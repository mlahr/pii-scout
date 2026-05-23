from __future__ import annotations

import logging
import os
from typing import Dict, Any, List, Optional, Set

from .consts import (
    PIIRANHA_CHUNK_SIZE,
    PIIRANHA_LABEL_MAP,
    PIIRANHA_MAX_TOKENS,
    PIIRANHA_MODEL_NAME,
    PIIRANHA_OVERLAP,
)

logger = logging.getLogger(__name__)

# Environment variable for model path override
ENV_PIIRANHA_MODEL_PATH = "PIIRANHA_MODEL_PATH"


def _get_torch_device(use_gpu: bool):
    """Determine the best available device: CUDA > MPS > CPU."""
    import torch

    if not use_gpu:
        return "cpu", "CPU (GPU disabled)"

    if torch.cuda.is_available():
        return 0, "CUDA"  # Device index 0 for transformers pipeline

    if torch.backends.mps.is_available():
        return "mps", "MPS (Apple Silicon)"

    logger.warning("No GPU available (CUDA/MPS not found), falling back to CPU")
    return "cpu", "CPU"


def load_piiranha_model(use_gpu: bool = True, model_path: str = None):
    """
    Load the Piiranha PII detection model.

    Args:
        use_gpu: Whether to use GPU acceleration
        model_path: Path to model (HuggingFace ID or local directory).
                    If None, uses PIIRANHA_MODEL_PATH env var or default.
    """
    from transformers import pipeline, AutoTokenizer

    # Priority: explicit arg > env var > default constant
    if model_path is None:
        model_path = os.environ.get(ENV_PIIRANHA_MODEL_PATH, PIIRANHA_MODEL_NAME)

    # Expand ~ in path if present
    if model_path.startswith("~"):
        model_path = os.path.expanduser(model_path)

    device, device_name = _get_torch_device(use_gpu)
    logger.info(f"Loading Piiranha model from {model_path} on {device_name}...")

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    # Fix missing max_length in tokenizer config (model supports 512)
    tokenizer.model_max_length = PIIRANHA_MAX_TOKENS

    pipe = pipeline(
        "token-classification",
        model=model_path,
        tokenizer=tokenizer,
        device=device,
        aggregation_strategy="simple"
    )

    # Warmup
    _ = pipe("warmup text")
    logger.info("Piiranha model loaded successfully.")

    return pipe, tokenizer


def run_piiranha_detection(pipe, tokenizer, text: str, entity_types: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """
    Run Piiranha model on text, handling chunking for long text.
    Returns list of entity dicts with start, end, type, text, score.
    """
    import warnings
    entities = []

    # Check if text needs chunking (suppress length warning - we handle chunking ourselves)
    #with warnings.catch_warnings():
    #    warnings.filterwarnings("ignore", message="Token indices sequence length")
    tokens = tokenizer.encode(text, add_special_tokens=False)

    if len(tokens) <= PIIRANHA_MAX_TOKENS:
        # Short text - process directly
        results = pipe(text)
        for r in results:
            label = r.get('entity_group', r.get('entity', ''))
            mapped_label = PIIRANHA_LABEL_MAP.get(label)
            if mapped_label:
                if entity_types and mapped_label not in entity_types:
                    continue
                entities.append({
                    "type": mapped_label,
                    "text": r['word'],
                    "start": r['start'],
                    "end": r['end'],
                    "score": round(float(r['score']), 2),
                    "source": "ner"
                })
    else:
        # Long text - chunk and process
        entities = _process_piiranha_chunked(pipe, tokenizer, text, tokens, entity_types=entity_types)

    return entities


def _process_piiranha_chunked(pipe, tokenizer, text: str, tokens: List[int], entity_types: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """Process long text in chunks with overlap to handle entities spanning chunk boundaries."""
    entities = []
    seen_spans = set()

    # Calculate chunk boundaries in token space
    chunk_starts = list(range(0, len(tokens), PIIRANHA_CHUNK_SIZE - PIIRANHA_OVERLAP))

    for chunk_idx, token_start in enumerate(chunk_starts):
        token_end = min(token_start + PIIRANHA_CHUNK_SIZE, len(tokens))
        chunk_tokens = tokens[token_start:token_end]

        # Decode chunk back to text
        chunk_text = tokenizer.decode(chunk_tokens, skip_special_tokens=True)

        # Find character offset for this chunk in original text
        if token_start == 0:
            char_offset = 0
        else:
            # Decode tokens up to this point to find character offset
            prefix_text = tokenizer.decode(tokens[:token_start], skip_special_tokens=True)
            char_offset = len(prefix_text)
            # Adjust for any whitespace differences
            while char_offset < len(text) and text[char_offset:char_offset + 1].isspace():
                char_offset += 1

        # Run inference on chunk
        try:
            results = pipe(chunk_text)
        except Exception as e:
            logger.debug(f"Piiranha chunk {chunk_idx} failed: {e}")
            continue

        for r in results:
            label = r.get('entity_group', r.get('entity', ''))
            mapped_label = PIIRANHA_LABEL_MAP.get(label)
            if not mapped_label:
                continue
            if entity_types and mapped_label not in entity_types:
                continue

            # Adjust offsets to original text
            orig_start = char_offset + r['start']
            orig_end = char_offset + r['end']

            # Deduplicate based on position
            span_key = (orig_start, orig_end, mapped_label)
            if span_key in seen_spans:
                continue
            seen_spans.add(span_key)

            # Get original text at those positions
            orig_text = text[orig_start:orig_end] if orig_start < len(text) and orig_end <= len(text) else r['word']

            entities.append({
                "type": mapped_label,
                "text": orig_text,
                "start": orig_start,
                "end": orig_end,
                "score": round(float(r['score']), 2),
                "source": "ner"
            })

    return entities
