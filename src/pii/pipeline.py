from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Set

from .merge import merge_adjacent_entities, merge_spans, trim_entity_spans
from .ner_ollama import load_ollama_model, run_ollama_detection
from .ner_openrouter import load_openrouter_model, run_openrouter_detection
from .ner_piiranha import load_piiranha_model, run_piiranha_detection
from .ner_spacy import load_spacy_model, run_spacy_detection
from .postprocess import disambiguate_entity_types, filter_address_ner_entities
from .regex_detector import run_regex_detection
from .text_utils import find_consecutive_digits, normalize_text

logger = logging.getLogger(__name__)

if False:  # TYPE_CHECKING guard without runtime import
    from config.pii_config import PIIConfig  # pragma: no cover


def _load_single_model(profile: str, args) -> tuple[Any, bool, str]:
    """Load a single NER model for the given profile name.
    Returns (model, ner_enabled, model_type).
    """
    use_gpu = getattr(args, 'use_gpu', True)

    # Normalize legacy profile names
    if profile == "fast":
        profile = "spacy-fast"
    elif profile == "accurate":
        profile = "spacy-accurate"

    model = None
    ner_enabled = False
    model_type = "spacy"

    if profile == "piiranha":
        piiranha_model_path = getattr(args, 'piiranha_model_path', None)
        pipe, tokenizer = load_piiranha_model(use_gpu=use_gpu, model_path=piiranha_model_path)
        model = (pipe, tokenizer)
        ner_enabled = True
        model_type = "piiranha"
    elif profile == "ollama":
        ollama_base_url = getattr(args, 'ollama_base_url', 'http://localhost:11434')
        ollama_model = getattr(args, 'ollama_model', 'llama3.2')
        model = load_ollama_model(ollama_base_url, ollama_model)
        ner_enabled = True
        model_type = "ollama"
    elif profile == "openrouter":
        openrouter_api_key = getattr(args, 'openrouter_api_key', '')
        openrouter_base_url = getattr(args, 'openrouter_base_url', 'https://openrouter.ai/api/v1')
        openrouter_model = getattr(args, 'openrouter_model', '')
        if not openrouter_model:
            raise RuntimeError(
                "No OpenRouter model specified. Use --openrouter-model <model_name> (e.g., openai/gpt-4o-mini)")
        model = load_openrouter_model(openrouter_api_key, openrouter_base_url, openrouter_model)
        ner_enabled = True
        model_type = "openrouter"
    elif profile == "spacy-accurate":
        model = load_spacy_model("en_core_web_trf", use_gpu=use_gpu)
        ner_enabled = True
        model_type = "spacy"
    else:  # spacy-fast (default)
        model = load_spacy_model("en_core_web_lg", use_gpu=use_gpu)
        ner_enabled = True
        model_type = "spacy"

    return model, ner_enabled, model_type


def load_models(args) -> List[tuple[Any, bool, str]]:
    """
    Load NER model(s) based on configuration.
    Returns list of (model, ner_enabled, model_type) tuples.

    Supports comma-separated profiles, e.g. "spacy-fast,piiranha".
    """
    profile_str = getattr(args, 'models', 'spacy-fast')
    profiles = [p.strip() for p in profile_str.split(",")]

    models = []
    for profile in profiles:
        try:
            models.append(_load_single_model(profile, args))
        except Exception as e:
            logger.error(f"Model load failed for '{profile}': {e}")
            raise e

    return models


def _boost_multi_model_agreement(
        ner_ents: List[Dict[str, Any]], boost: float, max_score: float
) -> List[Dict[str, Any]]:
    """Boost scores for entities found by multiple NER models.

    Two entities "agree" when they have the same type and overlapping spans
    but come from different models. Each agreed entity gets +boost (capped).
    """
    boosted = set()
    for i, a in enumerate(ner_ents):
        if i in boosted:
            continue
        for j in range(i + 1, len(ner_ents)):
            if j in boosted:
                continue
            b = ner_ents[j]
            if a['type'] != b['type']:
                continue
            if a.get('_model') == b.get('_model'):
                continue
            # Check overlap: spans intersect if a.start < b.end and b.start < a.end
            if a['start'] < b['end'] and b['start'] < a['end']:
                boosted.add(i)
                boosted.add(j)

    for idx in boosted:
        ner_ents[idx]['score'] = min(ner_ents[idx].get('score', 0) + boost, max_score)

    if boosted:
        logger.debug(f"multi-model agreement boosted {len(boosted)} entities by {boost}")

    return ner_ents


