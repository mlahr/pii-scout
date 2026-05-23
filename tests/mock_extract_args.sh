#!/bin/bash
# Mock that requires --output-dir

OUTPUT_DIR=""
PDF_PATH=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --output-dir)
      OUTPUT_DIR="$2"
      shift # past argument
      shift # past value
      ;;
    *)
      PDF_PATH="$1"
      shift # past argument
      ;;
  esac
done

if [ -z "$OUTPUT_DIR" ]; then
    >&2 echo "Error: --output-dir is required"
    exit 1
fi

if [[ "$PDF_PATH" == *"fail"* ]]; then
  >&2 echo "CRITICAL ERROR: Failed to extract text from $PDF_PATH (Simulated)"
  exit 1
fi

BASE=$(basename "$PDF_PATH" .pdf)
# We must write TO the output dir as requested
# But wait, original heuristic looks for a NEW directory in tmp root.
# If we dump files directly into --output-dir, there is no "new directory".
# UNLESS the script behaves by creating a subdir.
# The user PROMPT said: "Writes paragraphs to /tmp/<FILE>/<PAGE>/<PARAGRAPH>.txt"
# If we pass --output-dir /tmp, it writes to /tmp/<FILE>...
# So we should simulate creating a subdirectory in OUTPUT_DIR.

SUBDIR="$OUTPUT_DIR/mock_extract_output_${BASE}_$$"
mkdir -p "$SUBDIR/PAGE=0001"
echo "Dummy text" > "$SUBDIR/PAGE=0001/PAR=0001.txt"
