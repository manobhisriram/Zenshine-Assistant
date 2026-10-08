"""Input hygiene and prompt-injection heuristics.

Heuristics are one layer only: the real controls are the system prompt, the deterministic tools
(the model cannot change prices), strict output handling, and the absence of any privileged tool.
"""

from __future__ import annotations

import re
import unicodedata

from app.core import metrics

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁠﻿]")
_INJECTION = [
    re.compile(p, re.I)
    for p in (
        r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|prompts?|rules)",
        r"disregard (all |any |the )?(previous|prior|above|system)",
        r"(reveal|show|print|repeat|output) (me )?(your|the) (system|hidden|initial) (prompt|instructions?)",
        r"you are now (in )?(dan|developer mode|jailbroken)",
        r"act as (if you (have|had) no|an? unrestricted)",
        r"</?(system|assistant|tool_use|instructions?)>",
        r"\bBEGIN (SYSTEM|NEW) (PROMPT|INSTRUCTIONS)\b",
    )
]


def sanitize(text: str, max_chars: int) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _CTRL.sub("", text)
    text = re.sub(r"[ \t]{3,}", "  ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_chars]


def looks_like_injection(text: str) -> bool:
    flagged = any(p.search(text) for p in _INJECTION)
    if flagged:
        metrics.INJECTION_FLAGS.inc()
    return flagged


def neutralize_context(text: str) -> str:
    """Retrieved passages are data. Strip tag-like markup so a poisoned document can't open a fake instruction block."""
    return re.sub(r"</?\s*(system|assistant|user|instructions?|tool_use|tool_result)[^>]*>", "", text, flags=re.I)
