"""Qwen3-TTS service for Maya.

A local TTS provider wrapping the `qwen-tts` package (Qwen3-TTS, 0.6B).
Unlike the cloud ElevenLabs service, this runs a PyTorch model on the GPU:
the checkpoint is downloaded from the Hugging Face hub (~1.5-2 GB) and
loaded at construction, before the agent starts listening.

qwen-tts has no true streaming input yet (`non_streaming_mode=False` only
simulates it), so this service is buffer-and-generate: one model call per
aggregated sentence, one audio frame. Generation is blocking and runs in
a thread; a per-service lock serializes synthesis calls so a leftover
`asyncio.to_thread` from a barge-in cannot overlap the next turn's
generation on the same GPU.

For -Base checkpoints the voice prompt is frozen at construction:
`create_voice_clone_prompt` runs once at startup and every sentence
reuses the same prompt, so the cloned timbre is stable across the whole
session (empty `ref_text` = timbre-only/x-vector mode).

Heavy imports (torch, qwen_tts) live inside `_load_qwen_model` so tests
never pay for them and can monkeypatch the function instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import numpy as np
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import NOT_GIVEN, TTSSettings, assert_given
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language, resolve_language

# Qwen3-TTS language names, for the 10 languages the model supports.
# resolve_language() falls back to the base code with a warning for any
# other Language (the model raises at generate time → ErrorFrame).
QWEN3_LANGUAGE_MAP = {
    Language.EN: "English",
    Language.EN_AU: "English",
    Language.EN_CA: "English",
    Language.EN_GB: "English",
    Language.EN_GH: "English",
    Language.EN_HK: "English",
    Language.EN_IE: "English",
    Language.EN_IN: "English",
    Language.EN_KE: "English",
    Language.EN_NG: "English",
    Language.EN_NZ: "English",
    Language.EN_PH: "English",
    Language.EN_SG: "English",
    Language.EN_TZ: "English",
    Language.EN_US: "English",
    Language.EN_ZA: "English",
    Language.ZH: "Chinese",
    Language.ZH_CN: "Chinese",
    Language.ZH_HK: "Chinese",
    Language.ZH_TW: "Chinese",
    Language.JA: "Japanese",
    Language.JA_JP: "Japanese",
    Language.KO: "Korean",
    Language.KO_KR: "Korean",
    Language.DE: "German",
    Language.DE_AT: "German",
    Language.DE_BE: "German",
    Language.DE_CH: "German",
    Language.DE_DE: "German",
    Language.FR: "French",
    Language.FR_BE: "French",
    Language.FR_CA: "French",
    Language.FR_CH: "French",
    Language.FR_FR: "French",
    Language.RU: "Russian",
    Language.RU_RU: "Russian",
    Language.PT: "Portuguese",
    Language.PT_BR: "Portuguese",
    Language.PT_PT: "Portuguese",
    Language.ES: "Spanish",
    Language.ES_AR: "Spanish",
    Language.ES_BO: "Spanish",
    Language.ES_CL: "Spanish",
    Language.ES_CO: "Spanish",
    Language.ES_CR: "Spanish",
    Language.ES_CU: "Spanish",
    Language.ES_DO: "Spanish",
    Language.ES_EC: "Spanish",
    Language.ES_ES: "Spanish",
    Language.ES_GQ: "Spanish",
    Language.ES_GT: "Spanish",
    Language.ES_HN: "Spanish",
    Language.ES_MX: "Spanish",
    Language.ES_NI: "Spanish",
    Language.ES_PA: "Spanish",
    Language.ES_PE: "Spanish",
    Language.ES_PR: "Spanish",
    Language.ES_PY: "Spanish",
    Language.ES_SV: "Spanish",
    Language.ES_US: "Spanish",
    Language.ES_UY: "Spanish",
    Language.ES_VE: "Spanish",
    Language.IT: "Italian",
    Language.IT_CH: "Italian",
    Language.IT_IT: "Italian",
}


@dataclass
class Qwen3TTSSettings(TTSSettings):
    """Runtime-updatable settings for Qwen3TTSService.

    ``voice`` holds the CustomVoice speaker name; ``ref_audio``/``ref_text``
    configure voice cloning for -Base checkpoints.
    """

    instruct: str | None = field(default_factory=lambda: NOT_GIVEN)
    ref_audio: str | None = field(default_factory=lambda: NOT_GIVEN)
    ref_text: str | None = field(default_factory=lambda: NOT_GIVEN)


def _load_qwen_model(model_id: str, device: str, dtype: str, attn_implementation: str | None):
    """Load the Qwen3-TTS model from the Hugging Face hub (blocking).

    Heavy imports live here on purpose: tests import this module without
    paying for torch/qwen-tts and monkeypatch this function instead. Call
    from a thread when invoked outside of startup.
    """
    import torch
    from qwen_tts import Qwen3TTSModel

    # The project ships nvidia-cudnn-cu12 wheels (for ctranslate2/Whisper)
    # alongside torch's own cu13 wheels; torch's cudnn frontend then loads
    # the wrong libcudnn and any conv1d fails with
    # CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH (hit in the 12Hz tokenizer
    # vocoder). The 0.6B LM never uses cudnn and native CUDA conv kernels
    # are equivalent here — disable it for the whole process.
    torch.backends.cudnn.enabled = False

    dtype_map = {
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
        "float32": torch.float32,
    }
    logger.info(
        f"Loading Qwen3-TTS model {model_id} (device={device}, dtype={dtype})..."
    )
    return Qwen3TTSModel.from_pretrained(
        model_id,
        device_map=device,
        dtype=dtype_map[dtype],
        attn_implementation=attn_implementation,
    )


def _to_int16_bytes(wav) -> bytes:
    """Convert a float32 waveform (numpy array or torch tensor) to PCM bytes."""
    if hasattr(wav, "detach"):  # torch tensor (possibly on CUDA)
        wav = wav.detach().cpu().numpy()
    return (wav * 32767).astype(np.int16).tobytes()


class Qwen3TTSService(TTSService):
    Settings = Qwen3TTSSettings
    _settings: Settings
    # Frozen voice-clone prompt for -Base checkpoints (None for CustomVoice).
    _voice_clone_prompt: list | dict | None

    def __init__(
        self,
        *,
        model_id: str,
        device: str = "cuda",
        dtype: str = "bfloat16",
        attn_implementation: str | None = None,
        max_new_tokens: int = 4096,
        top_p: float | None = None,
        settings: Settings | None = None,
        **kwargs,
    ):
        default_settings = self.Settings(
            model=model_id,
            voice=None,
            language=None,  # converted to the qwen-tts name by the base class
            instruct=None,
            ref_audio=None,
            ref_text=None,
        )
        if settings is not None:
            default_settings.apply_update(settings)
        super().__init__(
            push_start_frame=True,
            push_stop_frames=True,
            settings=default_settings,
            **kwargs,
        )

        # Blocking model load (Kokoro precedent). Happens at startup, before
        # "Maya is listening" — a bad model id/speaker/device fails here,
        # not mid-conversation.
        self._model = _load_qwen_model(model_id, device, dtype, attn_implementation)
        self._gen_kwargs: dict = {"max_new_tokens": max_new_tokens}
        if top_p is not None:
            self._gen_kwargs["top_p"] = top_p

        self._speaker = assert_given(self._settings.voice)
        self._ref_audio = assert_given(self._settings.ref_audio)
        self._ref_text = assert_given(self._settings.ref_text)
        if self._ref_audio:
            # Frozen voice: extract the speaker features ONCE at startup and
            # reuse the same prompt for every sentence. Empty ref_text →
            # timbre-only (x-vector) clone; provided ref_text → full ICL
            # clone. Both are "locked" here: per-sentence generate calls
            # only pass the precomputed prompt, so the timbre never drifts.
            self._voice_clone_prompt = self._model.create_voice_clone_prompt(
                ref_audio=self._ref_audio,
                ref_text=self._ref_text or None,
                x_vector_only_mode=not self._ref_text,
            )
        else:
            supported = self._model.get_supported_speakers()
            if supported is None:
                raise ValueError(
                    f"{model_id} does not expose a speaker list (only "
                    "CustomVoice checkpoints do; use a -Base checkpoint with "
                    "QWEN3_REF_AUDIO for other models)."
                )
            # The hub lists speakers in lowercase ("ryan"), while the model
            # card uses "Ryan" — match case-insensitively and normalize to
            # the model's canonical name.
            canonical = {name.lower(): name for name in supported}
            if self._speaker.lower() not in canonical:
                raise ValueError(
                    f"QWEN3_SPEAKER '{self._speaker}' is not supported by {model_id} "
                    f"(supported: {', '.join(sorted(supported))})."
                )
            self._speaker = canonical[self._speaker.lower()]
            self._voice_clone_prompt = None

        # asyncio.to_thread work survives cancellation (barge-in); the lock
        # keeps a leftover generation from overlapping the next turn's.
        self._synthesis_lock = asyncio.Lock()

    def can_generate_metrics(self) -> bool:
        """Indicate that this service supports TTFB and usage metrics."""
        return True

    def language_to_service_language(self, language: Language) -> str:
        """Convert a Language enum to a qwen-tts language name."""
        return resolve_language(language, QWEN3_LANGUAGE_MAP, use_base_code=True)

    async def run_tts(
        self, text: str, context_id: str
    ) -> AsyncGenerator[Frame | None, None]:
        """Synthesize one aggregated sentence with Qwen3-TTS.

        One generate call per sentence, one audio frame. The call runs in a
        thread because it blocks the GPU for seconds; the returned native
        sample rate is resampled (SOXR) to the pipeline's sample rate.
        """
        try:
            await self.start_tts_usage_metrics(text)

            language = assert_given(self._settings.language)
            async with self._synthesis_lock:
                wavs, sr = await asyncio.to_thread(self._synthesize, text, language)
            await self.stop_ttfb_metrics()

            audio_int16 = _to_int16_bytes(wavs[0])
            audio_data = await self._resampler.resample(
                audio_int16, sr, self.sample_rate
            )

            yield TTSAudioRawFrame(
                audio=audio_data,
                sample_rate=self.sample_rate,
                num_channels=1,
                context_id=context_id,
            )
        except Exception as e:  # noqa: BLE001 — same pattern as Kokoro: any failure becomes an ErrorFrame, never crashes the pipeline
            yield ErrorFrame(error=f"Qwen3 TTS error: {e}")
        finally:
            await self.stop_ttfb_metrics()

    def _synthesize(self, text: str, language: str):
        """Blocking generate call; runs inside asyncio.to_thread.

        All keyword args: generate_custom_voice is (text, speaker, ...)
        while generate_voice_clone is (text, language, ...) — positional
        calls would land on the wrong parameter. For -Base checkpoints the
        voice prompt was frozen at construction; no per-call re-extraction.
        """
        if self._ref_audio:
            return self._model.generate_voice_clone(
                text=text,
                language=language,
                voice_clone_prompt=self._voice_clone_prompt,
                **self._gen_kwargs,
            )
        return self._model.generate_custom_voice(
            text=text,
            speaker=self._speaker,
            language=language,
            instruct=assert_given(self._settings.instruct) or None,
            **self._gen_kwargs,
        )
