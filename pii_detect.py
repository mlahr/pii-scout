#!/usr/bin/env python3

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent
src_root = repo_root / "src"
if src_root.exists():
    sys.path.insert(0, str(src_root))

from pii.cli import main
from pii.consts import (
    CONTEXT_WINDOW,
    KEYWORDS,
    NEGATIVE_CONTEXT,
    PATTERNS,
    SCORES,
)
from pii.text_utils import (
    find_consecutive_digits,
    has_consecutive_digits,
    is_luhn_valid,
    is_postal_4,
    is_ssn_format,
    is_zip_like,
    normalize_text,
)
from pii.context_rules import (
    has_context_keyword,
    has_immediate_birthdate_context,
    has_negative_context,
    has_zip_context,
)
from pii.regex_detector import run_regex_detection
from pii.merge import merge_adjacent_entities, merge_spans, trim_entity_spans
from pii.postprocess import disambiguate_entity_types, filter_address_ner_entities
from pii.ner_spacy import load_spacy_model, run_spacy_detection
from pii.ner_piiranha import load_piiranha_model, run_piiranha_detection
from pii.ner_ollama import load_ollama_model, run_ollama_detection
from pii.ner_openrouter import load_openrouter_model, run_openrouter_detection
from pii.pipeline import detect_pii, detect_pii_gateway, load_models
from pii.bench import calculate_quantiles, run_bench
from pii.eval import (
    apply_gold_corrections,
    load_gold_corrections,
    match_entities,
    run_eval,
)

__all__ = [
    "CONTEXT_WINDOW",
    "KEYWORDS",
    "NEGATIVE_CONTEXT",
    "PATTERNS",
    "SCORES",
    "normalize_text",
    "is_zip_like",
    "is_postal_4",
    "is_ssn_format",
    "has_consecutive_digits",
    "find_consecutive_digits",
    "is_luhn_valid",
    "has_context_keyword",
    "has_immediate_birthdate_context",
    "has_negative_context",
    "has_zip_context",
    "run_regex_detection",
    "merge_spans",
    "merge_adjacent_entities",
    "trim_entity_spans",
    "disambiguate_entity_types",
    "filter_address_ner_entities",
    "load_spacy_model",
    "run_spacy_detection",
    "load_piiranha_model",
    "run_piiranha_detection",
    "load_ollama_model",
    "run_ollama_detection",
    "load_openrouter_model",
    "run_openrouter_detection",
    "load_models",
    "detect_pii",
    "detect_pii_gateway",
    "calculate_quantiles",
    "run_bench",
    "load_gold_corrections",
    "apply_gold_corrections",
    "match_entities",
    "run_eval",
    "main",
]


if __name__ == "__main__":
    main()
