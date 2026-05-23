#!/bin/bash
# Mock extraction script that fails for specific input
# Usage: ./mock_extract_fail.sh <pdf_path>

PDF_PATH="$1"

if [[ "$PDF_PATH" == *"fail"* ]]; then
  >&2 echo "CRITICAL ERROR: Failed to extract text from $PDF_PATH (Simulated)"
  exit 1
fi

# Fallback to normal behavior (simulated)
BASE=$(basename "$PDF_PATH" .pdf)
OUT_DIR="$(pwd)/mock_extract_output_failtest_${BASE}_$$"
mkdir -p "$OUT_DIR/PAGE=0001"
echo "Dummy text" > "$OUT_DIR/PAGE=0001/PAR=0001.txt"
