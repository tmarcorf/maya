"""WordSynthesizer (palavra de working) no provider ElevenLabs.

O caminho Kokoro depende de modelo ONNX em disco e libs pesadas; fica coberto
pelo comportamento "indisponível → None" (modelo ausente nos testes). O
ElevenLabs é testado com um httpx.MockTransport injetado via ``http_client``.
"""

from __future__ import annotations

import io
import json
import wave

import httpx
import pytest

from pipeline.word_tts import WordSynthesisError, WordSynthesizer
from tests.conftest import make_settings

PCM_22050 = b"\x00\x00\xff\xff\x01\x00" * 100  # 1s a 22050 Hz, qualquer conteúdo


def _settings(**overrides):
    values = {
        "tts_provider": "elevenlabs",
        "elevenlabs_api_key": "el-test-key",
        "elevenlabs_voice_id": "el-voice",
    }
    values.update(overrides)
    return make_settings(**values)


async def _synth_with(handler, **settings_overrides) -> WordSynthesizer:
    # Client mockado fica aberto de propósito: o synth só fecha clientes que
    # ele mesmo cria (o MockTransport não segura recurso de SO).
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WordSynthesizer(_settings(**settings_overrides), http_client=client)


async def test_elevenlabs_synthesize_returns_wav():
    """Chama o endpoint certo (chave/voz/modelo) e embrulha o PCM em WAV."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=PCM_22050)

    synth = await _synth_with(handler)
    assert synth.available

    wav_bytes, rate = await synth.synthesize("analisando")

    assert str(seen["url"]).startswith("https://api.elevenlabs.io/v1/text-to-speech/el-voice")
    assert "output_format=pcm_22050" in str(seen["url"])
    assert seen["headers"]["xi-api-key"] == "el-test-key"
    assert seen["body"] == {"text": "analisando", "model_id": "eleven_flash_v2_5"}
    assert rate == 22050

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 22050
        # PCM_22050 = 600 bytes = 300 frames; readframes devolve esse tanto.
        assert wav.readframes(300) == PCM_22050


async def test_elevenlabs_api_error_surfaces_message():
    """Erro da API vira WordSynthesisError com a mensagem do campo detail."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"detail": {"message": "voz inválida ou sem acesso."}},
        )

    synth = await _synth_with(handler)
    with pytest.raises(WordSynthesisError, match="voz inválida ou sem acesso"):
        await synth.synthesize("analisando")


async def test_elevenlabs_network_error():
    """Rede fora do ar vira WordSynthesisError (e não propaga HTTPError)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    synth = await _synth_with(handler)
    with pytest.raises(WordSynthesisError, match="inalcançável"):
        await synth.synthesize("analisando")


async def test_elevenlabs_missing_key_is_unavailable():
    """Sem chave configurada o sintetizador reporta indisponível (None)."""
    synth = await _synth_with(lambda request: httpx.Response(200, content=b""), elevenlabs_api_key="")
    assert not synth.available
    assert await synth.synthesize("analisando") is None


async def test_kokoro_without_model_is_unavailable(monkeypatch, tmp_path):
    """Kokoro sem modelo em disco → indisponível (None), sem tocar no modelo."""
    import pipeline.word_tts as word_tts_module

    missing = tmp_path / "missing"
    monkeypatch.setattr(word_tts_module, "_KOKORO_MODEL", missing / "kokoro-v1.0.onnx")
    monkeypatch.setattr(word_tts_module, "_KOKORO_VOICES", missing / "voices-v1.0.bin")

    synth = WordSynthesizer(make_settings(tts_provider="kokoro"))
    assert not synth.available
    assert await synth.synthesize("analisando") is None
