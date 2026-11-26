from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LANGUAGE_NAMES = {
    "pt": "Brazilian Portuguese",
    "en": "English",
}


@dataclass(frozen=True, slots=True)
class MayaSettings:
    language: str
    prompt_path: Path

    @property
    def language_code(self) -> str:
        return self.language.split("-")[0].lower()

    @property
    def language_name(self) -> str:
        return LANGUAGE_NAMES.get(self.language_code, self.language)


@dataclass(frozen=True, slots=True)
class WhisperSettings:
    model: str
    device: str
    compute_type: str


@dataclass(frozen=True, slots=True)
class DeepSeekSettings:
    api_key: str
    model: str
    base_url: str
    temperature: float


@dataclass(frozen=True, slots=True)
class ElevenLabsSettings:
    api_key: str
    voice_id: str
    model_id: str


@dataclass(frozen=True, slots=True)
class TurnSettings:
    detector_version: str
    endpointing_mode: str
    min_endpointing_delay: float
    max_endpointing_delay: float
    min_interruption_duration: float


@dataclass(frozen=True, slots=True)
class WebSearchSettings:
    enabled: bool
    api_key: str
    max_results: int
    timeout_seconds: float
    cache_ttl_minutes: int


@dataclass(frozen=True, slots=True)
class WebExtractSettings:
    enabled: bool
    max_urls: int
    max_chars: int
    timeout_seconds: float
    cache_ttl_minutes: int


@dataclass(frozen=True, slots=True)
class AppSettings:
    maya: MayaSettings
    whisper: WhisperSettings
    deepseek: DeepSeekSettings
    elevenlabs: ElevenLabsSettings
    turn: TurnSettings
    web_search: WebSearchSettings
    web_extract: WebExtractSettings


