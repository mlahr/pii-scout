#!/usr/bin/env python3
"""
Convert ai4privacy/pii-masking-400k dataset to gold JSONL format
for evaluation with pii_detect.py --eval
"""

import argparse
import json
import logging
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Entity type mapping from ai4privacy to our system
TYPE_MAP = {
    "GIVENNAME": "PERSON",
    "SURNAME": "PERSON",
    "TELEPHONENUM": "PHONE_NUMBER",
    "SOCIALNUM": "SSN",
    "EMAIL": "EMAIL",
    "ACCOUNTNUM": "ACCOUNT_NUMBER",
    "DATEOFBIRTH": "BIRTHDATE",
    "STREET": "ADDRESS",
    "BUILDINGNUM": "ADDRESS",
    "CITY": "ADDRESS",
    "ZIPCODE": "ADDRESS",
}

# Entity types that should be merged when adjacent
MERGE_GROUPS = {
    "PERSON": {"GIVENNAME", "SURNAME"},
    "ADDRESS": {"STREET", "BUILDINGNUM", "CITY", "ZIPCODE"},
}


def merge_adjacent_entities(entities: List[Dict], text: str, gap_threshold: int = 2) -> List[Dict]:
    """
    Merge adjacent entities of the same mapped type.
    gap_threshold: max characters between entities to consider them adjacent
    """
    if not entities:
        return []

    # Sort by start position
    sorted_ents = sorted(entities, key=lambda x: x["start"])

    merged = []
    current = None

    for ent in sorted_ents:
        if current is None:
            current = ent.copy()
            continue

        # Check if same type and adjacent
        same_type = current["type"] == ent["type"]
        gap = ent["start"] - current["end"]

        # Check if gap contains only whitespace
        gap_text = text[current["end"]:ent["start"]] if gap > 0 else ""
        is_whitespace_gap = gap_text.strip() == ""

        if same_type and gap <= gap_threshold and is_whitespace_gap:
            # Merge: extend current entity
            current["end"] = ent["end"]
        else:
            merged.append(current)
            current = ent.copy()

    if current:
        merged.append(current)

    return merged


def convert_record(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a single ai4privacy record to gold format."""
    text = row["source_text"]
    privacy_mask = row["privacy_mask"]
    uid = row["uid"]

    entities = []

    for mask in privacy_mask:
        original_label = mask["label"]
        mapped_type = TYPE_MAP.get(original_label)

        if mapped_type:
            entities.append({
                "type": mapped_type,
                "start": mask["start"],
                "end": mask["end"],
                "original_label": original_label,  # Keep for debugging
            })

    # Merge adjacent PERSON and ADDRESS entities
    merged_entities = merge_adjacent_entities(entities, text)

    # Strip debug info for final output
    final_entities = [
        {"type": e["type"], "start": e["start"], "end": e["end"]}
        for e in merged_entities
    ]

    return {
        "id": f"ai4privacy_{uid}",
        "text": text,
        "entities": final_entities
    }


def main():
    parser = argparse.ArgumentParser(description="Convert ai4privacy dataset to gold JSONL")
    parser.add_argument("--output", "-o", default="ai4privacy_gold.jsonl", help="Output JSONL file")
    parser.add_argument("--ids", default="ai4privacy_ids.txt", help="Output IDs file")
    parser.add_argument("--max-records", type=int, default=0, help="Max records to convert (0=all)")
    parser.add_argument("--split", choices=["train", "validation", "both"], default="validation",
                        help="Dataset split to use")
    parser.add_argument("--locale", default="US", help="Filter by locale (default: US)")
    args = parser.parse_args()

    try:
        from datasets import load_dataset
    except ImportError:
        logger.error("datasets library not installed. Run: pip install datasets")
        return 1

    logger.info("Loading ai4privacy/pii-masking-400k dataset...")

    if args.split == "both":
        dataset = load_dataset("ai4privacy/pii-masking-400k")
        # Combine train and validation
        from datasets import concatenate_datasets
        data = concatenate_datasets([dataset["train"], dataset["validation"]])
    else:
        data = load_dataset("ai4privacy/pii-masking-400k", split=args.split)

    logger.info(f"Loaded {len(data)} records from {args.split} split")

    # Filter to English and specified locale
    logger.info(f"Filtering to language='en' and locale='{args.locale}'...")
    filtered = data.filter(lambda x: x["language"] == "en" and x["locale"] == args.locale)
    logger.info(f"Filtered to {len(filtered)} English/{args.locale} records")

    if args.max_records > 0:
        filtered = filtered.select(range(min(args.max_records, len(filtered))))
        logger.info(f"Limited to {len(filtered)} records")

    # Convert and write
    logger.info(f"Converting to gold format...")

    ids = []
    entity_counts = {}

    with open(args.output, "w") as f_out:
        for row in filtered:
            record = convert_record(row)
            ids.append(record["id"])

            # Count entities by type
            for ent in record["entities"]:
                entity_counts[ent["type"]] = entity_counts.get(ent["type"], 0) + 1

            f_out.write(json.dumps(record) + "\n")

    # Write IDs file
    with open(args.ids, "w") as f_ids:
        for rid in ids:
            f_ids.write(rid + "\n")

    logger.info(f"Wrote {len(ids)} records to {args.output}")
    logger.info(f"Wrote {len(ids)} IDs to {args.ids}")
    logger.info(f"Entity counts: {json.dumps(entity_counts, indent=2)}")

    return 0


if __name__ == "__main__":
    exit(main())
