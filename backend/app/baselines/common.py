from __future__ import annotations

import re
import unicodedata
from typing import Any

MOJIBAKE_MARKERS = ("Ã", "Ä", "Å", "â", "Ë", "Ê", "Æ", "œ", "Ð", "Ñ", "¤", "�")


def repair_text(value: str) -> str:
    if not value:
        return ""
    if any(marker in value for marker in MOJIBAKE_MARKERS):
        for encoding in ("latin1", "cp1252"):
            try:
                return value.encode(encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
    return value


def truncate_text(value: str, *, limit: int = 280) -> str:
    cleaned = repair_text(value).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def normalize_for_match(value: str) -> str:
    cleaned = repair_text(value)
    normalized = unicodedata.normalize("NFKD", cleaned)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.casefold()
    lowered = re.sub(r"[^a-z0-9\s]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def extract_chat_text(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts).strip()
    return str(content).strip()


def heuristic_match(prediction: str, gold_answer: str) -> dict[str, object]:
    normalized_prediction = normalize_for_match(prediction)
    normalized_gold = normalize_for_match(gold_answer)
    exact_match = normalized_prediction == normalized_gold and bool(normalized_gold)
    contains_match = bool(normalized_gold) and (
        normalized_gold in normalized_prediction or normalized_prediction in normalized_gold
    )
    return {
        "prediction_normalized": normalized_prediction,
        "gold_normalized": normalized_gold,
        "exact_match": exact_match,
        "contains_match": contains_match,
    }
