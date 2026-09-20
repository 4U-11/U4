"""AI provider configuration endpoints for this local single-user app."""

from __future__ import annotations

import re

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .errors import ApiError
from .local_settings import (
    PROVIDER_DEFAULTS,
    ProviderId,
    delete_key,
    get_key,
    get_preferences,
    get_provider_model,
    provider_has_key,
    save_provider_configuration,
)
from .settings import settings


router = APIRouter(prefix="/api/settings", tags=["settings"])
_INVALID_KEY_CHARS = re.compile(r"[\r\n\x00]")


class AIProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderId
    model: str = Field(min_length=1, max_length=128)
    api_key: str | None = Field(default=None, max_length=4096)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        clean = value.strip()
        if not clean or any(ord(character) < 32 for character in clean):
            raise ValueError("Invalid model ID")
        return clean

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if _INVALID_KEY_CHARS.search(clean):
            raise ValueError("Invalid API key")
        return clean or None


class AIProviderTest(AIProviderUpdate):
    pass


def _api_key_is_available(provider: ProviderId) -> bool:
    if provider_has_key(provider):
        return True
    return provider == "openai" and bool(
        settings.platform_ai_api_key
        and settings.platform_ai_api_key.get_secret_value().strip()
    )


def _configured_key(provider: ProviderId, submitted_key: str | None) -> str:
    if submitted_key:
        return submitted_key
    saved = get_key(provider)
    if saved:
        return saved
    if provider == "openai" and settings.platform_ai_api_key:
        environment_key = settings.platform_ai_api_key.get_secret_value().strip()
        if environment_key:
            return environment_key
    raise ApiError(400, "AI_KEY_REQUIRED", "请先填写 API Key")


async def _check_provider(*, provider: ProviderId, model: str, api_key: str) -> None:
    base_url = PROVIDER_DEFAULTS[provider]["base_url"].rstrip("/")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return a JSON object with ok set to true."},
            {"role": "user", "content": "Return the requested JSON object."},
        ],
        "response_format": {"type": "json_object"},
    }
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
    except httpx.HTTPError as exc:
        raise ApiError(
            502,
            "AI_PROVIDER_UNAVAILABLE",
            "无法连接 AI 服务，请检查网络后重试。",
        ) from exc

    if response.status_code in {401, 403}:
        raise ApiError(401, "AI_KEY_REJECTED", "服务商拒绝了该 API Key，请检查密钥。")
    if response.status_code == 429:
        raise ApiError(
            429,
            "AI_PROVIDER_RATE_LIMITED",
            "服务商限流或额度不足，请稍后重试并检查账户额度。",
        )
    if response.status_code >= 500:
        raise ApiError(
            502,
            "AI_PROVIDER_UNAVAILABLE",
            "AI 服务暂时不可用，请稍后重试。",
        )
    if response.status_code >= 400:
        raise ApiError(
            400,
            "AI_PROVIDER_REJECTED_REQUEST",
            "服务商未接受请求，请检查模型 ID 是否正确。",
        )


@router.get("/ai", summary="读取 AI 服务商配置状态")
async def read_ai_configuration():
    preferences = get_preferences()
    profiles = {}
    for provider, defaults in PROVIDER_DEFAULTS.items():
        model = get_provider_model(provider)
        profiles[provider] = {
            "name": defaults["name"],
            "base_url": defaults["base_url"],
            "model": model,
            "has_api_key": _api_key_is_available(provider),
        }
    return {
        "provider": preferences.provider,
        "profiles": profiles,
        "configured": _api_key_is_available(preferences.provider),
    }


@router.put("/ai", summary="保存 AI 服务商配置")
async def update_ai_configuration(request: AIProviderUpdate):
    try:
        preferences = save_provider_configuration(
            request.provider,
            request.model,
            request.api_key,
        )
    except (OSError, RuntimeError) as exc:
        raise ApiError(
            500,
            "AI_SETTINGS_SAVE_FAILED",
            "无法安全保存配置。请在 Windows 本机运行后重试。",
        ) from exc
    return {
        "provider": preferences.provider,
        "model": request.model,
        "has_api_key": _api_key_is_available(request.provider),
        "message": "配置已保存。",
    }


@router.post("/ai/test", summary="测试 AI 服务商连接")
async def test_ai_configuration(request: AIProviderTest):
    api_key = _configured_key(request.provider, request.api_key)
    await _check_provider(
        provider=request.provider,
        model=request.model,
        api_key=api_key,
    )
    return {"ok": True, "message": "连接成功，模型已接受测试请求。"}


@router.delete("/ai/{provider}/key", summary="删除指定服务商保存的 API Key")
async def remove_ai_key(provider: ProviderId):
    try:
        delete_key(provider)
    except (OSError, RuntimeError) as exc:
        raise ApiError(500, "AI_KEY_DELETE_FAILED", "无法删除本地 API Key。") from exc
    return {"ok": True, "provider": provider, "has_api_key": _api_key_is_available(provider)}
