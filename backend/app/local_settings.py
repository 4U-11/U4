"""Local single-user AI preferences and Windows DPAPI-protected API keys."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import tempfile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


ProviderId = Literal["openai", "deepseek"]
PROVIDER_DEFAULTS: dict[ProviderId, dict[str, str]] = {
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
    },
}

_APP_DATA_DIR = Path(
    os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
) / "CourseMaterialLearningAssistant"
_PREFERENCES_PATH = _APP_DATA_DIR / "ai-preferences.json"
_KEYS_PATH = _APP_DATA_DIR / "ai-keys.dpapi"


class ProviderPreference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=128)


class AIPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderId = "openai"
    profiles: dict[ProviderId, ProviderPreference] = Field(default_factory=dict)


def _read_preferences() -> AIPreferences:
    try:
        return AIPreferences.model_validate_json(
            _PREFERENCES_PATH.read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return AIPreferences()
    except (OSError, ValidationError, ValueError):
        return AIPreferences()


def _write_atomic(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(contents)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("安全保存 API Key 目前需要 Windows 用户凭据保护")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    input_buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte))
    )
    output_blob = _DataBlob()
    blob_pointer = ctypes.byref(input_blob)
    output_pointer = ctypes.byref(output_blob)
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN

    if protect:
        function = crypt32.CryptProtectData
        function.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.c_wchar_p,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(_DataBlob),
        ]
        function.restype = ctypes.c_int
        succeeded = function(
            blob_pointer,
            "Course Material Learning Assistant API keys",
            None,
            None,
            None,
            flags,
            output_pointer,
        )
    else:
        function = crypt32.CryptUnprotectData
        function.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(_DataBlob),
        ]
        function.restype = ctypes.c_int
        succeeded = function(
            blob_pointer, None, None, None, None, flags, output_pointer
        )

    if not succeeded:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(output_blob.pbData)


def _read_keys() -> dict[ProviderId, str]:
    try:
        encrypted = _KEYS_PATH.read_bytes()
    except FileNotFoundError:
        return {}
    try:
        decoded = json.loads(_dpapi(encrypted, protect=False))
        if not isinstance(decoded, dict):
            return {}
        return {
            provider: value
            for provider, value in decoded.items()
            if provider in PROVIDER_DEFAULTS
            and isinstance(value, str)
            and value.strip()
        }
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _write_keys(keys: dict[ProviderId, str]) -> None:
    if not keys:
        _KEYS_PATH.unlink(missing_ok=True)
        return
    serialized = json.dumps(keys, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    _write_atomic(_KEYS_PATH, _dpapi(serialized, protect=True))


def get_preferences() -> AIPreferences:
    return _read_preferences()


def get_key(provider: ProviderId) -> str | None:
    return _read_keys().get(provider)


def get_provider_model(provider: ProviderId) -> str:
    preferences = _read_preferences()
    profile = preferences.profiles.get(provider)
    return profile.model if profile else PROVIDER_DEFAULTS[provider]["model"]


def get_active_configuration() -> tuple[ProviderId, str, str, str | None]:
    """Return selected provider, URL, model, and its locally saved API key."""
    preferences = _read_preferences()
    provider = preferences.provider
    base_url = PROVIDER_DEFAULTS[provider]["base_url"]
    return provider, base_url, get_provider_model(provider), get_key(provider)


def get_saved_active_key() -> str | None:
    return get_active_configuration()[3]


def save_provider_configuration(
    provider: ProviderId,
    model: str,
    api_key: str | None,
) -> AIPreferences:
    preferences = _read_preferences()
    profiles = dict(preferences.profiles)
    profiles[provider] = ProviderPreference(model=model.strip())
    updated = AIPreferences(provider=provider, profiles=profiles)
    if api_key and api_key.strip():
        keys = _read_keys()
        keys[provider] = api_key.strip()
        _write_keys(keys)
    _write_atomic(
        _PREFERENCES_PATH,
        updated.model_dump_json(indent=2).encode("utf-8"),
    )
    return updated


def delete_key(provider: ProviderId) -> None:
    keys = _read_keys()
    keys.pop(provider, None)
    _write_keys(keys)


def provider_has_key(provider: ProviderId) -> bool:
    return bool(get_key(provider))

