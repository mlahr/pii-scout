from __future__ import annotations

import logging
import re
from typing import Dict, Any, List, Optional

from .consts import CONTEXT_WINDOW, SCORES
from .context_rules import has_context_keyword
from .text_utils import is_luhn_valid, is_ssn_format

logger = logging.getLogger(__name__)

if False:  # TYPE_CHECKING guard without runtime import
    from config.pii_config import PIIConfig  # pragma: no cover


def filter_address_ner_entities(
        entities: List[Dict[str, Any]],
        text: str,
        config: Optional["PIIConfig"] = None
) -> List[Dict[str, Any]]:
    """Filter NER-based ADDRESS entities using configurable rules."""
    if not config or not getattr(config, "post_filters", None):
        return entities
    addr_cfg = config.post_filters.address_ner
    if not addr_cfg or not addr_cfg.enabled:
        return entities

    sources = {s.lower() for s in (addr_cfg.sources or [])}
    allowed_single = {t.lower() for t in (addr_cfg.allowed_single_tokens or [])}
    suffixes = {s.lower() for s in (addr_cfg.suffixes or [])}
    require_digit = bool(addr_cfg.require_digit)
    require_suffix = bool(addr_cfg.require_suffix)
    min_single_len = int(addr_cfg.min_single_token_length or 0)
    allow_single_digit = bool(getattr(addr_cfg, "allow_single_token_digits", True))

    filtered = []
    for ent in entities:
        if ent.get('type') != 'ADDRESS':
            filtered.append(ent)
            continue

        ent_sources = {s.lower() for s in ent.get('sources', [ent.get('source', '')])}
        if sources and not (ent_sources & sources):
            filtered.append(ent)
            continue

        ent_text = ent.get('text') or text[ent['start']:ent['end']]
        ent_text = ent_text.strip()
        if not ent_text:
            continue

        lower_text = ent_text.lower()
        has_digit = any(ch.isdigit() for ch in lower_text)
        has_suffix = False
        if suffixes:
            # check suffix as whole word
            for suf in suffixes:
                if re.search(rf'\\b{re.escape(suf)}\\b', lower_text):
                    has_suffix = True
                    break

        if require_digit or require_suffix:
            if not ((require_digit and has_digit) or (require_suffix and has_suffix)):
                continue

        tokens = lower_text.split()
        if len(tokens) == 1:
            token = tokens[0]
            if token in allowed_single:
                filtered.append(ent)
                continue
            if allow_single_digit and has_digit:
                filtered.append(ent)
                continue
            if min_single_len > 0 and len(token) < min_single_len:
                continue

        filtered.append(ent)

    return filtered


def disambiguate_entity_types(
        entities: List[Dict[str, Any]],
        text: str,
        config: Optional["PIIConfig"] = None
) -> List[Dict[str, Any]]:
    """
    Disambiguate entity types based on context.

    Specifically handles:
    - 9-digit numbers: SSN vs ACCOUNT_NUMBER based on surrounding context
    - BIRTHDATE: drop if no birth context nearby

    If a 9-digit number is detected as SSN but has ACCOUNT context nearby,
    retype it to ACCOUNT_NUMBER.
    """
    # Get config values or use defaults
    context_window = config.context_window if config else CONTEXT_WINDOW
    account_score = config.scores.get('ACCOUNT_NUMBER', 0.80) if config else SCORES.get('ACCOUNT_NUMBER', 0.80)
    luhn_cfg = getattr(config, "luhn_retype", None) if config else None
    luhn_enabled = luhn_cfg.enabled if luhn_cfg else True
    luhn_min_len = luhn_cfg.min_length if luhn_cfg else 13
    luhn_max_len = luhn_cfg.max_length if luhn_cfg else 19
    luhn_require_no_account_ctx = luhn_cfg.require_no_account_context if luhn_cfg else True
    luhn_target_type = luhn_cfg.target_type if luhn_cfg else "CREDIT_CARD_NUMBER"

    # Account context keywords
    account_keywords = {
        'account', 'acct', 'a/c', 'account number', 'account no',
        'bank account', 'checking', 'savings', 'deposit'
    }

    # Use config context keywords if available
    if config and config.context_keywords:
        cfg_account_kw = config.context_keywords.get('ACCOUNT_NUMBER', [])
        if cfg_account_kw:
            account_keywords = set(cfg_account_kw) | account_keywords

    result = []
    for ent in entities:
        # Only process 9-digit SSN detections
        if ent['type'] == 'SSN':
            ent_text = ent.get('text', text[ent['start']:ent['end']])
            digit_count = len(re.sub(r'\D', '', ent_text))

            if digit_count == 9:
                # Check for account context
                start, end = ent['start'], ent['end']
                window_start = max(0, start - context_window)
                window_end = min(len(text), end + context_window)
                context = text[window_start:window_end].lower()

                has_account_context = any(kw in context for kw in account_keywords)

                if has_account_context:
                    # Retype to ACCOUNT_NUMBER
                    new_ent = ent.copy()
                    new_ent['type'] = 'ACCOUNT_NUMBER'
                    new_ent['score'] = account_score
                    logger.debug(f"Retyped 9-digit SSN → ACCOUNT_NUMBER: {ent_text}")
                    result.append(new_ent)
                    continue

        # Retype ACCOUNT_NUMBER that is SSN-shaped when SSN context exists
        if ent['type'] == 'ACCOUNT_NUMBER':
            ent_text = ent.get('text', text[ent['start']:ent['end']])
            digit_count = len(re.sub(r'\D', '', ent_text))
            if digit_count == 9 and (is_ssn_format(ent_text) or re.fullmatch(r'\d{9}', ent_text)):
                if has_context_keyword(text, ent['start'], ent['end'], 'SSN', config=config):
                    new_ent = ent.copy()
                    new_ent['type'] = 'SSN'
                    new_ent['score'] = SCORES.get('SSN', 0.95)
                    logger.debug(f"Retyped ACCOUNT_NUMBER → SSN: {ent_text}")
                    result.append(new_ent)
                    continue
            # Retype likely card numbers based on Luhn if enabled
            if luhn_enabled and is_luhn_valid(ent_text, min_len=luhn_min_len, max_len=luhn_max_len):
                if (not luhn_require_no_account_ctx) or (
                        not has_context_keyword(text, ent['start'], ent['end'], 'ACCOUNT_NUMBER', config=config)
                ):
                    new_ent = ent.copy()
                    new_ent['type'] = luhn_target_type
                    score_source = config.scores if config else SCORES
                    new_ent['score'] = score_source.get(luhn_target_type, new_ent.get('score', 0.95))
                    logger.debug(f"Retyped ACCOUNT_NUMBER → {luhn_target_type} (Luhn): {ent_text}")
                    result.append(new_ent)
                    continue

        # Drop BIRTHDATE without nearby birth context
        if ent['type'] == 'BIRTHDATE':
            if not has_context_keyword(text, ent['start'], ent['end'], 'BIRTHDATE', config=config):
                continue

        result.append(ent)

    return result
