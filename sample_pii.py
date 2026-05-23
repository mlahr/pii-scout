#!/usr/bin/env python3
"""
PII Sample Selection
====================

Selects a stratified sample of PDFs from select_pii.py output for annotation.
Samples files WITH PII and WITHOUT PII, stratified by page count buckets.
Optionally copies PDFs and extracted paragraphs to an annotation directory.

Usage:
    python sample_pii.py --in pii_scan_report.jsonl --out annotation_sample.jsonl --with-pii 280 --without-pii 20

    # With annotation directory setup:
    python sample_pii.py --in pii_scan_report.jsonl --out annotation_sample.jsonl \\
        --paragraphs-dir /path/to/extracted --annotation-dir ./annotation_set --copy-pdfs
"""

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import logging
from collections import defaultdict
from typing import Dict, List, Any, Tuple, Callable, Optional

from tqdm import tqdm

DEFAULT_PAGE_BUCKETS = "1,2-5,6-20,21+"

log = logging.getLogger(__name__)


def parse_page_buckets(bucket_str: str) -> List[Tuple[str, Callable[[int], bool]]]:
    """Parses '1,2-5,6-20,21+' into a list of (label, check_fn)."""
    defs = []
    parts = bucket_str.split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                defs.append((part, lambda n, s=start, e=end: s <= n <= e))
            except ValueError:
                pass
        elif part.endswith('+'):
            try:
                start = int(part[:-1])
                defs.append((part, lambda n, s=start: n >= s))
            except ValueError:
                pass
        else:
            try:
                val = int(part)
                defs.append((part, lambda n, v=val: n == v))
            except ValueError:
                pass
    return defs


def compute_page_bucket(page_count: int, buckets_def: List[Tuple[str, Callable[[int], bool]]]) -> str:
    """Map page count to bucket label."""
    if page_count is None or page_count <= 0:
        return "1"  # Default bucket for missing/zero pages

    for label, check_fn in buckets_def:
        if check_fn(page_count):
            return label
    return "other"


