"""Síntese avulsa da palavra de trabalho (working list) com a voz da Maya.

A resposta normal flui pelo pipecat (LLM → TTS → playback). A palavra de
working é pedida pelo renderer enquanto a Maya pensa e vive FORA do pipeline:
o backend sintetiza e devolve um WAV, o app toca. Nada atravessa a máquina
de estados de voz do ``VoiceBridge`` nem polui o espelho do chat.

Kokoro roda localmente (CPU) e é carregado lazy na primeira palavra — a
primeira síntese paga ~0,5s de load; as seguintes ~0,3s. Usa os mesmos
arquivos de modelo do pipecat (~/.cache/pipecat/kokoro-onnx/), que o
``KokoroTTSService`` do pipeline já baixa no primeiro launch.
"""

from __future__ import annotations

import asyncio
import io
import threading
import wave
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.settings import Settings

# Mesmos caminhos do KokoroTTSService do pipecat (fonte única de verdade).
_KOKORO_CACHE_DIR = Path.home() / ".cache" / "pipecat" / "kokoro-onnx"
_KOKORO_MODEL = _KOKORO_CACHE_DIR / "kokoro-v1.0.onnx"
_KOKORO_VOICES = _KOKORO_CACHE_DIR / "voices-v1.0.bin"


class WordSynthesizer:
    """Sintetiza palavras avulsas com a voz da Maya (Kokoro pt-BR).

    Thread-safe: o load do modelo e a inferência são CPU-bound e rodam em
    thread (``to_thread``); um lock serializa chamadas concorrentes (o
    renderer pede uma palavra por vez, mas a defesa é barata).
    """

    def __init__(self, settings: Settings) -> None:
        self._voice = settings.tts_voice
        self._lang = settings.tts_language.strip().lower()
        self._kokoro = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        """Modelo presente em disco (o pipeline já o baixou no startup)."""
        return _KOKORO_MODEL.exists() and _KOKORO_VOICES.exists()

    async def synthesize(self, text: str) -> tuple[bytes, int] | None:
        """Sintetiza `text` e devolve (WAV PCM16 mono, sample rate).

        None se o modelo não estiver disponível. A inferência roda em thread
        para não travar o event loop da bridge.
        """
        if not self.available:
            return None
        kokoro = await asyncio.to_thread(self._load)
        samples, rate = await asyncio.to_thread(
            kokoro.create, text, voice=self._voice, speed=1.0, lang=self._lang
        )
        return self._encode_wav(samples, rate), rate

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
    def _encode_wav(samples: object, rate: int) -> bytes:
        """Encoda os samples do Kokoro num WAV PCM mono 16-bit.

        O Kokoro devolve float32 em [-1, 1] — precisa converter para int16
        antes de gravar (mesmo padrão do KokoroTTSService do pipecat);
        gravar os bytes crus de float32 num WAV de 16 bits vira ruído alto.
        """
        import numpy as np

        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(pcm.tobytes())
        return buffer.getvalue()
