# PDF Pipeline

The full workflow moves from a raw PDF corpus to annotated gold data and model
evaluation.

```text
PDF Corpus
  -> index_corpus.py
  -> sample_candidates.py
  -> select_pii.py
  -> sample_pii.py
  -> manual annotation
  -> gold_validate.py
  -> split.py
  -> pii_detect.py --eval
```

## Quick Start

```bash
# 1. Index your PDF corpus
python index_corpus.py --root /path/to/pdfs --out corpus_index.jsonl

# 2. Sample candidates for annotation
python sample_candidates.py --index corpus_index.jsonl --out candidates_500.txt --report candidates_500_report.json --n 500

# 3. Filter to PDFs likely containing PII
python select_pii.py --in candidates_500.txt --out pii_shortlist.txt --report pii_scan_report.jsonl

# 4. Sample balanced set for annotation
python sample_pii.py --in pii_scan_report.jsonl --out annotation_sample.jsonl --with-pii 280 --without-pii 20

# 5. Annotate sampled PDFs and export gold.jsonl

# 6. Validate annotations
python gold_validate.py --in gold.jsonl --out gold_fixed.jsonl --fix

# 7. Split into dev/test
python split.py --in gold_fixed.jsonl --out-dir splits/

# 8. Evaluate
python pii_detect.py --eval gold_fixed.jsonl --ids splits/dev_ids.txt --json
```

## Stage 1: Index Corpus

`index_corpus.py` builds a JSONL metadata index of a PDF corpus.

```bash
python index_corpus.py \
  --root /path/to/pdfs \
  --out corpus_index.jsonl \
  --workers 8 \
  --resume
```

Each record includes `pdf_id`, `path`, `bytes`, `size_bucket`, `page_count`,
PDF metadata, scan likelihood, scan score, and any processing errors.

## Stage 2: Sample Candidates

`sample_candidates.py` selects a diverse candidate pool for PII scanning.

```bash
python sample_candidates.py \
  --index corpus_index.jsonl \
  --out candidates_5000.txt \
  --report candidates_5000.report.json \
  --n 5000 \
  --seed 42
```

Useful options:

- `--prefer-textpdf`: Prioritize non-scanned PDFs with text layers.
- `--scanned-share <float>`: Target fraction of scanned PDFs.
- `--page-buckets <spec>`: Page count buckets such as `1,2-5,6-20,21+`.
- `--exclude-file <path>`: Paths or IDs to exclude.

## Stage 3: Select PII

`select_pii.py` filters candidate PDFs and records whether extracted text likely
contains PII. It expects an external extractor command.

```bash
python select_pii.py \
  --in candidates_5000.txt \
  --out pii_shortlist.txt \
  --report pii_scan_report.jsonl \
  --extract /path/to/extract-text.sh \
  --extraction-dir data/extracted
```

The extractor output should use page and paragraph files:

```text
PAGE=0001/PAR=0001.txt
PAGE=0001/PAR=0002.txt
```

The JSONL report includes file path, PDF ID, PII status, processing stats, and
detected entity counts.

## Stage 4: Sample PII

`sample_pii.py` creates a balanced annotation sample with and without PII.

```bash
python sample_pii.py \
  --in pii_scan_report.jsonl \
  --out annotation_sample.jsonl \
  --with-pii 280 \
  --without-pii 20 \
  --seed 42 \
  --report annotation_sample_report.json
```

With annotation directory setup:

```bash
python sample_pii.py \
  --in pii_scan_report.jsonl \
  --out annotation_sample.jsonl \
  --with-pii 280 \
  --without-pii 20 \
  --paragraphs-dir /path/to/extracted \
  --annotation-dir ./annotation_set \
  --copy-pdfs
```

## Stage 5: Manual Annotation

Use `pii_labeler/app.py` to label PII spans in extracted paragraphs.

Keyboard shortcuts:

- `P`: PERSON
- `L`: LOCATION
- `A`: ADDRESS
- `S`: SSN
- `T`: PHONE_NUMBER
- `C`: ACCOUNT_NUMBER
- `B`: BIRTHDATE
- `D`: DATE
- `E`: EMAIL
- `K`: Toggle skip for current PDF

The labeler exports `gold.jsonl` records containing `id`, `path`, `text`, and
`entities`.

## Stages 6-8

Validation, split generation, and evaluation are documented in
[evaluation.md](evaluation.md).
