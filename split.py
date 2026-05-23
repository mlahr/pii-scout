#!/usr/bin/env python3
import argparse
import collections
import json
import logging
import os
import random
import re
import sys
from typing import Dict, List, Tuple, Set

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_TYPES = [
    "PERSON", "LOCATION", "ADDRESS", "SSN", "PHONE_NUMBER",
    "ACCOUNT_NUMBER", "BIRTHDATE"
]
DEFAULT_RARE_TYPES = ["SSN", "BIRTHDATE", "ACCOUNT_NUMBER"]

def parse_args():
    parser = argparse.ArgumentParser(description="Split paragraph-level gold annotations into dev/test sets without file leakage.")
    
    # Input/Output
    parser.add_argument("--in", dest="input_file", required=True, help="Input JSONL file")
    parser.add_argument("--out-dir", dest="output_dir", required=True, help="Output directory for split files")
    
    # Configuration
    parser.add_argument("--dev-ratio", type=float, default=0.8, help="Target ratio of records for dev set (default 0.8)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42)")
    parser.add_argument("--mode", choices=["random", "stratified"], default="stratified", help="Split mode (default stratified)")
    parser.add_argument("--file-key", default=r"^(?:FILE=)?([^/]+)", help="Regex to extract file ID from record ID (default extracts 'invoice_001' from 'FILE=invoice_001/...' or 'file1' from 'file1/...')")
    
    # Entity Types
    parser.add_argument("--allowed-types", help="Comma-separated list of allowed entity types")
    parser.add_argument("--rare-types", help="Comma-separated list of rare entity types to prioritize balancing")
    parser.add_argument("--min-positives-test", type=int, default=1, help="Minimum occurrences of each rare type in test set (default 1)")
    
    # Comparison
    parser.add_argument("--write", choices=["ids", "files", "both"], default="both", help="What to write to output files (default both)")
    parser.add_argument("--no-shuffle", action="store_true", help="Disable shuffling (only relevant for debugging, otherwise seed controls shuffle)")

    return parser.parse_args()

def load_and_group_data(input_file: str, file_key_pattern: str, allowed_types: Set[str]) -> Tuple[Dict[str, List[Dict]], int, List[str]]:
    """
    Reads JSONL, groups records by file_id, and counts entities.
    Returns:
        file_groups: Dict[file_id, list_of_records]
        total_records: int
        parse_errors: List[str]
    """
    file_groups = collections.defaultdict(list)
    total_records = 0
    parse_errors = []
    
    try:
        regex = re.compile(file_key_pattern)
    except re.error as e:
        logger.error(f"Invalid regex pattern: {e}")
        sys.exit(1)

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line: continue
                
                try:
                    record = json.loads(line)
                    rec_id = record.get("id")
                    
                    if not rec_id or not isinstance(rec_id, str):
                        parse_errors.append(f"Line {line_num}: Missing or invalid 'id'")
                        continue
                        
                    match = regex.search(rec_id)
                    if not match:
                        parse_errors.append(f"Line {line_num}: ID '{rec_id}' does not match file key pattern")
                        continue
                    
                    file_id = match.group(1)
                    
                    # Pre-calculate counts for this record (optimization for stratified)
                    ents = record.get("entities", [])
                    type_counts = collections.defaultdict(int)
                    if isinstance(ents, list):
                        for e in ents:
                            if isinstance(e, dict) and e.get("type") in allowed_types:
                                type_counts[e["type"]] += 1
                    
                    # Store minimal needed info or full record? 
                    # We accept full record as we just hold references.
                    # Attach counts to record for easier aggregation later? 
                    # Better to aggregate at file level now.
                    record["_type_counts"] = type_counts
                    
                    file_groups[file_id].append(record)
                    total_records += 1
                    
                except json.JSONDecodeError as e:
                    parse_errors.append(f"Line {line_num}: Invalid JSON - {e}")
                    
    except FileNotFoundError:
        logger.error(f"Input file not found: {input_file}")
        sys.exit(1)
        
    return file_groups, total_records, parse_errors