def detect_pii(
        text: str, models: List[tuple[Any, bool, str]], min_score: float,
        detectors: set = None, config: Optional["PIIConfig"] = None,
        entity_types: Optional[Set[str]] = None
) -> tuple[List[Dict[str, Any]], Dict[str, float]]:
    """
    Run full PII detection pipeline on text.
    Returns (merged_entities, timing_stats_ms).

    Args:
        text: Input text to analyze
        models: List of (model, ner_enabled, model_type) tuples
        min_score: Minimum confidence score threshold
        detectors: Set of detector types to run: {"ner", "regex", "dict"}
        config: Optional PIIConfig for customizing detection behavior
        entity_types: Optional set of entity type strings to return. None = all.
    """
    if detectors is None:
        # Use config if provided
        if config:
            detectors = set(config.detection.detector_order)
        else:
            detectors = {"ner", "regex", "dict"}
    # Normalize aliases and validate
    _ALIASES = {"dictionary": "dict"}
    detectors = {_ALIASES.get(d, d) for d in detectors}
    _VALID = {"ner", "regex", "dict"}
    unknown = detectors - _VALID
    if unknown:
        raise ValueError(f"Unknown detector(s): {unknown}. Valid: {_VALID}")
    stats = {}

    # Determine which passes to run
    if config:
        passes = config.detection.passes
    else:
        passes = ["raw", "normalized"]

    # 1. Normalization (always compute for potential use)
    t0 = time.perf_counter()
    normalized_text, offset_map = normalize_text(text)
    t1 = time.perf_counter()
    stats['normalize_ms'] = (t1 - t0) * 1000

    all_entities = []

    # helper for pipeline
    def run_pipeline(input_text, mapping=None):
        # NER
        t_ner_start = time.perf_counter()
        ner_ents = []
        if "ner" in detectors:
            for model, ner_enabled, model_type in models:
                if not ner_enabled or model is None:
                    continue
                try:
                    if model_type == "piiranha":
                        pipe, tokenizer = model
                        results = run_piiranha_detection(pipe, tokenizer, input_text, entity_types=entity_types)
                    elif model_type == "ollama":
                        results = run_ollama_detection(model, input_text, entity_types=entity_types)
                    elif model_type == "openrouter":
                        results = run_openrouter_detection(model, input_text, entity_types=entity_types)
                    else:
                        results = run_spacy_detection(model, input_text, entity_types=entity_types)
                    for r in results:
                        r['_model'] = model_type
                    ner_ents.extend(results)
                except Exception as e:
                    logger.error(f"NER detection failed ({model_type}): {e}")

        # Boost scores when multiple models agree
        if len(models) > 1 and ner_ents:
            boost = config.scoring_rules.multi_model_boost if config else 0.10
            max_score = config.scoring_rules.max_score if config else 0.99
            ner_ents = _boost_multi_model_agreement(ner_ents, boost, max_score)

        # Strip internal _model tag
        for e in ner_ents:
            e.pop('_model', None)

        # Trim whitespace from NER entity spans
        if ner_ents:
            ner_ents = trim_entity_spans(ner_ents, input_text)

        t_ner_end = time.perf_counter()
        if ner_ents:
            ner_matches = {}
            for e in ner_ents:
                ner_matches.setdefault(e['type'], []).append(e['text'])
            model_types = ",".join(mt for _, _, mt in models)
            logger.debug(f"ner layer ({model_types}): {ner_matches}")

        # Regex
        t_regex_start = time.perf_counter()
        regex_ents = []
        if "regex" in detectors:
            regex_ents = run_regex_detection(input_text, config=config, entity_types=entity_types)
        t_regex_end = time.perf_counter()
        if regex_ents:
            regex_matches = {}
            for e in regex_ents:
                regex_matches.setdefault(e['type'], []).append(e['text'])
            logger.debug(f"regex layer: {regex_matches}")

        # Dictionary-based name detection
        t_dict_start = time.perf_counter()
        dict_ents = []
        if "dict" in detectors and (not entity_types or "PERSON" in entity_types):
            try:
                from detectors.name_dict_detector import run_dict_name_detection, is_initialized
                if is_initialized():
                    dict_ents = run_dict_name_detection(input_text)
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"Dictionary detection failed: {e}")
        t_dict_end = time.perf_counter()
        if dict_ents:
            dict_matches = {}
            for e in dict_ents:
                dict_matches.setdefault(e['type'], []).append(e['text'])
            logger.debug(f"dict layer: {dict_matches}")

        # Mapping
        if mapping:
            for ent in ner_ents + regex_ents + dict_ents:
                start_norm = ent['start']
                end_norm = ent['end']

                if start_norm < len(mapping):
                    ent['start'] = mapping[start_norm]
                else:
                    ent['start'] = mapping[-1] + 1 if mapping else 0

                if end_norm > 0 and end_norm <= len(mapping):
                    ent['end'] = mapping[end_norm - 1] + 1
                else:
                    ent['end'] = len(text)

        combined = ner_ents + regex_ents + dict_ents
        combined = filter_address_ner_entities(combined, text, config=config)

        return combined, (t_ner_end - t_ner_start), (t_regex_end - t_regex_start), (
                t_dict_end - t_dict_start)

    t_ner_raw = t_regex_raw = t_dict_raw = 0
    t_ner_norm = t_regex_norm = t_dict_norm = 0

    # Run on Raw
    if "raw" in passes:
        raw_ents, t_ner_raw, t_regex_raw, t_dict_raw = run_pipeline(text)
        all_entities.extend(raw_ents)

    # Run on Normalized
    if "normalized" in passes:
        norm_ents, t_ner_norm, t_regex_norm, t_dict_norm = run_pipeline(normalized_text, mapping=offset_map)
        all_entities.extend(norm_ents)

    stats['ner_ms'] = (t_ner_raw + t_ner_norm) * 1000
    stats['regex_ms'] = (t_regex_raw + t_regex_norm) * 1000
    stats['dict_ms'] = (t_dict_raw + t_dict_norm) * 1000

    # Filter Score
    filtered = [e for e in all_entities if e['score'] >= min_score]

    # Disambiguate types (e.g., 9-digit SSN vs ACCOUNT_NUMBER based on context)
    disambiguated = disambiguate_entity_types(filtered, text, config=config)

    # Merge
    t_merge_start = time.perf_counter()
    # First merge adjacent entities of the same type (e.g., GIVENNAME+SURNAME → PERSON)
    adjacent_merged = merge_adjacent_entities(disambiguated, text, gap_threshold=2)
    # Then merge overlapping spans of the same type
    merged = merge_spans(adjacent_merged)
    t_merge_end = time.perf_counter()
    stats['merge_ms'] = (t_merge_end - t_merge_start) * 1000

    return merged, stats


