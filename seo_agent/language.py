from __future__ import annotations

import re

_ARABIC = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-z]")
_HTML_LANG = re.compile(r"<html[^>]*\blang=[\"']?([a-zA-Z]{2})", re.IGNORECASE)


def detect_language(text: str) -> str:
    """Return an ISO 639-1 code ("ar" or "en") for page text or raw HTML."""
    declared = _HTML_LANG.search(text)
    if declared:
        return declared.group(1).lower()
    arabic = len(_ARABIC.findall(text))
    latin = len(_LATIN.findall(text))
    if arabic == 0 and latin == 0:
        return "en"
    return "ar" if arabic >= latin else "en"


def is_rtl(language: str) -> bool:
    return language in {"ar", "he", "fa", "ur"}
