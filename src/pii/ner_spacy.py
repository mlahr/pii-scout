from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional, Set

from .consts import SCORES

logger = logging.getLogger(__name__)


def run_spacy_detection(nlp, text: str, entity_types: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    import spacy
    spacy.prefer_gpu()  # Re-activate GPU context before inference
    doc = nlp(text)
    entities = []
    for ent in doc.ents:
        label = ent.label_

        if label == 'PERSON':
            final_label = 'PERSON'
            score = SCORES['PERSON']
        elif label in ['GPE', 'LOC', 'FAC']:
            final_label = 'LOCATION'
            score = SCORES['LOCATION']
        else:
            continue

        if entity_types and final_label not in entity_types:
            continue

        entities.append({
            "type": final_label,
            "text": ent.text,
            "start": ent.start_char,
            "end": ent.end_char,
            "score": score,
            "source": "ner"
        })
    return entities


def load_spacy_model(model_name: str, use_gpu: bool = True):
    import spacy
    try:
        if use_gpu and spacy.prefer_gpu():
            logger.info("Using GPU for SpaCy.")
        else:
            if use_gpu:
                logger.warning("No GPU available for SpaCy, falling back to CPU")
            spacy.require_cpu()
            logger.info("Using CPU for SpaCy.")
        nlp = spacy.load(model_name)
        _ = nlp("warmup")  # Warmup inference
        return nlp
    except OSError:
        logger.info(f"Model '{model_name}' not found. Downloading...")
        from spacy.cli import download
        download(model_name)
        return spacy.load(model_name)