def get_file_stats(file_groups: Dict[str, List[Dict]], allowed_types: Set[str]) -> Dict[str, Dict[str, int]]:
    """
    Summarize entity counts per file.
    Returns: Dict[file_id, Dict[type, count]]
    """
    file_stats = {}
    for fid, records in file_groups.items():
        counts = collections.defaultdict(int)
        for r in records:
            for t, c in r.get("_type_counts", {}).items():
                counts[t] += c
        counts["_record_count"] = len(records)
        file_stats[fid] = counts
    return file_stats

def solve_random_split(file_ids: List[str], file_stats: Dict[str, Dict], total_records: int, dev_ratio: float, seed: int) -> Tuple[List[str], List[str]]:
    """
    Random split.
    """
    random.seed(seed)
    shuffled_files = list(file_ids)
    random.shuffle(shuffled_files)
    
    dev_files = []
    test_files = []
    
    dev_count = 0
    target_dev = total_records * dev_ratio
    
    # Greedy fill dev until full
    for fid in shuffled_files:
        rec_count = file_stats[fid]["_record_count"]
        # Basic logic: if adding it keeps us closer to target or we are under target
        # Actually standard simple logic: fill dev until >= target? Or closest?
        # "Assign first N files to dev until dev_ratio target"
        if dev_count < target_dev:
            dev_files.append(fid)
            dev_count += rec_count
        else:
            test_files.append(fid)
            
    return dev_files, test_files

