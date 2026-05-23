# PII Labeler

A local macOS GUI annotation tool for paragraph-level PII/NER gold labeling.

## Installation

1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the App

```bash
python app.py
```

## Keybindings

- **P**: PERSON
- **L**: LOCATION
- **A**: ADDRESS
- **S**: SSN
- **T**: PHONE_NUMBER
- **C**: ACCOUNT_NUMBER
- **B**: BIRTHDATE
- **D**: DATE
- **E**: EMAIL
- **K**: Toggle skip for current PDF
- **R**: Mark entire PDF as reviewed (no PII)
- **Delete**: Remove selected annotation
- **Enter**: Accept current suggestion
- **Shift+Enter**: Accept all suggestions
- **Ctrl+Z**: Undo
- **Ctrl+S**: Save
- **Ctrl+N**: Next paragraph (marks current as done, auto-reviews PDF when leaving)
- **Ctrl+P**: Previous paragraph

## Filters

- **All**: Show all files
- **Unlabeled**: Files not yet processed (no annotations, not reviewed)
- **Labeled**: Files that are done (have annotations, processed, or in reviewed PDF)
- **Skipped**: Files in skipped PDFs
- **Unskipped**: Files not in skipped PDFs

## Export

Exported gold data is in JSONL format:
`{"id": "...", "path": "...", "text": "...", "entities": [{"type": "...", "start": 0, "end": 10}, ...]}`
