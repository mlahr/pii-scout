# Evaluation

Evaluation uses gold-standard JSONL annotations, optional split files, and
`pii_detect.py --eval`.

## Entity Types

| Type | Detection Method | Base Score | Notes |
| --- | --- | --- | --- |
| PERSON | SpaCy NER | 0.80 | From PERSON entities |
| LOCATION | SpaCy NER | 0.75 | From GPE, FAC, LOC entities |
| ADDRESS | Regex + context | 0.70 | Boosted by address keywords |
| SSN | Regex | 0.95 | Common US SSN formats |
| PHONE_NUMBER | Regex | 0.85 | Multiple formats supported |
| ACCOUNT_NUMBER | Regex + context | 0.80 | 10-17 digits or IBAN-like values |
| BIRTHDATE | Regex | 0.75 | Date with birth context |
| DATE | Labels/eval | 0.75 | General dates are supported in labels/eval |
| EMAIL | Regex | 0.90 | Email addresses |
| CREDIT_CARD_NUMBER | Piiranha / post-process | 0.95 | Piiranha label or Luhn retype |
| DRIVERS_LICENSE | Piiranha | 0.90 | Piiranha-specific type |
| ID_CARD | Piiranha | 0.90 | Piiranha-specific type |
| TAX_NUMBER | Piiranha | 0.90 | Piiranha-specific type |
| USERNAME | Piiranha | 0.85 | Piiranha-specific type |
| PASSWORD | Piiranha | 0.95 | Piiranha-specific type |
| ZIPCODE | Piiranha / config | 0.75 | Piiranha-specific type |

## Gold Validation

Validate and fix gold-standard JSONL annotations:

```bash
python gold_validate.py --in gold.jsonl --out gold_fixed.jsonl --fix
```

Options:

- `--in <file>`: Input JSONL file.
- `--out <file>`: Output fixed JSONL file.
- `--fix`: Apply safe auto-fixes.
- `--strict`: Treat warnings as errors.
- `--report <file>`: Write detailed JSON report.
- `--context <int>`: Context characters in report.
- `--require-text-field`: Fail if top-level `text` is missing.

Validation checks record IDs, text fields, entity types, entity offsets,
out-of-bounds spans, ordering, duplicates, and span text consistency.

## Dataset Splitting

Split annotations into dev/test sets without file leakage:

```bash
python split.py --in gold_fixed.jsonl --out-dir splits/ --mode stratified
```

Options:

- `--in <file>`: Input JSONL file.
- `--out-dir <dir>`: Output directory.
- `--dev-ratio <float>`: Target dev ratio.
- `--mode <stratified|random>`: Split strategy.
- `--seed <int>`: Random seed.
- `--allowed-types <list>`: Entity types to include.
- `--rare-types <list>`: Rare types to balance.
- `--min-positives-test <int>`: Minimum positives in test for rare types.

Outputs:

```text
splits/
  dev_ids.txt
  test_ids.txt
  dev_files.txt
  test_files.txt
  split_report.json
```

## Run Evaluation

```bash
python pii_detect.py --eval gold_fixed.jsonl --ids splits/dev_ids.txt --json
```

Options:

- `--eval <file>`: Gold JSONL file.
- `--ids <file>`: Evaluate only records with IDs in this file.
- `--files <file>`: Evaluate only records from files in this file.
- `--match <hybrid|exact|overlap>`: Matching strategy.
- `--overlap-min-chars <int>`: Minimum overlap for overlap matching.
- `--types <list>`: Entity types to evaluate.
- `--report-dir <dir>`: Directory for error dumps.
- `--write-fp`: Also dump false positives.
- `--json`: Print JSON summary to stdout.
- `--max-errors <int>`: Cap error dump lines.
- `--context <int>`: Context characters around errors.

## Metrics

Evaluation reports true positives, false negatives, false positives, recall,
precision, and F1 by entity type.

Matching modes:

- `exact`: Exact offset match.
- `overlap`: Any overlap of at least `--overlap-min-chars`.
- `hybrid`: Exact for SSN/phone/account/DOB-style entities, overlap for
  person/location-style entities.

Micro averages:

- `MICRO ALL`: Aggregates counts across all types.
- `MICRO P+L`: Aggregates only `PERSON` and `LOCATION`.

## Error Dumps

The `eval_report/` directory contains JSONL files for false negatives and,
when `--write-fp` is set, false positives.

Example false-negative line:

```json
{"id": "FILE=doc1.pdf/...", "type": "PERSON", "gold": { "text": "John Doe" }, "context": "Hello, my name is [[John Doe]] and I..."}
```

If evaluation selects `0 records`, check the split file being used. For small
datasets, `split.py` might move all records to `test` to satisfy rare-type
constraints.

## AI4Privacy

For the AI4Privacy benchmark workflow, see
[ai4privacy-evaluation.md](ai4privacy-evaluation.md).
