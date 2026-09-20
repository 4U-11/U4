"""Translation helpers using a self-hosted LibreTranslate service by default."""

from __future__ import annotations

from dataclasses import dataclass
import re
from uuid import uuid4

import httpx

from .content_models import ParsedBlock
from .settings import settings


ACADEMIC_GLOSSARY: dict[str, str] = {
    "assignment": "作业",
    "boundary condition": "边界条件",
    "dataset": "数据集",
    "derivative": "导数",
    "equation": "方程",
    "function": "函数",
    "gradient": "梯度",
    "homework": "作业",
    "integral": "积分",
    "lemma": "引理",
    "loss function": "损失函数",
    "matrix": "矩阵",
    "neural network": "神经网络",
    "proof": "证明",
    "theorem": "定理",
    "unit step response": "单位阶跃响应",
    "variable": "变量",
}

_INLINE_PROTECTED = re.compile(
    r"`[^`\r\n]+`|\\\(.*?\\\)|\\\[.*?\\\]|(?<!\\)\$[^$\r\n]+\$",
    re.DOTALL,
)
_IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*(?![A-Za-z0-9_])"
)
_ASSIGNMENT = re.compile(r"(?m)^\s*(?:const|let|var)\s+([A-Za-z_]\w*)\s*=")
_PY_ASSIGNMENT = re.compile(r"(?m)^\s*([A-Za-z_]\w*)\s*=(?!=)")
_FUNCTION_ARGS = re.compile(r"\bdef\s+[A-Za-z_]\w*\s*\(([^)]*)\)")
_FOR_TARGET = re.compile(r"\bfor\s+([A-Za-z_]\w*)\s+in\b")
_KEYWORDS = {
    "and", "as", "assert", "async", "await", "break", "class", "continue",
    "def", "del", "elif", "else", "except", "False", "finally", "for",
    "from", "global", "if", "import", "in", "is", "lambda", "None",
    "nonlocal", "not", "or", "pass", "raise", "return", "self", "True",
    "try", "while", "with", "yield", "const", "let", "var", "function",
}


class TranslationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProtectedText:
    text: str
    replacements: dict[str, str]
    marker_prefix: str

    def restore(self, translated_text: str) -> str:
        for marker in self.replacements:
            if translated_text.count(marker) != 1:
                raise TranslationError(
                    "TRANSLATION_INVALID_OUTPUT",
                    "翻译结果改变了代码、公式或术语占位符。",
                )
        if re.search(re.escape(self.marker_prefix) + r"\d+QXZ", translated_text):
            unknown = re.findall(
                re.escape(self.marker_prefix) + r"\d+QXZ", translated_text
            )
            if any(marker not in self.replacements for marker in unknown):
                raise TranslationError(
                    "TRANSLATION_INVALID_OUTPUT",
                    "翻译结果包含未知占位符。",
                )

        restored = translated_text
        for marker, value in self.replacements.items():
            restored = restored.replace(marker, value)
        return restored


def collect_variable_names(blocks: list[ParsedBlock]) -> set[str]:
    """Collect likely identifiers from formulae and explicit code declarations."""
    names: set[str] = set()
    for block in blocks:
        if not block.text:
            continue
        if block.kind == "formula":
            names.update(
                token
                for token in _IDENTIFIER.findall(block.text)
                if token not in _KEYWORDS
            )
        elif block.kind == "code":
            names.update(_ASSIGNMENT.findall(block.text))
            names.update(_PY_ASSIGNMENT.findall(block.text))
            names.update(_FOR_TARGET.findall(block.text))
            for argument_list in _FUNCTION_ARGS.findall(block.text):
                for argument in argument_list.split(","):
                    match = _IDENTIFIER.search(argument.strip())
                    if match and match.group(0) not in _KEYWORDS:
                        names.add(match.group(0))
    return names


def prepare_translation(
    text: str,
    variable_names: set[str],
    target_language: str = "zh-CN",
) -> ProtectedText:
    """Protect inline code, math, variable identifiers, and glossary terms."""
    prefix = f"ZXQ{uuid4().hex[:16].upper()}PH"
    while prefix in text:
        prefix = f"ZXQ{uuid4().hex[:16].upper()}PH"

    replacements: dict[str, str] = {}

    def protect(value: str) -> str:
        marker = f"{prefix}{len(replacements)}QXZ"
        replacements[marker] = value
        return marker

    protected = _INLINE_PROTECTED.sub(lambda match: protect(match.group(0)), text)

    # Identifiers found in formulae or declared in code take precedence over glossary terms.
    for source in sorted(
        (name for name in variable_names if name),
        key=len,
        reverse=True,
    ):
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(source)}(?![A-Za-z0-9_])"
        )
        protected = pattern.sub(lambda match: protect(match.group(0)), protected)

    variable_names_folded = {name.casefold() for name in variable_names}
    glossary_terms = (
        [
            (term, translated)
            for term, translated in ACADEMIC_GLOSSARY.items()
            if term.casefold() not in variable_names_folded
        ]
        if target_language.lower().startswith("zh")
        else []
    )
    for source, target in sorted(
        glossary_terms,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(source)}(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )
        protected = pattern.sub(lambda _match, value=target: protect(value), protected)

    return ProtectedText(
        text=protected,
        replacements=replacements,
        marker_prefix=prefix,
    )


def _target_language_code(target_language: str) -> str:
    return target_language.split("-", 1)[0].lower()


async def translate_with_libretranslate(
    text: str,
    target_language: str,
) -> str:
    """Call the configured LibreTranslate instance without exposing provider errors."""
    base_url = settings.libretranslate_url.strip().rstrip("/")
    if not base_url:
        raise TranslationError(
            "TRANSLATION_SERVICE_UNAVAILABLE",
            "尚未配置本地翻译服务。请启动 LibreTranslate 并设置 LIBRETRANSLATE_URL。",
        )

    payload: dict[str, str] = {
        "q": text,
        "source": "auto",
        "target": _target_language_code(target_language),
        "format": "text",
    }
    if settings.libretranslate_api_key:
        configured_key = settings.libretranslate_api_key.get_secret_value().strip()
        if configured_key:
            payload["api_key"] = configured_key

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(45.0, connect=8.0)
        ) as client:
            response = await client.post(f"{base_url}/translate", json=payload)
    except httpx.HTTPError as exc:
        raise TranslationError(
            "TRANSLATION_SERVICE_UNAVAILABLE",
            "无法连接本地翻译服务，请确认 LibreTranslate 正在运行。",
        ) from exc

    if response.status_code >= 400:
        raise TranslationError(
            "TRANSLATION_SERVICE_UNAVAILABLE",
            "本地翻译服务未能处理请求，请检查语言包和服务配置。",
        )

    try:
        translated = response.json().get("translatedText")
    except (ValueError, AttributeError):
        translated = None
    if not isinstance(translated, str) or not translated.strip():
        raise TranslationError(
            "TRANSLATION_INVALID_OUTPUT",
            "本地翻译服务返回了无效结果。",
        )
    return translated
