from __future__ import annotations

from typing import Optional

from .consts import CONTEXT_WINDOW, KEYWORDS, NEGATIVE_CONTEXT, ZIP_CONTEXT_KEYWORDS

if False:  # TYPE_CHECKING guard without runtime import
    from config.pii_config import PIIConfig  # pragma: no cover


def has_context_keyword(
        text: str, start: int, end: int, entity_type: str,
        config: Optional["PIIConfig"] = None
) -> bool:
    """Check if keywords for the entity type appear within +/- context_window chars."""
    # Use config if provided, else fall back to module constants
    if config:
        context_window = config.context_window
        keywords_dict = config.context_keywords
    else:
        context_window = CONTEXT_WINDOW
        keywords_dict = KEYWORDS

    window_start = max(0, start - context_window)
    window_end = min(len(text), end + context_window)

    # We look at the context ONLY, excluding the entity itself roughly,
    # but practically checking the whole window is fine as long as keywords aren't the entity itself usually.
    # To be safe, let's checking the snippet before and after.
    pre_text = text[window_start:start].lower()
    post_text = text[end:window_end].lower()

    context_text = pre_text + " " + post_text

    keywords = keywords_dict.get(entity_type, [])
    # Convert to set if it's a list
    if isinstance(keywords, list):
        keywords = set(keywords)
    for kw in keywords:
        if kw in context_text:
            return True
    return False


def has_negative_context(text: str, start: int, end: int, entity_type: str) -> bool:
    """
    Check if negative context keywords appear immediately before match.
    Uses a smaller window (25 chars) and only checks pre-text to avoid
    false positives from unrelated nearby text.
    """
    negative_keywords = NEGATIVE_CONTEXT.get(entity_type, set())
    if not negative_keywords:
        return False

    # Use smaller window and only check immediately before the match
    small_window = 25
    window_start = max(0, start - small_window)
    pre_text = text[window_start:start].lower()

    for kw in negative_keywords:
        if kw in pre_text:
            return True
    return False


def has_immediate_birthdate_context(text: str, start: int, end: int) -> bool:
    """
    Check if birthdate context keywords appear immediately before match.
    Uses a smaller window to avoid picking up context from other dates.
    """
    birthdate_keywords = {'dob', 'date of birth', 'born', 'birthdate', 'birth'}

    # Check immediately before (20 chars)
    small_window = 20
    window_start = max(0, start - small_window)
    pre_text = text[window_start:start].lower()

    for kw in birthdate_keywords:
        if kw in pre_text:
            return True
    return False


def has_zip_context(text: str, start: int, end: int, context_window: int = CONTEXT_WINDOW) -> bool:
    """Check if zip/postal context keywords appear within +/- context_window chars."""
    window_start = max(0, start - context_window)
    window_end = min(len(text), end + context_window)
    context = (text[window_start:start] + " " + text[end:window_end]).lower()
    return any(kw in context for kw in ZIP_CONTEXT_KEYWORDS)