def _env(env: Mapping[str, str], name: str, default: str = "") -> str:
    return (env.get(name) or default).strip()


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _env(env, name)
    return float(raw) if raw else default


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _env(env, name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _env(env, name)
    if not raw:
        return default
    normalized = raw.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _require(value: str, name: str) -> str:
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _normalize_language(value: str) -> str:
    parts = value.replace("_", "-").split("-")
    if len(parts) == 1:
        return parts[0].lower()
    return f"{parts[0].lower()}-{parts[1].upper()}"


def _resolve_prompt_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _load_turn_settings(env: Mapping[str, str]) -> TurnSettings:
    detector_version = _env(env, "TURN_DETECTOR_VERSION", "v1-mini")
    if detector_version not in {"v1", "v1-mini"}:
        raise ValueError("TURN_DETECTOR_VERSION must be 'v1' or 'v1-mini'")

    endpointing_mode = _env(env, "ENDPOINTING_MODE", "fixed").lower()
    if endpointing_mode not in {"fixed", "dynamic"}:
        raise ValueError("ENDPOINTING_MODE must be 'fixed' or 'dynamic'")

    min_endpointing_delay = _env_float(env, "MIN_ENDPOINTING_DELAY", 0.3)
    max_endpointing_delay = _env_float(env, "MAX_ENDPOINTING_DELAY", 2.5)
    if min_endpointing_delay < 0 or max_endpointing_delay <= min_endpointing_delay:
        raise ValueError(
            "Endpointing delays must satisfy 0 <= MIN_ENDPOINTING_DELAY < MAX_ENDPOINTING_DELAY"
        )

    min_interruption_duration = _env_float(env, "MIN_INTERRUPTION_DURATION", 0.4)
    if min_interruption_duration < 0:
        raise ValueError("MIN_INTERRUPTION_DURATION must be >= 0")

    return TurnSettings(
        detector_version=detector_version,
        endpointing_mode=endpointing_mode,
        min_endpointing_delay=min_endpointing_delay,
        max_endpointing_delay=max_endpointing_delay,
        min_interruption_duration=min_interruption_duration,
    )


def _load_whisper_settings(env: Mapping[str, str]) -> WhisperSettings:
    device = _env(env, "WHISPER_DEVICE", "auto").lower()
    if device not in {"auto", "cpu", "cuda"}:
        raise ValueError("WHISPER_DEVICE must be 'auto', 'cpu' or 'cuda'")

    return WhisperSettings(
        model=_env(env, "WHISPER_MODEL", "medium"),
        device=device,
        compute_type=_env(env, "WHISPER_COMPUTE_TYPE", "default").lower(),
    )


def _load_deepseek_settings(env: Mapping[str, str]) -> DeepSeekSettings:
    temperature = _env_float(env, "DEEPSEEK_TEMPERATURE", 0.6)
    if not 0 <= temperature <= 2:
        raise ValueError("DEEPSEEK_TEMPERATURE must be between 0 and 2")

    return DeepSeekSettings(
        api_key=_require(_env(env, "DEEPSEEK_API_KEY"), "DEEPSEEK_API_KEY"),
        model=_env(env, "DEEPSEEK_MODEL", "deepseek-flash"),
        base_url=_env(env, "DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        or "https://api.deepseek.com",
        temperature=temperature,
    )


def _load_elevenlabs_settings(env: Mapping[str, str]) -> ElevenLabsSettings:
    return ElevenLabsSettings(
        api_key=_require(_env(env, "ELEVENLABS_API_KEY"), "ELEVENLABS_API_KEY"),
        voice_id=_require(_env(env, "ELEVENLABS_VOICE_ID"), "ELEVENLABS_VOICE_ID"),
        model_id=_env(env, "ELEVENLABS_MODEL_ID", "eleven_flash_v2_5"),
    )


def _load_web_search_settings(env: Mapping[str, str]) -> WebSearchSettings:
    enabled = _env_bool(env, "WEB_SEARCH_ENABLED", False)
    max_results = _env_int(env, "WEB_SEARCH_MAX_RESULTS", 3)
    if not 1 <= max_results <= 10:
        raise ValueError("WEB_SEARCH_MAX_RESULTS must be between 1 and 10")

    timeout_seconds = _env_float(env, "WEB_SEARCH_TIMEOUT_SECONDS", 8.0)
    if not 2 <= timeout_seconds <= 30:
        raise ValueError("WEB_SEARCH_TIMEOUT_SECONDS must be between 2 and 30")

    cache_ttl_minutes = _env_int(env, "WEB_SEARCH_CACHE_TTL_MINUTES", 10)
    if not 0 <= cache_ttl_minutes <= 1440:
        raise ValueError("WEB_SEARCH_CACHE_TTL_MINUTES must be between 0 and 1440")

    return WebSearchSettings(
        enabled=enabled,
        api_key=_env(env, "TAVILY_API_KEY"),
        max_results=max_results,
        timeout_seconds=timeout_seconds,
        cache_ttl_minutes=cache_ttl_minutes,
    )


def _load_web_extract_settings(env: Mapping[str, str]) -> WebExtractSettings:
    enabled = _env_bool(env, "WEB_EXTRACT_ENABLED", True)
    max_urls = _env_int(env, "WEB_EXTRACT_MAX_URLS", 2)
    if not 1 <= max_urls <= 5:
        raise ValueError("WEB_EXTRACT_MAX_URLS must be between 1 and 5")

    max_chars = _env_int(env, "WEB_EXTRACT_MAX_CHARS", 6000)
    if not 500 <= max_chars <= 15000:
        raise ValueError("WEB_EXTRACT_MAX_CHARS must be between 500 and 15000")

    timeout_seconds = _env_float(env, "WEB_EXTRACT_TIMEOUT_SECONDS", 8.0)
    if not 2 <= timeout_seconds <= 30:
        raise ValueError("WEB_EXTRACT_TIMEOUT_SECONDS must be between 2 and 30")

    cache_ttl_minutes = _env_int(env, "WEB_EXTRACT_CACHE_TTL_MINUTES", 10)
    if not 0 <= cache_ttl_minutes <= 1440:
        raise ValueError("WEB_EXTRACT_CACHE_TTL_MINUTES must be between 0 and 1440")

    return WebExtractSettings(
        enabled=enabled,
        max_urls=max_urls,
        max_chars=max_chars,
        timeout_seconds=timeout_seconds,
        cache_ttl_minutes=cache_ttl_minutes,
    )


def load_settings(env: Mapping[str, str] | None = None) -> AppSettings:
    source = os.environ if env is None else env
    language = _normalize_language(_env(source, "MAYA_LANGUAGE", "pt-BR") or "pt-BR")
    prompt_path = _resolve_prompt_path(
        _env(source, "MAYA_PROMPT_PATH", "prompts/maya.md") or "prompts/maya.md"
    )

    return AppSettings(
        maya=MayaSettings(language=language, prompt_path=prompt_path),
        whisper=_load_whisper_settings(source),
        deepseek=_load_deepseek_settings(source),
        elevenlabs=_load_elevenlabs_settings(source),
        turn=_load_turn_settings(source),
        web_search=_load_web_search_settings(source),
        web_extract=_load_web_extract_settings(source),
    )
