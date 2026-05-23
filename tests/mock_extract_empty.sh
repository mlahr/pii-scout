#!/bin/bash
# Mock that requires --output-dir BUT produces NO OUPUT
# Simulating the user's issue

OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --output-dir)
      OUTPUT_DIR="$2"
      shift; shift ;;
    *) scale="$1"; shift ;;
  esac
done

echo "Starting extraction (mock silent failure)..."
# Do nothing. Create no files.
echo "Done."
