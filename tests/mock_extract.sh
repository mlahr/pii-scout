#!/bin/bash
# Mock extraction script
# Usage: ./mock_extract.sh <pdf_path>

PDF_PATH="$1"
# Create a robust unique dir name based on the pdf basename + random
# In real life, the extractor does this.
BASE=$(basename "$PDF_PATH" .pdf)
OUT_DIR="$(pwd)/mock_extract_output_${BASE}_$$"

mkdir -p "$OUT_DIR/PAGE=0001"
echo "This is some dummy text for $BASE." > "$OUT_DIR/PAGE=0001/PAR=0001.txt"

# If the PDF filename contains "pii", inject PII
if [[ "$PDF_PATH" == *"pii"* ]]; then
  echo "My SSN is 999-99-9999" > "$OUT_DIR/PAGE=0001/PAR=0002.txt"
fi

# We don't print anything to stdout usually, but let's be silent unless error