def detect_pii_gateway(
        text: str,
        models: List[tuple[Any, bool, str]],
        min_score: float,
        detectors: set = None,
        config: Optional["PIIConfig"] = None,
        entity_types: Optional[Set[str]] = None
) -> tuple[List[Dict[str, Any]], Dict[str, float]]:
    """
    Gateway workflow:
    1. Run all regex detection
    2. Run gateway tests from config.gateway.tests
    3. If any test matches → run full detection (NER + regex)
    4. If no match → return regex-only results (skip NER)

    Stats includes:
    - gateway_skipped: True if model was not called
    - gateway_trigger: 'digits' or 'name' (what triggered the model call)
    - gateway_match: the text that matched (first digit sequence or first name)

    Args:
        models: List of (model, ner_enabled, model_type) tuples
        config: Optional PIIConfig for customizing gateway behavior
    """
    stats = {'gateway_skipped': False, 'gateway_trigger': None, 'gateway_match': None}

    # Get gateway tests config
    tests = config.gateway.tests if config else None

    # Step 1: Run all regex detection
    regex_entities = run_regex_detection(text, config=config, entity_types=entity_types)

    # Step 2: Gateway check - should we call the model?
    should_call_model = False

    if tests:
        # Use configured tests
        for test in tests:
            if not test.enabled:
                continue

            if test.name == "consecutive_digits":
                threshold = test.threshold if test.threshold is not None else 5
                digit_matches = find_consecutive_digits(text, min_length=threshold)
                if digit_matches:
                    should_call_model = True
                    stats['gateway_trigger'] = 'digits'
                    stats['gateway_match'] = digit_matches[0]
                    logger.debug(f"gateway trigger: digits -> {digit_matches}")
                    break

            elif test.name == "name_dictionary":
                try:
                    from detectors.name_dict_detector import run_dict_name_detection, is_initialized
                    if is_initialized():
                        name_entities = run_dict_name_detection(text)
                        if name_entities:
                            should_call_model = True
                            stats['gateway_trigger'] = 'name'
                            stats['gateway_match'] = name_entities[0].get('text', '')
                            logger.debug(f"gateway trigger: name -> {[e['text'] for e in name_entities]}")
                            break
                except ImportError:
                    pass

            elif test.name == "address_signals":
                try:
                    from detectors.address_signals import get_detector
                    detector = get_detector(config)
                    trigger, match_desc = detector.should_trigger(text)
                    if trigger:
                        should_call_model = True
                        stats['gateway_trigger'] = 'address'
                        stats['gateway_match'] = match_desc
                        logger.debug(f"gateway trigger: address -> {match_desc}")
                        break
                except ImportError:
                    logger.debug("gateway: address_signals module not available")
    else:
        # Default behavior (backward compat)
        digit_matches = find_consecutive_digits(text, min_length=5)
        if digit_matches:
            should_call_model = True
            stats['gateway_trigger'] = 'digits'
            stats['gateway_match'] = digit_matches[0]
            logger.debug("Gateway: found consecutive digits, will call model")

        if not should_call_model:
            try:
                from detectors.name_dict_detector import run_dict_name_detection, is_initialized
                if is_initialized():
                    name_entities = run_dict_name_detection(text)
                    if name_entities:
                        should_call_model = True
                        stats['gateway_trigger'] = 'name'
                        stats['gateway_match'] = name_entities[0].get('text', '')
                        logger.debug("Gateway: found dictionary name match, will call model")
            except ImportError:
                pass

    # Step 3: Run full detection or return regex-only results
    if should_call_model:
        entities, detect_stats = detect_pii(text, models, min_score, detectors, config=config, entity_types=entity_types)
        detect_stats.update(stats)
        return entities, detect_stats
    else:
        # Gateway skip: skip NER only, still return all regex results
        stats['gateway_skipped'] = True
        logger.debug("gateway: no trigger, skipping NER")
        filtered = [e for e in regex_entities if e['score'] >= min_score]
        # Still run type disambiguation for consistency
        disambiguated = disambiguate_entity_types(filtered, text, config=config)
        return disambiguated, stats
