# Data Policy

This repository contains source code, configuration templates, and small
synthetic test fixtures only.

The following are intentionally not bundled:

- PDF corpora and extracted paragraph text
- annotation exports and annotation autosaves
- evaluation reports and false-positive/false-negative dumps
- generated split files
- AI4Privacy converted JSONL files
- WGND or other third-party name datasets
- generated dictionary caches (`*.bloom`, `*.marisa`, `*.sha256`)

## What Works Without Extra Data

After installing dependencies and a SpaCy model, you can run text detection,
the API, unit tests, and synthetic examples directly from the repository.

The full PDF-to-evaluation pipeline needs local inputs. The repository does not
ship private PDFs, extracted paragraphs, annotation exports, or benchmark
outputs because those can contain sensitive text or third-party licensed data.

## Local Configuration

Copy the example config and keep the copy local:

```bash
cp pii_config.example.yaml pii_config.yaml
```

`pii_config.yaml` is ignored by git and is the right place for local filesystem
paths, model settings, and dataset-specific detector tuning.

## PDF Text Extraction

`select_pii.py` and `sample_pii.py` can call an external extraction command.
Provide your own script with `--extract` or `--extract-cmd`. The expected output
is a directory containing page/paragraph text files, for example:

```text
PAGE=0001/PAR=0001.txt
PAGE=0001/PAR=0002.txt
PAGE=0002/PAR=0001.txt
```

Keep generated extraction output under an ignored directory such as `data/`,
`annotation_set/`, or another path outside the repository.

## AI4Privacy Evaluation

Use `convert_ai4privacy.py` to generate AI4Privacy evaluation data locally
after reviewing the dataset's current license and access terms. Do not commit
the generated `ai4privacy_gold.jsonl` or split ID files.

## Name Dictionaries

Dictionary-based name detection can use local name lists configured through
`pii_config.yaml`:

```yaml
name_lists:
  first_names:
    source: "/path/to/first_names.txt"
  last_names:
    source: "/path/to/last_names.txt"
  stopwords:
    source: "/path/to/stopwords-en.json"
```

If you do not configure these files, run with `--detectors ner,regex` for
normal text detection without the dictionary detector.

Keep local corpora and generated outputs outside git, or under paths ignored by
`.gitignore`.
