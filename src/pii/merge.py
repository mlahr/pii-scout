from __future__ import annotations

from typing import Dict, Any, List


def _ensure_sources(ent: Dict[str, Any]) -> None:
    """Convert legacy 'source' string to 'sources' list in-place, if needed."""
    if 'sources' not in ent:
        ent['sources'] = [ent.pop('source', 'unknown')]


def _get_sources(ent: Dict[str, Any]) -> List[str]:
    """Read sources from an entity that may have 'sources' or 'source'."""
    if 'sources' in ent:
        return ent['sources']
    return [ent.get('source', 'unknown')]


def merge_spans(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge overlapping spans of the same type.

    Previous behavior only removed exact (start, end, type) duplicates.
    New behavior merges overlapping spans of the same type into one span,
    keeping the highest score and preferring 'ner' source.
    """
    if not entities:
        return []

    # Sort by (type, start, end)
    entities.sort(key=lambda x: (x['type'], x['start'], x['end']))

    merged = []
    current = None

    for e in entities:
        if current is None:
            current = e.copy()
            _ensure_sources(current)
            continue

        same_type = current['type'] == e['type']
        overlaps = e['start'] < current['end']

        if same_type and overlaps:
            # Merge: extend end, keep highest score, collect sources
            current['end'] = max(current['end'], e['end'])
            current['score'] = max(current.get('score', 0), e.get('score', 0))
            for s in _get_sources(e):
                if s not in current['sources']:
                    current['sources'].append(s)
        else:
            merged.append(current)
            current = e.copy()
            _ensure_sources(current)

    if current:
        merged.append(current)

    # Re-sort by start position for consistent output
    merged.sort(key=lambda x: (x['start'], x['end']))
    return merged


def merge_adjacent_entities(entities: List[Dict[str, Any]], text: str, gap_threshold: int = 2) -> List[Dict[str, Any]]:
    """
    Merge adjacent entities of the same type (e.g., GIVENNAME+SURNAME → PERSON).

    Args:
        entities: List of entity dicts with start, end, type, score, source
        text: Original text (used to check if gap contains only whitespace)
        gap_threshold: Max characters between entities to consider them adjacent

    Returns:
        List of merged entities
    """
    if not entities:
        return []

    # Sort by start position
    sorted_ents = sorted(entities, key=lambda x: x['start'])

    merged = []
    current = None

    for ent in sorted_ents:
        if current is None:
            current = ent.copy()
            _ensure_sources(current)
            continue

        # Check if same type and adjacent
        same_type = current['type'] == ent['type']
        gap = ent['start'] - current['end']

        # Check if gap contains only whitespace
        gap_text = text[current['end']:ent['start']] if gap > 0 else ""
        is_whitespace_gap = gap_text.strip() == ""

        if same_type and gap <= gap_threshold and is_whitespace_gap:
            # Merge: extend current entity, collect sources
            current['end'] = ent['end']
            current['score'] = max(current.get('score', 0), ent.get('score', 0))
            for s in _get_sources(ent):
                if s not in current['sources']:
                    current['sources'].append(s)
        else:
            merged.append(current)
            current = ent.copy()
            _ensure_sources(current)

    if current:
        merged.append(current)

    return merged


def trim_entity_spans(entities: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    """
    Trim leading/trailing whitespace from entity spans and adjust offsets.

    NER models (especially Piiranha) sometimes include leading/trailing whitespace
    in their detected spans. This function corrects the offsets to match the
    actual entity text boundaries.
    """
    trimmed = []
    for ent in entities:
        start = ent['start']
        end = ent['end']

        # Safety check
        if start < 0 or end > len(text) or start >= end:
            trimmed.append(ent)
            continue

        entity_text = text[start:end]

        # Count leading whitespace
        leading = len(entity_text) - len(entity_text.lstrip())
        # Count trailing whitespace
        trailing = len(entity_text) - len(entity_text.rstrip())

        if leading > 0 or trailing > 0:
            new_start = start + leading
            new_end = end - trailing if trailing > 0 else end

            # Ensure we still have valid span
            if new_start < new_end:
                new_ent = ent.copy()
                new_ent['start'] = new_start
                new_ent['end'] = new_end
                new_ent['text'] = text[new_start:new_end]
                trimmed.append(new_ent)
            else:
                # Degenerate case - keep original
                trimmed.append(ent)
        else:
            trimmed.append(ent)

    # Trim leading/trailing punctuation for numeric identifiers
    punct_trim = {'ACCOUNT_NUMBER', 'SSN', 'PHONE_NUMBER'}
    cleaned = []
    for ent in trimmed:
        if ent.get('type') not in punct_trim:
            cleaned.append(ent)
            continue

        start = ent['start']
        end = ent['end']
        if start < 0 or end > len(text) or start >= end:
            cleaned.append(ent)
            continue

        ent_text = text[start:end]
        new_start = start
        new_end = end

        while new_start < new_end and ent_text[0] in ['#', '(', '[']:
            new_start += 1
            ent_text = text[new_start:new_end]

        while new_end > new_start and ent_text[-1] in ['.', ',', ')', ']', ':']:
            new_end -= 1
            ent_text = text[new_start:new_end]

        if new_start < new_end:
            new_ent = ent.copy()
            new_ent['start'] = new_start
            new_ent['end'] = new_end
            new_ent['text'] = text[new_start:new_end]
            cleaned.append(new_ent)
        else:
            cleaned.append(ent)

    return cleaned