def solve_stratified_split(
    file_ids: List[str], 
    file_stats: Dict[str, Dict], 
    allowed_types: Set[str], 
    rare_types: Set[str], 
    min_positives_test: int, 
    dev_ratio: float, 
    total_records: int,
    seed: int
) -> Tuple[List[str], List[str], List[str]]:
    """
    Stratified split logic as per spec.
    """
    random.seed(seed)
    
    # 1. Compute global counts and rarity weights
    global_counts = collections.defaultdict(int)
    for fid in file_ids:
        for t, c in file_stats[fid].items():
            if t in allowed_types:
                global_counts[t] += c
                
    weights = {}
    for t in allowed_types:
        w = 1.0 / (global_counts[t] + 1)
        if t in rare_types:
            w *= 5.0
        weights[t] = w
        
    # 2. Compute file rarity contribution (File score logic)
    # We also sort by this desc
    file_scores = []
    for fid in file_ids:
        score = sum(file_stats[fid].get(t, 0) * weights[t] for t in allowed_types)
        file_scores.append((fid, score))
        
    # Sort by score descending. Stable sort for determinism (using fid as tiebreak if score equal)
    file_scores.sort(key=lambda x: (x[1], x[0]), reverse=True)
    sorted_files = [x[0] for x in file_scores]
    
    # 3. Greedy assignment
    dev_files = []
    test_files = []
    
    dev_recs = 0
    test_recs = 0
    dev_type_counts = collections.defaultdict(int)
    test_type_counts = collections.defaultdict(int)
    
    target_dev_recs = total_records * dev_ratio
    
    for fid in sorted_files:
        stats = file_stats[fid]
        rec_c = stats["_record_count"]
        
        # Simulate adding to dev
        dev_diff = abs((dev_recs + rec_c) / total_records - dev_ratio)
        current_dev_diff = abs(dev_recs / total_records - dev_ratio) if total_records > 0 else 0
        
        # Cost function? Spec says:
        # "Primary objective: hit dev_ratio by record count."
        # "Secondary objective: balance rare types across splits."
        
        # Let's assess where this file is needed more.
        # If it has rare types that are currently 0 in test, preferring test might be good.
        
        # Simple greedy approach based on the spec:
        # "Choose the split that yields lower combined objective."
        
        # Let's simplify: 
        # If dev "needs" records (current ratio < target), lean dev.
        # UNLESS it contains a rare type that test has 0 of?
        
        # Let's calculate a cost for both options.
        # Option A: Add to Dev
        # Option B: Add to Test
        
        def calculate_cost(d_r, t_r, d_counts, t_counts):
            # 1. Ratio cost
            total = d_r + t_r
            if total == 0: return 0
            ratio = d_r / total if total > 0 else 0
            ratio_cost = abs(ratio - dev_ratio) * 100 # weight it up
            
            # 2. Rare balance cost
            rare_cost = 0
            for rt in rare_types:
                d_c = d_counts.get(rt, 0)
                t_c = t_counts.get(rt, 0)
                
                # Penalty for test being zero
                if t_c < min_positives_test:
                    rare_cost += 50 
                
                # Deviation from ratio logic for types? 
                # Ideally type distribution approx equals file distribution?
                # Spec: "consider difference in totals between splits"
                # A balanced split would have approx dev_ratio of the types in dev.
                total_t = d_c + t_c
                if total_t > 0:
                   type_ratio = d_c / total_t
                   rare_cost += abs(type_ratio - dev_ratio) * 10 # slightly less weight than main ratio
                    
            return ratio_cost + rare_cost

        # Try Dev
        new_d_counts = dev_type_counts.copy()
        for t, c in stats.items():
            if t in allowed_types: new_d_counts[t] += c
        cost_dev = calculate_cost(dev_recs + rec_c, test_recs, new_d_counts, test_type_counts)
        
        # Try Test
        new_t_counts = test_type_counts.copy()
        for t, c in stats.items():
            if t in allowed_types: new_t_counts[t] += c
        cost_test = calculate_cost(dev_recs, test_recs + rec_c, dev_type_counts, new_t_counts)
        
        if cost_dev <= cost_test:
            dev_files.append(fid)
            dev_recs += rec_c
            dev_type_counts = new_d_counts
        else:
            test_files.append(fid)
            test_recs += rec_c
            test_type_counts = new_t_counts

    # 4. Repair step
    # "For each rare type: test_count >= min_positives_test (if possible)"
    # "If not satisfied, attempt a local repair: swap one file from dev to test"
    
    warnings = []
    
    for rt in rare_types:
        if test_type_counts[rt] < min_positives_test:
            # Need to find a file in dev that has this type and swap it to test
            # Candidates: files in dev having rt > 0
            candidates = []
            for fid in dev_files:
                if file_stats[fid].get(rt, 0) > 0:
                    candidates.append(fid)
            
            if not candidates:
                warnings.append(f"Cannot satisfy min_positives for {rt} (no available file in dev or type not present globally)")
                continue
                
            # "choosing the smallest file that fixes it with minimal ratio disruption"
            # Since we just want to fix the "missing" status, any file with > 0 works.
            # Smallest file by record count is best to preserve ratio.
            candidates.sort(key=lambda f: file_stats[f]["_record_count"])
            
            best_cand = candidates[0]
            
            # Swap
            dev_files.remove(best_cand)
            test_files.append(best_cand)
            
            # Update counts (approximate, we don't fully recalc everything loop requires, just this once)
            # Actually we should update counts to reflect the swap for subsequent checks
            cand_stats = file_stats[best_cand]
            test_recs += cand_stats["_record_count"]
            dev_recs -= cand_stats["_record_count"]
            for t, c in cand_stats.items():
                if t in allowed_types:
                    test_type_counts[t] += c
                    dev_type_counts[t] -= c
            
            if test_type_counts[rt] >= min_positives_test:
                 logger.info(f"Repaired split by swapping {best_cand} to test for rare type {rt}")
            else:
                 warnings.append(f"Attempted repair for {rt} with {best_cand} but still insufficient counts")

    return dev_files, test_files, warnings

