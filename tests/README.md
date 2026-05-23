# Tests for select_pii.py

## Unit Tests
Run the unit tests for the detector class and helpers:
```bash
python3 tests/test_select_pii.py
```

## Integration Tests
Run a full integration test using the mock extraction script:
```bash
# 1. Ensure dummy candidates exist
# (Already created as dummy_candidates.txt)

# 2. Run the pipeline
python3 select_pii.py \
  --in tests/dummy_candidates.txt \
  --extract tests/mock_extract.sh \
  --tmp-root tests \
  --out tests/shortlist.txt \
  --report tests/report.jsonl \
  --log tests/pipeline.log \
  --keep-tmp
```

## Files
- `test_select_pii.py`: Unit tests.
- `mock_extract.sh`: Mock extraction script that injects PII into "dirty_pii.pdf" and clean text into others.
- `dummy_candidates.txt`: List of dummy PDFs for testing.