def load_and_partition(
    input_file: str,
    page_bucket_defs: List[Tuple[str, Callable[[int], bool]]]
) -> Tuple[Dict[str, List[Dict]], Dict[str, List[Dict]], Dict[str, Any]]:
    """
    Load report.jsonl and partition into pii_pool and non_pii_pool.

    Returns:
        pii_pool: Dict[bucket_key -> List[record]]
        non_pii_pool: Dict[bucket_key -> List[record]]
        stats: Dict with counts
    """
    pii_pool = defaultdict(list)
    non_pii_pool = defaultdict(list)

    stats = {
        "total_read": 0,
        "status_ok": 0,
        "status_error": 0,
        "with_pii": 0,
        "without_pii": 0,
        "missing_stats": 0,
    }

    with open(input_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            stats["total_read"] += 1

            # Skip errors
            if rec.get("status") != "ok":
                stats["status_error"] += 1
                continue

            stats["status_ok"] += 1

            # Get page count for bucketing
            rec_stats = rec.get("stats", {})
            page_count = rec_stats.get("total_pages")

            if page_count is None or page_count == 0:
                stats["missing_stats"] += 1
                page_count = 1  # Default bucket

            bucket_key = compute_page_bucket(page_count, page_bucket_defs)
            contains_pii = rec.get("contains_pii", False)

            if contains_pii:
                pii_pool[bucket_key].append(rec)
                stats["with_pii"] += 1
            else:
                non_pii_pool[bucket_key].append(rec)
                stats["without_pii"] += 1

    return pii_pool, non_pii_pool, stats


def stratified_sample(
    pool: Dict[str, List[Dict]],
    target_n: int,
    rng: random.Random
) -> Tuple[List[Dict], Dict[str, Dict]]:
    """
    Sample target_n items from pool with proportional stratification.
    Each non-empty bucket gets at least 1 sample.

    Returns:
        selected: List of selected records
        bucket_stats: Dict[bucket -> {available, selected}]
    """
    available_keys = [k for k in pool.keys() if len(pool[k]) > 0]

    if not available_keys:
        return [], {}

    total_items = sum(len(pool[k]) for k in available_keys)

    if total_items == 0:
        return [], {}

    # If target exceeds available, take everything
    if target_n >= total_items:
        selected = []
        bucket_stats = {}
        for k in available_keys:
            selected.extend(pool[k])
            bucket_stats[k] = {"available": len(pool[k]), "selected": len(pool[k])}
        rng.shuffle(selected)
        return selected, bucket_stats

    # Proportional allocation with minimum 1 per bucket
    raw_allocs = {k: (len(pool[k]) / total_items) * target_n for k in available_keys}
    final_allocs = {k: max(1, round(v)) for k, v in raw_allocs.items()}

    # Fix sum to match target_n
    current_sum = sum(final_allocs.values())
    diff = target_n - current_sum

    if diff > 0:
        # Add to largest buckets
        sorted_keys = sorted(available_keys, key=lambda k: len(pool[k]), reverse=True)
        for i in range(diff):
            k = sorted_keys[i % len(sorted_keys)]
            if final_allocs[k] < len(pool[k]):
                final_allocs[k] += 1
    elif diff < 0:
        # Remove from largest allocations (that are > 1)
        to_remove = -diff
        while to_remove > 0:
            candidates = [k for k in final_allocs if final_allocs[k] > 1]
            if not candidates:
                break
            candidates.sort(key=lambda k: final_allocs[k], reverse=True)
            final_allocs[candidates[0]] -= 1
            to_remove -= 1

    # Edge case: more buckets than target_n
    if len(available_keys) > target_n:
        keys_to_keep = rng.sample(available_keys, target_n)
        final_allocs = {k: 1 for k in keys_to_keep}

    # Sample from each bucket
    selected = []
    bucket_stats = {}

    for k in final_allocs:
        available_list = pool[k]
        count = min(final_allocs[k], len(available_list))

        sampled = rng.sample(available_list, count)
        selected.extend(sampled)

        bucket_stats[k] = {
            "available": len(available_list),
            "selected": count
        }

    rng.shuffle(selected)
    return selected, bucket_stats


def write_output(output_file: str, selected: List[Dict]):
    """Write selected records to JSONL."""
    with open(output_file, 'w') as f:
        for rec in selected:
            f.write(json.dumps(rec) + "\n")


def find_paragraphs_dir(pdf_path: str, paragraphs_root: str) -> Optional[str]:
    """Find extracted paragraphs for a PDF in the paragraphs directory.

    Looks for a subdirectory matching the PDF basename (without extension).
    Returns path to the directory containing PAGE=XXXX folders, or None.
    """
    pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]

    # Look for exact match first
    candidate = os.path.join(paragraphs_root, pdf_basename)
    if os.path.isdir(candidate):
        return candidate

    # Look for subdirectories that might contain the extracted content
    for name in os.listdir(paragraphs_root):
        path = os.path.join(paragraphs_root, name)
        if not os.path.isdir(path):
            continue

        # Check if this directory matches the pdf basename
        if name == pdf_basename or name.startswith(pdf_basename):
            return path

    return None


def extract_paragraphs(pdf_path: str, extract_cmd: str, output_dir: str) -> Optional[str]:
    """Extract paragraphs from PDF using extract-text.sh.

    Returns path to extracted directory, or None on failure.
    """
    pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
    extract_dir = os.path.join(output_dir, pdf_basename)
    os.makedirs(extract_dir, exist_ok=True)

    try:
        proc = subprocess.run(
            [extract_cmd, "--output-dir", extract_dir, pdf_path],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(extract_cmd)
        )

        if proc.returncode != 0:
            log.error(f"Extraction failed for {pdf_path}: {proc.stderr[:500]}")
            return None

        return extract_dir
    except Exception as e:
        log.error(f"Extraction error for {pdf_path}: {e}")
        return None


