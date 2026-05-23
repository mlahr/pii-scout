# Evaluating with AI4Privacy Dataset

This guide explains how to use the [ai4privacy/pii-masking-400k](https://huggingface.co/datasets/ai4privacy/pii-masking-400k) dataset to evaluate the PII detection model.

The converted JSONL and ID files are generated local artifacts and are not
included in this repository. Review the AI4Privacy dataset license before
downloading, converting, or redistributing any derived data.

## Overview

The AI4Privacy dataset contains 400k+ synthetic records with labeled PII entities across 6 languages and 8 locales. We convert this dataset to our gold standard format for evaluation.

## Requirements

```bash
pip install datasets
```

## Quick Start

```bash
# Convert 1000 English/US records from validation split
python convert_ai4privacy.py --max-records 1000

# Run evaluation
python pii_detect.py --eval ai4privacy_gold.jsonl --ids ai4privacy_ids.txt --json --pretty
```

---

## convert_ai4privacy.py

This script downloads the AI4Privacy dataset from HuggingFace and converts it to our gold standard JSONL format.

### What It Does

1. **Downloads the dataset** from HuggingFace Hub using the `datasets` library
2. **Filters records** to only English language (`language == "en"`) and the specified locale
3. **Maps entity types** from AI4Privacy labels to our system's labels (see mapping table below)
4. **Merges adjacent entities** of the same type (e.g., GIVENNAME + SURNAME become a single PERSON span)
5. **Outputs two files**:
   - A JSONL file with gold annotations
   - A text file with record IDs (one per line)

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `-o, --output` | `ai4privacy_gold.jsonl` | Path to write the gold standard JSONL file. Each line contains one record with `id`, `text`, and `entities` fields. |
| `--ids` | `ai4privacy_ids.txt` | Path to write the IDs file. Contains one record ID per line, used by `pii_detect.py --ids` to select which records to evaluate. |
| `--max-records` | `0` (all) | Limits the number of records to convert. Useful for quick tests. Set to 0 to convert all matching records. |
| `--split` | `validation` | Which dataset split to use. Options: `train` (325k records), `validation` (81k records), or `both` (combines both splits). |
| `--locale` | `US` | Filter by geographic locale. Options: `US`, `GB`, `FR`, `DE`, `IT`, `NL`, `ES`, `CH`. Different locales have different PII formats (phone numbers, addresses, etc.). |

### Entity Merging Logic

The AI4Privacy dataset labels names as separate GIVENNAME and SURNAME entities. Our system expects a single PERSON span covering the full name.

The script merges adjacent entities when:
- They map to the same target type (e.g., both become PERSON)
- They are within 2 characters of each other
- The gap between them contains only whitespace

Example:
```
Input:  "John Smith" with GIVENNAME(0,4) + SURNAME(5,10)
Output: "John Smith" with PERSON(0,10)
```

The same logic applies to address components (STREET, BUILDINGNUM, CITY, ZIPCODE) which get merged into ADDRESS spans.

### Output Format

**Gold JSONL** (`ai4privacy_gold.jsonl`):
```json
{"id": "ai4privacy_302513", "text": "Contact John Smith at john@example.com", "entities": [{"type": "PERSON", "start": 8, "end": 18}, {"type": "EMAIL", "start": 22, "end": 38}]}
```

**IDs file** (`ai4privacy_ids.txt`):
```
ai4privacy_302513
ai4privacy_302514
ai4privacy_302515
```

---

## pii_detect.py --eval

The evaluation mode compares the detector's predictions against gold standard annotations and computes precision/recall/F1 metrics.

### What It Does

1. **Loads the gold file** and filters to records matching the provided IDs
2. **Runs PII detection** on each record's text using the configured model
3. **Matches predictions to gold entities** using the specified matching strategy
4. **Computes metrics** per entity type and aggregated (micro-average)
5. **Writes error analysis files** for false negatives (and optionally false positives)

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--eval` | (required) | Path to the gold JSONL file containing annotated records. |
| `--ids` | - | Path to a file with record IDs to evaluate (one per line). Only records with matching IDs are processed. |
| `--files` | - | Alternative to `--ids`. Path to a file with document filenames. Records are matched by extracting the filename from the ID field. |
| `--models` | `accurate` | Model profile to use. `fast` uses `en_core_web_lg` (faster, less accurate). `accurate` uses `en_core_web_trf` (transformer-based, slower, more accurate). |
| `--min-score` | `0.0` | Minimum confidence score threshold. Predictions below this score are discarded before evaluation. |
| `--match` | `hybrid` | Matching strategy for comparing predictions to gold. See below. |
| `--overlap-min-chars` | `1` | For overlap matching, the minimum number of overlapping characters required for a match. |
| `--types` | all types | Comma-separated list of entity types to evaluate. Others are ignored. |
| `--json` | false | Output metrics as JSON to stdout instead of human-readable table to stderr. |
| `--pretty` | false | Pretty-print the JSON output with indentation. |
| `--report-dir` | `eval_report` | Directory to write error analysis files (false negatives/positives). |
| `--write-fp` | false | Also write false positive dumps (by default only false negatives are written). |
| `--max-errors` | `2000` | Maximum number of errors to dump per entity type. |
| `--context` | `50` | Number of characters of context to include around each error in the dump files. |

### Matching Strategies

The `--match` option controls how predictions are matched to gold entities:

| Mode | Description |
|------|-------------|
| `exact` | Prediction must have exactly the same start and end offsets as the gold entity. |
| `overlap` | Prediction must overlap with the gold entity by at least `--overlap-min-chars` characters. |
| `hybrid` | Uses `exact` for structured types (SSN, PHONE_NUMBER, ACCOUNT_NUMBER, BIRTHDATE) and `overlap` for free-text types (PERSON, LOCATION, ADDRESS). |

**Hybrid rationale**: Structured entities like SSNs have fixed formats, so we expect exact boundary matches. Names and addresses can have fuzzy boundaries (e.g., including/excluding titles like "Mr."), so overlap matching is more appropriate.

### Matching Algorithm

For each entity type, the matcher:

1. **Builds candidate pairs** of (gold, prediction) that satisfy the matching criteria
2. **Scores each pair** by overlap length (for overlap mode) or exact match (score=infinity for exact)
3. **Sorts candidates** by: score (desc), gold entity length (desc), start position (asc)
4. **Greedily assigns** matches one-to-one, ensuring each gold and prediction is matched at most once
5. **Counts**: TP = matched pairs, FN = unmatched gold, FP = unmatched predictions

### Metrics Computed

| Metric | Formula | Description |
|--------|---------|-------------|
| TP | - | True positives: correctly detected entities |
| FN | - | False negatives: gold entities not detected |
| FP | - | False positives: predictions not in gold |
| Recall | TP / (TP + FN) | Fraction of gold entities that were detected |
| Precision | TP / (TP + FP) | Fraction of predictions that were correct |
| F1 | 2 * P * R / (P + R) | Harmonic mean of precision and recall |

Metrics are computed:
- **Per type**: Separately for each entity type
- **Micro all**: Aggregated across all entity types
- **Micro P+L**: Aggregated for PERSON and LOCATION only (SpaCy NER types)

### Error Analysis Files

After evaluation, the `eval_report/` directory contains:

- `fn_PERSON.jsonl`, `fn_SSN.jsonl`, etc. - False negatives by type
- `fp_PERSON.jsonl`, etc. - False positives (if `--write-fp` enabled)

Each line is a JSON object with:
```json
{
  "id": "ai4privacy_302513",
  "type": "PERSON",
  "gold": {"type": "PERSON", "start": 8, "end": 18},
  "context": "Contact [[John Smith]] at john@example.com"
}
```

The `[[brackets]]` highlight the missed/spurious entity in context.

---

## Entity Type Mapping

The conversion script maps AI4Privacy labels to our system:

| AI4Privacy Label | Our Label | Notes |
|------------------|-----------|-------|
| GIVENNAME | PERSON | Merged with adjacent SURNAME |
| SURNAME | PERSON | Merged with adjacent GIVENNAME |
| TELEPHONENUM | PHONE_NUMBER | |
| SOCIALNUM | SSN | |
| EMAIL | EMAIL | |
| ACCOUNTNUM | ACCOUNT_NUMBER | |
| DATEOFBIRTH | BIRTHDATE | |
| STREET | ADDRESS | Merged with adjacent address components |
| BUILDINGNUM | ADDRESS | Merged with adjacent address components |
| CITY | ADDRESS | Merged with adjacent address components |
| ZIPCODE | ADDRESS | Merged with adjacent address components |

### Unmapped Entity Types

These AI4Privacy labels are ignored during conversion:

- USERNAME, PASSWORD - Not PII types we detect
- CREDITCARDNUMBER - Not currently detected
- IDCARDNUM, DRIVERLICENSENUM, TAXNUM - Not currently detected

---

## Expected Results

Results vary based on sample size and locale. Typical observations on US/English data:

| Entity Type | Expected Recall | Expected Precision | Notes |
|-------------|-----------------|-------------------|-------|
| EMAIL | 85-95% | 95-100% | Regex pattern matches well |
| PERSON | 75-85% | 60-75% | SpaCy NER performs reasonably |
| SSN | 70-80% | 40-60% | Synthetic SSNs may differ from real patterns |
| PHONE_NUMBER | 70-80% | 25-40% | International formats cause false positives |
| BIRTHDATE | 20-30% | 90-100% | Requires date + context keywords like "DOB" |
| ADDRESS | 10-20% | 90-100% | Synthetic addresses often don't match regex |
| ACCOUNT_NUMBER | 90-100% | 5-15% | Regex is intentionally broad (catches many FPs) |

### Why Results Differ from Production

1. **Synthetic vs Real Data**: The dataset is synthetically generated with patterns that may not match real-world documents.

2. **International Formats**: The dataset includes international phone numbers and addresses that don't match US-focused regex patterns.

3. **Context Differences**: Our detector boosts scores when context keywords appear (e.g., "phone:", "SSN:"). Synthetic text may lack these cues.

4. **Entity Boundaries**: The dataset separates name components (GIVENNAME/SURNAME) and address components (STREET/CITY/ZIP) differently than our combined spans. Even after merging, boundaries may not align perfectly.

5. **LOCATION false positives**: SpaCy detects geographic entities (GPE, LOC, FAC) that we map to LOCATION, but the AI4Privacy dataset doesn't label these, causing many false positives.

---

## Output Files Reference

### From convert_ai4privacy.py

| File | Description |
|------|-------------|
| `ai4privacy_gold.jsonl` | Gold standard annotations. One JSON object per line containing the original text and labeled entity spans. |
| `ai4privacy_ids.txt` | Plain text file with one record ID per line. Used to filter which records are evaluated. |

**ai4privacy_gold.jsonl structure:**
```json
{
  "id": "ai4privacy_302513",
  "text": "I, wsgqnpedll06819, consent to treatment at 7 Pines Road...",
  "entities": [
    {"type": "ADDRESS", "start": 44, "end": 56},
    {"type": "PHONE_NUMBER", "start": 125, "end": 138}
  ]
}
```

| Field | Description |
|-------|-------------|
| `id` | Unique identifier prefixed with `ai4privacy_` followed by the original dataset UID |
| `text` | The `source_text` field from AI4Privacy containing the original text with PII |
| `entities` | Array of entity annotations with `type`, `start` (inclusive), and `end` (exclusive) character offsets |

### From pii_detect.py --eval

| File | Description |
|------|-------------|
| `eval_report/fn_{TYPE}.jsonl` | False negatives for each entity type. Gold entities that the detector missed. |
| `eval_report/fp_{TYPE}.jsonl` | False positives (only if `--write-fp`). Predictions that don't match any gold entity. |

**fn_{TYPE}.jsonl structure:**
```json
{
  "id": "ai4privacy_302513",
  "type": "PERSON",
  "gold": {"type": "PERSON", "start": 8, "end": 18},
  "context": "Contact [[John Smith]] at john@example.com"
}
```

| Field | Description |
|-------|-------------|
| `id` | Record ID where the error occurred |
| `type` | Entity type that was missed |
| `gold` | The gold entity annotation that was not detected |
| `context` | Text snippet with the entity highlighted in `[[brackets]]`. Includes `--context` characters before and after. |

**fp_{TYPE}.jsonl structure:**
```json
{
  "id": "ai4privacy_302513",
  "type": "PHONE_NUMBER",
  "pred": {"type": "PHONE_NUMBER", "start": 50, "end": 62, "score": 0.85, "text": "123-456-7890"},
  "context": "Reference number [[123-456-7890]] is not a phone"
}
```

| Field | Description |
|-------|-------------|
| `id` | Record ID where the false positive occurred |
| `type` | Entity type that was incorrectly predicted |
| `pred` | The prediction including type, offsets, confidence score, and matched text |
| `context` | Text snippet with the spurious prediction highlighted in `[[brackets]]` |

### JSON Output from --json

When running with `--json`, the evaluation prints results to stdout:

```json
{
  "meta": {
    "gold": "ai4privacy_gold.jsonl",
    "split": "ai4privacy_ids.txt",
    "records": 100,
    "match": "hybrid",
    "min_score": 0.0
  },
  "by_type": {
    "PERSON": {"tp": 66, "fn": 15, "fp": 33, "recall": 0.8148, "precision": 0.6667, "f1": 0.7333},
    "EMAIL": {"tp": 27, "fn": 3, "fp": 0, "recall": 0.9, "precision": 1.0, "f1": 0.9474}
  },
  "micro": {"tp": 173, "fn": 169, "fp": 284, "recall": 0.5058, "precision": 0.3786, "f1": 0.433},
  "person_location_micro": {"tp": 66, "fn": 15, "fp": 107, "recall": 0.8148, "precision": 0.3815, "f1": 0.5197}
}
```

| Field | Description |
|-------|-------------|
| `meta.gold` | Path to the gold file used |
| `meta.split` | Path to the IDs/files filter used |
| `meta.records` | Number of records evaluated |
| `meta.match` | Matching strategy used |
| `meta.min_score` | Score threshold applied |
| `by_type` | Per-entity-type metrics |
| `micro` | Micro-averaged metrics across all types |
| `person_location_micro` | Micro-averaged metrics for PERSON + LOCATION only (SpaCy NER performance)
