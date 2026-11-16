"""Síntese avulsa da palavra de trabalho (working list) com a voz da Maya.

A resposta normal flui pelo pipecat (LLM → TTS → playback). A palavra de
working é pedida pelo renderer enquanto a Maya pensa e vive FORA do pipeline:
o backend sintetiza e devolve um WAV, o app toca. Nada atravessa a máquina
de estados de voz do ``VoiceBridge`` nem polui o espelho do chat.

O provider é o do pipeline (``TTS_PROVIDER``):

* **kokoro** — roda localmente (CPU) e é carregado lazy na primeira palavra;
  a primeira síntese paga ~0,5s de load, as seguintes ~0,3s. Usa os mesmos
  arquivos de modelo do pipecat (~/.cache/pipecat/kokoro-onnx/), que o
  ``KokoroTTSService`` do pipeline já baixa no primeiro launch.
* **elevenlabs** — sintetiza na nuvem via REST (``/v1/text-to-speech``) com a
  mesma chave/voz/modelo do pipeline principal. A primeira palavra paga a
  latência da rede (~0,3–0,5s); a chamada volta como PCM 22050 Hz e é
  embrulhada em WAV — o app toca o mesmo formato nos dois providers.
"""

from __future__ import annotations

import asyncio
import io
import threading
import wave
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

    from config.settings import Settings

# Mesmos caminhos do KokoroTTSService do pipecat (fonte única de verdade).
_KOKORO_CACHE_DIR = Path.home() / ".cache" / "pipecat" / "kokoro-onnx"
_KOKORO_MODEL = _KOKORO_CACHE_DIR / "kokoro-v1.0.onnx"
_KOKORO_VOICES = _KOKORO_CACHE_DIR / "voices-v1.0.bin"

# ElevenLabs: REST text-to-speech; pcm_22050 devolve PCM int16 mono cru (sem
# codec no backend — só o header WAV é acrescentado).
_ELEVEN_ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech"
_ELEVEN_OUTPUT_RATE = 22050


class WordSynthesisError(RuntimeError):
    """Falha ao sintetizar no ElevenLabs (rede, quota, voz/modelo inválidos...)."""


class WordSynthesizer:
    """Sintetiza palavras avulsas com a voz da Maya (provider do ``TTS_PROVIDER``).

    O caminho Kokoro é thread-safe: load do modelo e inferência são
    CPU-bound e rodam em thread (``to_thread``); um lock serializa chamadas
    concorrentes. O caminho ElevenLabs é assíncrono e sem estado — cada
    chamada usa um ``AsyncClient`` próprio e é independente das demais.
    """

    def __init__(
        self, settings: Settings, *, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self._provider = settings.tts_provider
        # Kokoro.
        self._voice = settings.tts_voice
        self._lang = settings.tts_language.strip().lower()
        self._kokoro = None
        self._lock = threading.Lock()
        # ElevenLabs (usado só quando tts_provider == "elevenlabs").
        self._eleven_api_key = settings.elevenlabs_api_key
        self._eleven_voice_id = settings.elevenlabs_voice_id
        self._eleven_model_id = settings.elevenlabs_model_id
        # Cliente injetável nos testes (httpx.MockTransport).
        self._http_client = http_client

    @property
    def available(self) -> bool:
        """Provider pronto para sintetizar.

        Kokoro: modelo presente em disco (o pipeline já o baixou no startup).
        ElevenLabs: chave e voz configuradas (o ``load_settings`` já garante
        quando o provider é elevenlabs).
        """
        if self._provider == "elevenlabs":
            return bool(self._eleven_api_key and self._eleven_voice_id)
        return _KOKORO_MODEL.exists() and _KOKORO_VOICES.exists()

    async def synthesize(self, text: str) -> tuple[bytes, int] | None:
        """Sintetiza `text` e devolve (WAV PCM16 mono, sample rate).

        None se o provider não estiver disponível. A inferência do Kokoro
        roda em thread para não travar o event loop da bridge; o ElevenLabs
        levanta ``WordSynthesisError`` quando a API falha — o chamador decide
        como reportar (a ponte responde com um ack de erro).
        """
        if not self.available:
            return None
        if self._provider == "elevenlabs":
            return await self._synthesize_elevenlabs(text)
        kokoro = await asyncio.to_thread(self._load)
        samples, rate = await asyncio.to_thread(
            kokoro.create, text, voice=self._voice, speed=1.0, lang=self._lang
        )
        return self._encode_wav(self._to_int16_pcm(samples), rate), rate

    async def _synthesize_elevenlabs(self, text: str) -> tuple[bytes, int]:
        import httpx

        # Client por chamada: a palavra é um evento raro (uma por pensamento)
        # e um client persistente exigiria shutdown explícito; a latência de
        # conexão perdida é desprezível perto da síntese em si. Nos testes um
        # client com MockTransport é injetado e o synth não o fecha.
        client = self._http_client or httpx.AsyncClient(timeout=30)
        try:
            response = await client.post(
                f"{_ELEVEN_ENDPOINT}/{self._eleven_voice_id}",
                params={"output_format": "pcm_22050"},
                headers={"xi-api-key": self._eleven_api_key},
                json={"text": text, "model_id": self._eleven_model_id},
            )
        except httpx.HTTPError as e:
            raise WordSynthesisError(f"ElevenLabs inalcançável: {e}") from e
        finally:
            if self._http_client is None:
                await client.aclose()
        if response.status_code != 200:
            raise WordSynthesisError(self._eleven_error(response))
        # pcm_22050 já é PCM int16 — vira WAV direto (o encode float32→int16
        # do Kokoro não se aplica aqui).
        return self._encode_wav(response.content, _ELEVEN_OUTPUT_RATE), _ELEVEN_OUTPUT_RATE

    @staticmethod
    def _eleven_error(response: httpx.Response) -> str:
        """Mensagem amigável do corpo de erro da API (campo ``detail``)."""
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        if isinstance(detail, dict):
            return str(detail.get("message") or detail)
        if detail:
            return str(detail)
        return f"ElevenLabs retornou HTTP {response.status_code}."

    def _load(self):
        with self._lock:
            if self._kokoro is None:
                from espeakng_loader import get_data_path
                from kokoro_onnx import EspeakConfig, Kokoro

                # Caminho do espeak-ng data resolvido pelo loader do próprio
                # kokoro-onnx (portátil entre distribuições/pacotes).
                self._kokoro = Kokoro(
                    model_path=str(_KOKORO_MODEL),
                    voices_path=str(_KOKORO_VOICES),
                    espeak_config=EspeakConfig(data_path=get_data_path()),
                )
            return self._kokoro

    @staticmethod
    def _to_int16_pcm(samples: object) -> bytes:
        """Float32 em [-1, 1] do Kokoro → PCM int16 little-endian (numpy lazy)."""
        import numpy as np

        return (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

    @staticmethod
    def _encode_wav(pcm: bytes, rate: int) -> bytes:
        """Encoda PCM int16 mono num WAV PCM 16-bit.

        O Kokoro devolve float32 — o chamador converte com ``_to_int16_pcm``
        antes de gravar (mesmo padrão do KokoroTTSService do pipecat);
        gravar os bytes crus de float32 num WAV de 16 bits vira ruído alto.
        """
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(pcm)
        return buffer.getvalue()