def main():
    args = parse_args()
    
    # 1. Setup Types
    if args.allowed_types:
        allowed_types = set(t.strip() for t in args.allowed_types.split(","))
    else:
        allowed_types = set(DEFAULT_ALLOWED_TYPES)
        
    if args.rare_types:
        rare_types = set(t.strip() for t in args.rare_types.split(","))
    else:
        rare_types = set(DEFAULT_RARE_TYPES)
        # Filter rare types to valid ones
        rare_types = {t for t in rare_types if t in allowed_types}

    # 2. Load Data
    logger.info(f"Loading {args.input_file}...")
    file_groups, total_records, parse_errors = load_and_group_data(args.input_file, args.file_key, allowed_types)
    
    if parse_errors:
        logger.warning(f"Found {len(parse_errors)} parse errors. First 5:")
        for e in parse_errors[:5]:
            logger.warning(f"  {e}")
            
    file_ids = list(file_groups.keys())
    if not file_ids:
        logger.error("No valid files found.")
        if parse_errors:
            logger.info("Hint: Your IDs might not match the default regex pattern '^(?:FILE=)?([^/]+)'.")
            logger.info("      Try using --file-key to specify a matching regex.")
        sys.exit(1)
        
    file_stats = get_file_stats(file_groups, allowed_types)
    
    # Check if unsatisfiable (e.g. total records < 2)
    if len(file_ids) < 2 and args.mode == "stratified":
        logger.warning("Only 1 file found. Cannot split strictly.")
    
    # 3. Split
    split_warnings = []
    if args.mode == "random":
        dev_files, test_files = solve_random_split(
            file_ids, file_stats, total_records, args.dev_ratio, args.seed
        )
    else:
        dev_files, test_files, split_warnings = solve_stratified_split(
            file_ids, file_stats, allowed_types, rare_types, 
            args.min_positives_test, args.dev_ratio, total_records, args.seed
        )

    # 4. Generate Report Stats
    def get_split_stats(files, stats_map):
        c = collections.defaultdict(int)
        rec_count = 0
        for f in files:
            rec_count += stats_map[f]["_record_count"]
            for t, val in stats_map[f].items():
                if t != "_record_count":
                    c[t] += val
        return c, rec_count

    dev_counts, dev_recs = get_split_stats(dev_files, file_stats)
    test_counts, test_recs = get_split_stats(test_files, file_stats)
    
    # Verify constraints for reporting
    rare_coverage = {}
    for rt in rare_types:
        has_min = test_counts.get(rt, 0) >= args.min_positives_test
        rare_coverage[rt] = has_min
        if not has_min:
             msg = f"Rare type {rt} has {test_counts.get(rt,0)} occurrences in test (min {args.min_positives_test})"
             if msg not in split_warnings: # Avoid double reporting if repair logged it
                 split_warnings.append(msg)
                 
    # 5. Output
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
        
    # Write files
    def write_list(fname, data):
        with open(os.path.join(args.output_dir, fname), 'w') as f:
            for item in data:
                f.write(f"{item}\n")
                
    if args.write in ["files", "both"]:
        write_list("dev_files.txt", dev_files)
        write_list("test_files.txt", test_files)
        
    if args.write in ["ids", "both"]:
        dev_ids = []
        for f in dev_files:
            dev_ids.extend(r["id"] for r in file_groups[f])
        test_ids = []
        for f in test_files:
            test_ids.extend(r["id"] for r in file_groups[f])
            
        write_list("dev_ids.txt", dev_ids)
        write_list("test_ids.txt", test_ids)
        
    # Report JSON
    report = {
        "meta": {
            "seed": args.seed,
            "mode": args.mode,
            "dev_ratio": args.dev_ratio,
            "total_files": len(file_ids),
            "total_records": total_records
        },
        "splits": {
            "dev": {
                "files": len(dev_files),
                "records": dev_recs,
                "counts": dev_counts
            },
            "test": {
                "files": len(test_files),
                "records": test_recs,
                "counts": test_counts,
                "rare_coverage": rare_coverage
            }
        },
        "warnings": split_warnings + parse_errors
    }
    
    with open(os.path.join(args.output_dir, "split_report.json"), 'w') as f:
        json.dump(report, f, indent=2)
        
    # Stderr Summary
    sys.stderr.write("Split Summary:\n")
    sys.stderr.write(f"  Dev:  {len(dev_files)} files, {dev_recs} records\n")
    sys.stderr.write(f"  Test: {len(test_files)} files, {test_recs} records\n")
    sys.stderr.write("  Rare Types in Test:\n")
    for rt in rare_types:
        status = "OK" if rare_coverage[rt] else "MISSING"
        sys.stderr.write(f"    {rt}: {test_counts.get(rt, 0)} ({status})\n")
    
    if split_warnings:
        sys.stderr.write("\nWARNINGS:\n")
        for w in split_warnings:
             sys.stderr.write(f"  - {w}\n")
             
    if split_warnings and any("Cannot satisfy" in w for w in split_warnings):
        sys.exit(1)
        
    sys.exit(0)

if __name__ == "__main__":
    main()
