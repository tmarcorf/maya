from __future__ import annotations

import asyncio
import logging
import tempfile
import threading
from typing import Protocol

from faster_whisper import WhisperModel
from livekit import rtc
from livekit.agents import APIConnectOptions, LanguageCode, stt
from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer, is_given

from .config import WhisperSettings

logger = logging.getLogger("maya.whisper")

_model: WhisperModel | None = None
_model_lock = threading.Lock()
_inference_lock = threading.Lock()


class Transcriber(Protocol):
    @property
    def model(self) -> str: ...

    def prewarm(self) -> None: ...

    def transcribe(self, wav_bytes: bytes, language: str | None) -> str: ...


def _load_model(model_size: str, device: str, compute_type: str) -> WhisperModel:
    global _model
    with _model_lock:
        if _model is not None:
            return _model

        logger.info(
            "loading faster-whisper: model=%s device=%s compute_type=%s",
            model_size,
            device,
            compute_type,
        )
        try:
            _model = WhisperModel(model_size, device=device, compute_type=compute_type)
        except Exception:
            logger.warning(
                "failed to load faster-whisper on %s/%s; falling back to cpu/int8",
                device,
                compute_type,
                exc_info=True,
            )
            _model = WhisperModel(model_size, device="cpu", compute_type="int8")
        return _model


class FasterWhisperTranscriber:
    def __init__(self, *, model_size: str, device: str, compute_type: str) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type

    @property
    def model(self) -> str:
        return f"faster-whisper-{self._model_size}"

    def prewarm(self) -> None:
        threading.Thread(
            target=_load_model,
            args=(self._model_size, self._device, self._compute_type),
            daemon=True,
            name="whisper-prewarm",
        ).start()

    def transcribe(self, wav_bytes: bytes, language: str | None) -> str:
        model = _load_model(self._model_size, self._device, self._compute_type)
        with tempfile.NamedTemporaryFile(suffix=".wav") as wav_file:
            wav_file.write(wav_bytes)
            wav_file.flush()
            with _inference_lock:
                segments, _ = model.transcribe(
                    wav_file.name,
                    language=language,
                    beam_size=1,
                    vad_filter=False,
                    condition_on_previous_text=False,
                    without_timestamps=True,
                )
                return "".join(segment.text for segment in segments).strip()


class WhisperSTT(stt.STT):
    def __init__(
        self,
        *,
        transcriber: Transcriber,
        language: str | None = None,
    ) -> None:
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        self._transcriber = transcriber
        self._language = language

    @property
    def model(self) -> str:
        return self._transcriber.model

    @property
    def provider(self) -> str:
        return "local"

    def prewarm(self) -> None:
        self._transcriber.prewarm()

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        frame = rtc.combine_audio_frames(buffer)
        wav_bytes = frame.to_wav_bytes()

        lang = language if is_given(language) else self._language
        lang = lang.split("-")[0].lower() if lang else None

        text = await asyncio.to_thread(self._transcriber.transcribe, wav_bytes, lang)
        if not text:
            return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT, alternatives=[])

        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[
                stt.SpeechData(
                    text=text,
                    language=LanguageCode(lang) if lang else LanguageCode(""),
                )
            ],
        )


def build_whisper_stt(settings: WhisperSettings, language: str | None) -> WhisperSTT:
    transcriber = FasterWhisperTranscriber(
        model_size=settings.model,
        device=settings.device,
        compute_type=settings.compute_type,
    )
    return WhisperSTT(transcriber=transcriber, language=language)
