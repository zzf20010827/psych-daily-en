"""English-only stub — no translation calls, identity transforms."""

from __future__ import annotations

from pathlib import Path


class TranslationCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
    def save(self) -> None:
        pass
    def get(self, text: str) -> str | None:
        return None
    def set(self, text: str, translated: str) -> None:
        pass


_cache: TranslationCache | None = None


def get_cache(path: str | Path | None = None) -> TranslationCache:
    global _cache
    if _cache is None:
        _cache = TranslationCache(path or Path(__file__).resolve().parent.parent / "data" / "translation_cache.json")
    return _cache


def translate_title(title: str) -> str:
    return title


def translate_abstract(abstract: str) -> str:
    return abstract


def build_highlight(title: str, abstract: str) -> str:
    import re
    if not abstract or abstract == "Abstract unavailable":
        return f"Topic: {title}."
    sents = re.split(r"(?<=[.;])\s+(?=[A-Z(])", abstract)
    sents = [s.strip() for s in sents if len(s.strip()) > 20]
    if sents:
        h = sents[0]
        if len(h) > 160:
            h = h[:157] + "..."
        return f"Highlight: {h}"
    return f"Topic: {title}."


def flush_cache() -> None:
    pass
