#!/usr/bin/env python3
"""
PII Selection Pipeline
======================

This script filters a list of PDF files, identifying those that contain Personally Identifiable Information (PII)
using a pure regex-based approach. It is designed for high throughput and reliability.

Architecture:
-------------
1. **Input**: Reads a list of PDF paths from a text file.
2. **Extraction**: For each PDF, calls an external shell script (`extract-text.sh`) to convert PDF pages to text files.
   - Extractions are stored in `--extraction-dir/<pdf_basename>/`.
   - Already-extracted paragraphs are detected and reused (skips re-extraction).
3. **Detection**: Scans the extracted text files using `PIIDetector`.
   - **Regex Engine**: Uses compiled regex patterns for SSN, Phone, Email, Date, Account Numbers, and contextual
     matches for Name and Address.
   - **Performance**: Optimized for speed; avoids loading heavy ML models (spaCy).
4. **Reporting**:
   - **Shortlist**: Appends paths of positive matches to a plain text file.
   - **JSONL Report**: Writes a detailed JSON object for every processed file, including timing, stats
     (page/paragraph counts), and match details (or error logs).

Usage:
------
    python3 select_pii.py --in candidates_5000.txt --out pii_shortlist.txt --report pii_scan_report.jsonl

See `python3 select_pii.py --help` for all options.
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Optional, Dict, Any, Tuple

from tqdm import tqdm

# --- Configuration & Constants ---

DEFAULT_CANDIDATES = "candidates_5000.txt"
DEFAULT_SHORTLIST = "pii_shortlist.txt"
DEFAULT_REPORT = "pii_scan_report.jsonl"
DEFAULT_EXTRACT_SCRIPT = "extract-text.sh"
DEFAULT_TMP_ROOT = "/tmp"

# --- Detector Class ---

class PIIDetector:
    """
    Regex-based PII Detector.

    Implements a set of high-recall regular expressions to identify sensitive information
    in unstructured text. Designed to replace slower ML-based approaches.

    Supported Entities:
    - **SSN**: US Social Security Numbers (formatted).
    - **PHONE**: US Phone numbers (various formats).
    - **EMAIL**: Email addresses.
    - **DATE**: Standard date formats (MM/DD/YYYY, YYYY-MM-DD).
    - **ACCOUNT**: 8-12 digit sequences.
    - **PERSON_CTX**: Capitalized names following context markers ("Name:", "Employee:", etc.).
    - **ADDRESS_CTX**: Address usage following context markers ("Address:", "Residing at:").
    """
    def __init__(self):
        self._compile_regexes()

    def _compile_regexes(self):
        # 1. High Confidence Patterns
        
        # US SSN: 3-2-4 digits
        self.re_ssn = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
        
        # Phone: (123) 456-7890, 123-456-7890, 123.456.7890
        self.re_phone = re.compile(r'(\b\d{3}[-.]?\d{3}[-.]?\d{4}\b)|(\(\d{3}\)\s*\d{3}[-.]?\d{4})')
        
        # Email: Simple, fast
        self.re_email = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
        
        # Date: MM/DD/YYYY or YYYY-MM-DD
        self.re_date = re.compile(r'\b(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/((19|20)\d{2})\b|\b((19|20)\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b')
        
        # Account number: 8-12 digits
        self.re_account = re.compile(r'\b\d{8,12}\b')

        # 2. Contextual / Structural Patterns (Heuristics)
        # Catch "Name: John Doe"
        self.re_name_context = re.compile(r'\b(Name|Employee|Beneficiary|Customer)\s*:\s*([A-Z][a-z]+(\s+[A-Z][a-z]+)+)')
        
        # Catch "Address: 123 Main St" - requires street suffix OR zipcode
        # Street suffixes: St, Street, Rd, Road, Ave, Avenue, Blvd, Lane, Ln, Drive, Dr, Way, Court, Ct, Place, Pl, Circle, Cir
        # Zipcode: 5 digits optionally followed by -4 digits
        self.re_addr_context = re.compile(
            r'\b(Address|Residing at)\s*:\s*'
            r'('
            r'\d+\s+[A-Za-z0-9. ]+(?:St|Street|Rd|Road|Ave|Avenue|Blvd|Boulevard|Lane|Ln|Drive|Dr|Way|Court|Ct|Place|Pl|Circle|Cir)\b'
            r'|'
            r'[^,\n]{5,50}\d{5}(?:-\d{4})?'
            r')',
            re.IGNORECASE
        )

    def detect(self, text: str, threshold: float) -> Optional[Dict[str, Any]]:
        """
        Scans a string for the first PII match exceeding the threshold.

        Args:
            text (str): The content of a paragraph/page.
            threshold (float): Minimum confidence score (0.0 - 1.0) to report a match.
                               Note: Most regex matches have fixed high scores (0.8-1.0).

        Returns:
            Optional[Dict[str, Any]]: A dictionary containing match details if found, else None.
            Format:
                {
                    "type": str,   # e.g., "SSN", "EMAIL"
                    "score": float,# Confidence score
                    "text": str    # The matched text
                }
        """
        # 1. SSN (Highest Risk)
        if self.re_ssn.search(text):
            return {"type": "SSN", "score": 1.0, "text": self.re_ssn.search(text).group(0)}
            
        # 2. Email
        if self.re_email.search(text):
            return {"type": "EMAIL", "score": 1.0, "text": self.re_email.search(text).group(0)}
            
        # 3. Phone
        if self.re_phone.search(text):
            return {"type": "PHONE", "score": 0.8, "text": self.re_phone.search(text).group(0)}

        # 4. Contextual Name
        m_name = self.re_name_context.search(text)
        if m_name:
            # Group 2 has the actual name value
            return {"type": "PERSON_CTX", "score": 0.8, "text": m_name.group(2)}

        # 5. Contextual Address
        m_addr = self.re_addr_context.search(text)
        if m_addr:
            return {"type": "ADDRESS_CTX", "score": 0.8, "text": m_addr.group(2)}

        # 6. Dates (Lower priority, often benign)
        if self.re_date.search(text):
             # Only strictly if threshold allows low score features? 
             # Let's say dates are 0.5 risk unless threshold is low.
             if 0.5 >= threshold:
                 return {"type": "DATE", "score": 0.5, "text": self.re_date.search(text).group(0)}
                 
        return None

# --- Helpers ---

def scan_paragraphs(extraction_dir: str, detector: PIIDetector, threshold: float, max_paragraphs: int) -> Tuple[bool, Optional[Dict], int, float, Dict[str, int]]:
    """
    Recursively scans all .txt files within a directory for PII.

    Args:
        extraction_dir (str): Root directory to scan (usually the per-PDF temp folder).
        detector (PIIDetector): The initialized detector instance.
        threshold (float): PII detection threshold.
        max_paragraphs (int): Maximum number of paragraph files to read before stopping (0 = unlimited).

    Returns:
        Tuple:
            - found_match (bool): True if PII was found.
            - match_details (Optional[Dict]): The match object if found.
            - paragraphs_scanned (int): Number of files processed.
            - scan_duration (float): Time taken in seconds.
            - stats (Dict[str, int]): Dictionary with "total_pages" and "total_paragraphs" counts.
    """
    t0 = time.time()
    paragraphs = []
    
    # We want to count pages too. 
    # Structure: tmp/<DIR>/PAGE=XXXX/PAR=XXXX.txt
    pages_seen = set()
    
    for root, dirs, files in os.walk(extraction_dir):
        # Heuristic for page counting: check if current dir name starts with PAGE=
        if os.path.basename(root).startswith("PAGE="):
            pages_seen.add(os.path.basename(root))
            
        for f in files:
            if f.endswith(".txt"):
                paragraphs.append(os.path.join(root, f))
    
    paragraphs.sort() # Deterministic order
    total_paragraphs = len(paragraphs)
    total_pages = len(pages_seen)
    
    stats = {
        "total_pages": total_pages, 
        "total_paragraphs": total_paragraphs
    }
    
    count = 0
    for p_path in paragraphs:
        if max_paragraphs > 0 and count >= max_paragraphs:
            break
        
        count += 1
        try:
            with open(p_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Cap reading to avoid memory bombs
                text = f.read(200000)
                
            match = detector.detect(text, threshold)
            if match:
                # Add location context
                match['paragraph'] = p_path
                return True, match, count, time.time() - t0, stats
        except Exception as e:
            logging.warning(f"Error reading {p_path}: {e}")
            
    return False, None, count, time.time() - t0, stats

# --- Main ---

def main():
    """
    Main CLI entry point.
    Parses arguments, executes the extraction-detection loop, and handles logging/reporting.
    """
    parser = argparse.ArgumentParser(description="Filter PDFs containing PII")
    parser.add_argument("--in", dest="input_file", default=DEFAULT_CANDIDATES, help="Input candidates file")
    parser.add_argument("--out", dest="output_file", default=DEFAULT_SHORTLIST, help="Shortlist output file")
    parser.add_argument("--report", dest="report_file", default=DEFAULT_REPORT, help="Report JSONL output")
    parser.add_argument("--extract", dest="extract_script", default=DEFAULT_EXTRACT_SCRIPT, help="Extraction script path")
    parser.add_argument("--extraction-dir", dest="extraction_dir", default=DEFAULT_TMP_ROOT, help="Directory for extracted paragraphs")
    parser.add_argument("--pii-threshold", type=float, default=0.0, help="Score threshold")
    parser.add_argument("--max-paragraphs", type=int, default=0, help="Max paragraphs per PDF (0=all)")
    parser.add_argument("--no-resume", action="store_true", help="Disable resume logic")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop immediately on extraction error and show details")
    parser.add_argument("--log", default="pipeline.log", help="Log file path")
    
    args = parser.parse_args()
    
    # Setup logging
    # Setup logging
    # Console: WARNING+ (so it doesn't break tqdm)
    # File: INFO+ (full details)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove default handlers if any
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    
    # File Handler
    file_handler = logging.FileHandler(args.log)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    root_logger.addHandler(file_handler)
    
    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING) # Only warnings/errors on console
    console_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    root_logger.addHandler(console_handler)
    
    # Validate inputs
    if not os.path.exists(args.input_file):
        logging.error(f"Input file not found: {args.input_file}")
        sys.exit(1)
        
    extract_cmd = os.path.abspath(args.extract_script)
    if not os.path.exists(extract_cmd):
        logging.error(f"Extraction script not found: {extract_cmd}")
        sys.exit(1)
        
    # Resume Logic
    processed_files = set()
    if not args.no_resume and os.path.exists(args.report_file):
        logging.info("Scanning report for resumed files...")
        with open(args.report_file, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    processed_files.add(data.get('pdf'))
                except:
                    pass
        logging.info(f"Resuming: skipping {len(processed_files)} previously processed files.")

    # Init Detector
    logging.info(f"Initializing detector (pure regex)...")
    detector = PIIDetector()
    
    # Process
    # Resolve tmp_root to absolute to avoid CWD confusion when running extractor
    args.extraction_dir = os.path.abspath(args.extraction_dir)
    
    if not os.path.exists(args.extraction_dir):
        os.makedirs(args.extraction_dir, exist_ok=True)
        
    with open(args.input_file, 'r') as f_in, \
         open(args.output_file, 'a') as f_out, \
         open(args.report_file, 'a') as f_report:
        
        # Read all candidates to memory for tqdm (assuming rational size)
        candidates = [l.strip() for l in f_in if l.strip() and not l.strip().startswith("#")]
        
        pbar = tqdm(candidates, desc="Scanning PDFs", unit="pdf")
        for pdf_path in pbar:
            # Update description for liveliness
            short_name = os.path.basename(pdf_path)
            if len(short_name) > 30: 
                short_name = short_name[:27] + "..."
            pbar.set_description(f"Scanning {short_name}")

            if pdf_path in processed_files:
                continue
                
            logging.info(f"Processing: {pdf_path}")
            
            # 1. Extraction
            t_start = time.time()
            pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
            extract_dir = os.path.join(args.extraction_dir, pdf_basename)

            # Check if extraction already exists (has .txt files) or previously failed
            already_extracted = False
            extraction_failed_marker = os.path.join(extract_dir, ".extraction_failed")
            if os.path.exists(extraction_failed_marker):
                logging.info(f"Skipping previously failed extraction: {extract_dir}")
                continue
            if os.path.isdir(extract_dir):
                for root, dirs, files in os.walk(extract_dir):
                    if any(f.endswith('.txt') for f in files):
                        already_extracted = True
                        break

            try:
                if already_extracted:
                    logging.info(f"Skipping extraction, using existing: {extract_dir}")
                    t_extract = 0.0
                else:
                    os.makedirs(extract_dir, exist_ok=True)
                    proc = subprocess.run(
                        [extract_cmd, "--output-dir", extract_dir, pdf_path],
                        capture_output=True,
                        text=True,
                        cwd=os.path.dirname(extract_cmd)
                    )

                    t_extract = time.time() - t_start

                    if proc.returncode != 0:
                        logging.error(f"Extraction failed for {pdf_path}. RC={proc.returncode}")
                        error_msg = f"STDERR:\n{proc.stderr}\nSTDOUT:\n{proc.stdout}" if (proc.stderr or proc.stdout) else "Unknown error (no output)"

                        # Write marker file to skip on future runs
                        with open(extraction_failed_marker, 'w') as f_marker:
                            f_marker.write(error_msg)

                        if args.stop_on_error:
                            logging.error(f"STOPPING due to error (--stop-on-error):\n{error_msg}")
                            sys.exit(1)

                        report_entry = {
                            "pdf": pdf_path,
                            "status": "extract_error",
                            "contains_pii": None,
                            "error": error_msg[-1000:]
                        }
                        f_report.write(json.dumps(report_entry) + "\n")
                        f_report.flush()
                        continue
                
                # 2. Scanning
                found, match_data, count, t_scan, stats = scan_paragraphs(extract_dir, detector, args.pii_threshold, args.max_paragraphs)
                
                timing = {
                    "extract": round(t_extract * 1000, 1),
                    "scan": round(t_scan * 1000, 1),
                    "total": round((t_extract + t_scan) * 1000, 1)
                }
                
                if found:
                    logging.info(f"MATCH: {match_data['type']} in {pdf_path} (Pages: {stats['total_pages']}, Pars: {stats['total_paragraphs']})")
                    f_out.write(pdf_path + "\n")
                    f_out.flush()
                    
                    report_entry = {
                        "pdf": pdf_path,
                        "status": "ok",
                        "contains_pii": True,
                        "match": match_data,
                        "stats": stats,
                        "timing_ms": timing
                    }
                else:
                    if stats['total_paragraphs'] == 0:
                        logging.warning(f"Extraction produced 0 paragraphs for {pdf_path}")
                        logging.warning(f"Contents of {extract_dir}:")
                        for root, _, files in os.walk(extract_dir):
                            for name in files:
                                logging.warning(f"  {os.path.join(root, name)}")
                                
                    logging.info(f"No match in {pdf_path} (Pages: {stats['total_pages']}, Pars: {stats['total_paragraphs']})")
                    report_entry = {
                        "pdf": pdf_path,
                        "status": "ok",
                        "contains_pii": False,
                        "stats": stats,
                        "timing_ms": timing
                    }
                    
                f_report.write(json.dumps(report_entry) + "\n")
                f_report.flush()

            except Exception as e:
                logging.exception(f"Fatal error processing {pdf_path}")
                # Don't crash the whole loop, just log
                
if __name__ == "__main__":
    main()