def copy_to_annotation_dir(
    pdf_path: str,
    paragraphs_dir: str,
    annotation_dir: str,
    copy_pdf: bool = False
) -> Dict[str, Any]:
    """Copy paragraphs (and optionally PDF) to annotation directory.

    Supports both input formats:
    - PAGE=XXXX/PAR=XXXX.txt (converts to pageN/pN.txt)
    - pageN/N.txt (copies as-is)

    Returns stats about copied files.
    """
    pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
    dest_dir = os.path.join(annotation_dir, pdf_basename)

    stats = {
        "pages": 0,
        "paragraphs": 0,
        "pdf_copied": False
    }

    # Walk the paragraphs directory looking for page directories
    # Supports both "PAGE=XXXX" and "pageN" formats
    for root, dirs, files in os.walk(paragraphs_dir):
        dirname = os.path.basename(root)

        # Check for PAGE=XXXX format (e.g., PAGE=0001)
        page_num = None
        match = re.match(r"PAGE=(\d+)", dirname)
        if match:
            page_num = int(match.group(1))
        else:
            # Check for pageN format (e.g., page1)
            match = re.match(r"page(\d+)$", dirname)
            if match:
                page_num = int(match.group(1))

        if page_num is None:
            continue

        new_page_dir = f"page{page_num}"
        page_dest = os.path.join(dest_dir, new_page_dir)
        os.makedirs(page_dest, exist_ok=True)
        stats["pages"] += 1

        # Copy paragraph files
        for filename in sorted(files):
            if not filename.endswith(".txt"):
                continue

            # Extract paragraph number from various formats
            # PAR=0001.txt -> 0 (0-indexed)
            # 1.txt -> 1 (keep as-is)
            par_match = re.match(r"PAR=(\d+)\.txt", filename)
            if par_match:
                par_num = int(par_match.group(1)) - 1  # Convert to 0-indexed
                new_filename = f"p{par_num}.txt"
            else:
                # Keep original name (handles N.txt format)
                new_filename = filename

            src_path = os.path.join(root, filename)
            dst_path = os.path.join(page_dest, new_filename)
            shutil.copy2(src_path, dst_path)
            os.chmod(dst_path, 0o644)
            stats["paragraphs"] += 1

    # Copy PDF if requested
    if copy_pdf and os.path.exists(pdf_path):
        pdfs_dir = os.path.join(annotation_dir, "pdfs")
        os.makedirs(pdfs_dir, exist_ok=True)
        pdf_dest = os.path.join(pdfs_dir, os.path.basename(pdf_path))
        shutil.copy2(pdf_path, pdf_dest)
        os.chmod(pdf_dest, 0o644)
        stats["pdf_copied"] = True

    return stats


