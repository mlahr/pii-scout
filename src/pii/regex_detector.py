from __future__ import annotations

import re
from typing import Dict, Any, List, Optional, Set

from .consts import PATTERNS, SCORES
from .context_rules import (
    has_context_keyword,
    has_immediate_birthdate_context,
    has_negative_context,
    has_zip_context,
)
from .text_utils import is_postal_4, is_ssn_format, is_zip_like

if False:  # TYPE_CHECKING guard without runtime import
    from config.pii_config import PIIConfig  # pragma: no cover


def run_regex_detection(
        text: str,
        config: Optional["PIIConfig"] = None,
        entity_types: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    entities = []

    # Use config if provided, else fall back to module constants
    if config:
        patterns = config.patterns
        scores = config.scores
        scoring_rules = config.scoring_rules
    else:
        patterns = PATTERNS
        scores = SCORES
        scoring_rules = None

    for label, pattern_list in patterns.items():
        if entity_types:
            # DATE patterns can produce BIRTHDATE, so keep DATE if BIRTHDATE requested
            if label not in entity_types and not (label == 'DATE' and 'BIRTHDATE' in entity_types):
                continue
        base_score = scores.get(label, 0.5)

        for pat in pattern_list:
            for match in re.finditer(pat, text):
                match_text = match.group()
                start, end = match.span()

                # Special handling logic
                score = base_score
                is_valid = True

                has_ctx = has_context_keyword(text, start, end, label, config=config)

                # Get scoring rules
                if scoring_rules:
                    context_boost = scoring_rules.context_boost
                    max_score = scoring_rules.max_score
                    account_no_ctx_score = scoring_rules.account_no_context_score
                    account_min_digits = scoring_rules.account_min_digits
                else:
                    context_boost = 0.10
                    max_score = 0.99
                    account_no_ctx_score = 0.40  # Lowered from 0.60
                    account_min_digits = 10  # Raised from 8

                if label == 'ACCOUNT_NUMBER':
                    # Skip if negative context present (credit card, passport, phone, etc.)
                    if has_negative_context(text, start, end, label):
                        is_valid = False
                    # Skip if SSN-shaped
                    if is_valid:
                        if is_ssn_format(match_text) or re.fullmatch(r'\d{9}', match_text):
                            is_valid = False
                    # Lower score if no positive context, and require minimum digits
                    if is_valid and not has_ctx:
                        score = account_no_ctx_score
                        if len(re.sub(r'\D', '', match_text)) < account_min_digits:
                            is_valid = False

                # PHONE_NUMBER: skip if negative context present immediately before (ID:, passport:, etc.)
                # Negative context takes precedence because it's checked in a smaller window
                if label == 'PHONE_NUMBER':
                    if has_negative_context(text, start, end, label):
                        is_valid = False
                    # Skip if match is adjacent to more digits (part of longer number)
                    if is_valid:
                        before_char = text[start - 1] if start > 0 else ''
                        after_char = text[end] if end < len(text) else ''
                        if before_char.isdigit() or after_char.isdigit():
                            is_valid = False

                # SSN: skip if negative context present (passport, driver license, etc.)
                if label == 'SSN':
                    if has_negative_context(text, start, end, label):
                        is_valid = False
                    if is_valid:
                        digit_count = len(re.sub(r'\D', '', match_text))
                        if digit_count == 9 and re.fullmatch(r'\d{9}', match_text):
                            # Require SSN context for plain 9-digit matches
                            if not has_ctx:
                                is_valid = False

                # ADDRESS: validate standalone postal codes with zip context
                if label == 'ADDRESS':
                    if is_zip_like(match_text) or is_postal_4(match_text):
                        if not has_zip_context(text, start, end):
                            is_valid = False

                # Context boost
                if has_ctx:
                    score = min(max_score, score + context_boost)

                # Handle DATE: only emit if it's actually a BIRTHDATE (has immediate birth context)
                # Suppress standalone DATE detections to avoid type confusion
                final_label = label
                if label == 'DATE':
                    if has_immediate_birthdate_context(text, start, end):
                        final_label = 'BIRTHDATE'
                        score = min(max_score, score + context_boost)
                    else:
                        # Skip DATE without birthdate context
                        is_valid = False

                if is_valid:
                    entities.append({
                        "type": final_label,
                        "text": match_text,
                        "start": start,
                        "end": end,
                        "score": round(score, 2),
                        "source": "regex"
                    })

    return entities
