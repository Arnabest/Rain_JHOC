from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode


@dataclass(frozen=True, slots=True)
class SanitizedDataPayload:
    content: Mapping[str, Any]
    stripped_tokens_count: int
    flags: tuple[str, ...]
    purity_score: float
    digest: str


class DataSanitizer:
    """Neutralizes directive tokens and hidden control characters from untrusted data streams."""

    # Unicode zero-width and control characters used for covert injection
    _ZERO_WIDTH_AND_CONTROL_RE = re.compile(r"[\u200b-\u200f\ufeff\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

    # High-plane emoji and decorative symbol characters (Rule 7 Zero-Emoji Discipline)
    _EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]")

    # Patterns commonly used to hijack LLM instruction streams
    _INJECTION_DIRECTIVES = [
        (re.compile(r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior)\s+instructions\b"), "[NEUTRALIZED_DIRECTIVE: IGNORE_PREVIOUS]"),
        (re.compile(r"(?i)\bdisregard\s+(?:all\s+)?(?:previous|prior)\s+rules\b"), "[NEUTRALIZED_DIRECTIVE: DISREGARD_RULES]"),
        (re.compile(r"(?i)\byou\s+are\s+now\s+in\s+(?:dan|developer|jailbreak)\s+mode\b"), "[NEUTRALIZED_DIRECTIVE: MODE_SWITCH]"),
        (re.compile(r"(?i)<\s*(?:system|instruction|prompt)\s*>"), "[NEUTRALIZED_TAG]"),
        (re.compile(r"(?i)<\s*/\s*(?:system|instruction|prompt)\s*>"), "[/NEUTRALIZED_TAG]"),
        (re.compile(r"【(?:隐藏指令|系统指令|最高指令)】"), "[NEUTRALIZED_DIRECTIVE: HIDDEN_COMMAND]"),
        (re.compile(r"(?i)system\s+prompt\s*:"), "[NEUTRALIZED_HEADER: SYSTEM_PROMPT]"),
    ]

    @classmethod
    def sanitize_text(cls, raw_text: str) -> tuple[str, list[str]]:
        """Cleanses raw text, strips control characters, emojis, and neutralizes injection directives."""
        if not isinstance(raw_text, str):
            return str(raw_text), []

        flags: list[str] = []
        cleaned, num_ctrl = cls._ZERO_WIDTH_AND_CONTROL_RE.subn("", raw_text)
        if num_ctrl > 0:
            flags.append(f"stripped_{num_ctrl}_invisible_characters")

        cleaned, num_emoji = cls._EMOJI_RE.subn("", cleaned)
        if num_emoji > 0:
            flags.append(f"stripped_{num_emoji}_emoji_characters")

        for pattern, replacement in cls._INJECTION_DIRECTIVES:
            cleaned, count = pattern.subn(replacement, cleaned)
            if count > 0:
                flags.append(f"neutralized_{count}_directive_patterns")

        return cleaned, flags

    @classmethod
    def sanitize_source(cls, source_data: Mapping[str, Any]) -> SanitizedDataPayload:
        """Recursively sanitizes a structured data payload from an external source."""
        if not isinstance(source_data, Mapping):
            raise ContractError("source_data must be a mapping", ErrorCode.INVALID_CONTRACT)

        total_flags: list[str] = []
        cleaned_content = cls._cleanse_recursive(dict(source_data), total_flags)

        raw_bytes = json.dumps(cleaned_content, sort_keys=True, default=str).encode("utf-8")
        digest = hashlib.sha256(raw_bytes).hexdigest()

        # Purity score calculation: drops with each flag
        penalty = min(0.9, len(total_flags) * 0.15)
        purity_score = round(max(0.1, 1.0 - penalty), 2)

        return SanitizedDataPayload(
            content=cleaned_content,
            stripped_tokens_count=len(total_flags),
            flags=tuple(total_flags),
            purity_score=purity_score,
            digest=digest,
        )

    @classmethod
    def _cleanse_recursive(cls, value: Any, flags_collector: list[str]) -> Any:
        if isinstance(value, str):
            cleaned, flags = cls.sanitize_text(value)
            flags_collector.extend(flags)
            return cleaned
        if isinstance(value, Mapping):
            return {k: cls._cleanse_recursive(v, flags_collector) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._cleanse_recursive(v, flags_collector) for v in value]
        return value