def setup_annotation_dir(
    selected_records: List[Dict],
    paragraphs_dir: Optional[str],
    annotation_dir: str,
    extract_cmd: Optional[str],
    copy_pdfs: bool
) -> Dict[str, Any]:
    """Set up annotation directory with paragraphs from selected PDFs.

    Returns summary stats.
    """
    os.makedirs(annotation_dir, exist_ok=True)

    summary = {
        "total": len(selected_records),
        "copied": 0,
        "extracted": 0,
        "skipped": 0,
        "total_pages": 0,
        "total_paragraphs": 0,
        "pdfs_copied": 0
    }

    for rec in tqdm(selected_records, desc="Processing PDFs", unit="file"):
        pdf_path = rec.get("pdf")
        if not pdf_path:
            log.warning("Record missing pdf path, skipping")
            summary["skipped"] += 1
            continue

        # Try to find existing paragraphs
        found_dir = None
        if paragraphs_dir:
            found_dir = find_paragraphs_dir(pdf_path, paragraphs_dir)

        # Extract if not found and we have extract command
        if not found_dir and extract_cmd:
            log.debug(f"Extracting paragraphs for {pdf_path}")
            found_dir = extract_paragraphs(pdf_path, extract_cmd, annotation_dir + "_tmp")
            if found_dir:
                summary["extracted"] += 1

        if not found_dir:
            log.warning(f"No paragraphs found for {pdf_path}, skipping")
            summary["skipped"] += 1
            continue

        # Copy to annotation directory
        copy_stats = copy_to_annotation_dir(pdf_path, found_dir, annotation_dir, copy_pdfs)
        summary["copied"] += 1
        summary["total_pages"] += copy_stats["pages"]
        summary["total_paragraphs"] += copy_stats["paragraphs"]
        if copy_stats["pdf_copied"]:
            summary["pdfs_copied"] += 1

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Sample PDFs from PII detection report for annotation."
    )
    parser.add_argument("--in", dest="input_file", required=True,
                        help="Input report JSONL from select_pii.py")
    parser.add_argument("--out", dest="output_file", required=True,
                        help="Output sampled JSONL file")
    parser.add_argument("--with-pii", dest="with_pii", type=int, default=280,
                        help="Number of files WITH PII to sample (default: 280)")
    parser.add_argument("--without-pii", dest="without_pii", type=int, default=20,
                        help="Number of files WITHOUT PII to sample (default: 20)")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed for reproducibility (default: 42)")
    parser.add_argument("--page-buckets", default=DEFAULT_PAGE_BUCKETS,
                        help="Page count bucket definitions (default: 1,2-5,6-20,21+)")
    parser.add_argument("--report", dest="report_file", default=None,
                        help="Optional JSON report path for sampling statistics")

    # Annotation directory setup
    parser.add_argument("--paragraphs-dir", dest="paragraphs_dir", default=None,
                        help="Directory containing pre-extracted paragraphs")
    parser.add_argument("--annotation-dir", dest="annotation_dir", default=None,
                        help="Output directory for annotation files (pii_labeler format)")
    parser.add_argument("--copy-pdfs", dest="copy_pdfs", action="store_true",
                        help="Also copy original PDFs to annotation-dir/pdfs/")
    parser.add_argument("--extract-cmd", dest="extract_cmd", default=None,
                        help="Path to extract-text.sh for on-demand extraction")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    rng = random.Random(args.seed)
    page_bucket_defs = parse_page_buckets(args.page_buckets)

    # Load and partition
    pii_pool, non_pii_pool, load_stats = load_and_partition(args.input_file, page_bucket_defs)

    log.info(f"Loaded {load_stats['total_read']} records from {args.input_file}")
    log.info(f"Valid: {load_stats['status_ok']}, Errors: {load_stats['status_error']}")
    log.info(f"With PII: {load_stats['with_pii']}, Without PII: {load_stats['without_pii']}")

    # Validate
    if load_stats['status_ok'] == 0:
        log.error("No valid records found in input file.")
        sys.exit(1)

    # Warnings for shortfall
    if load_stats['with_pii'] < args.with_pii:
        log.warning(f"Requested {args.with_pii} files with PII, but only {load_stats['with_pii']} available.")

    if load_stats['without_pii'] < args.without_pii:
        log.warning(f"Requested {args.without_pii} files without PII, but only {load_stats['without_pii']} available.")

    # Sample
    selected_pii, pii_bucket_stats = stratified_sample(pii_pool, args.with_pii, rng)
    selected_non_pii, non_pii_bucket_stats = stratified_sample(non_pii_pool, args.without_pii, rng)

    # Combine and shuffle
    all_selected = selected_pii + selected_non_pii
    rng.shuffle(all_selected)

    # Write output
    write_output(args.output_file, all_selected)

    log.info(f"Sampled {len(all_selected)} files to {args.output_file}")
    log.info(f"  With PII: {len(selected_pii)}")
    log.info(f"  Without PII: {len(selected_non_pii)}")

    # Optional report
    if args.report_file:
        report = {
            "input_file": args.input_file,
            "seed": args.seed,
            "requested": {
                "with_pii": args.with_pii,
                "without_pii": args.without_pii
            },
            "input_stats": load_stats,
            "selected": {
                "with_pii": len(selected_pii),
                "without_pii": len(selected_non_pii),
                "total": len(all_selected)
            },
            "bucket_stats": {
                "with_pii": pii_bucket_stats,
                "without_pii": non_pii_bucket_stats
            }
        }
        with open(args.report_file, 'w') as f:
            json.dump(report, f, indent=2)
        log.info(f"Report written to {args.report_file}")

    # Set up annotation directory if requested
    if args.annotation_dir:
        if not args.paragraphs_dir and not args.extract_cmd:
            log.error("--annotation-dir requires --paragraphs-dir or --extract-cmd")
            sys.exit(1)

        log.info(f"Setting up annotation directory: {args.annotation_dir}")
        annotation_stats = setup_annotation_dir(
            all_selected,
            args.paragraphs_dir,
            args.annotation_dir,
            args.extract_cmd,
            args.copy_pdfs
        )

        log.info(f"Annotation directory setup complete:")
        log.info(f"  Copied: {annotation_stats['copied']} PDFs")
        log.info(f"  Extracted: {annotation_stats['extracted']} PDFs")
        log.info(f"  Skipped: {annotation_stats['skipped']} PDFs")
        log.info(f"  Total pages: {annotation_stats['total_pages']}")
        log.info(f"  Total paragraphs: {annotation_stats['total_paragraphs']}")
        if args.copy_pdfs:
            log.info(f"  PDFs copied: {annotation_stats['pdfs_copied']}")


if __name__ == "__main__":
    main()
