#!/usr/bin/env python3
import argparse
import json
import random
import sys
import math
import gzip
from collections import defaultdict, Counter
from typing import Dict, List, Set, Any, Optional

# --- Constants & Families ---

def normalize_family(producer: Optional[str], creator: Optional[str]) -> str:
    # Combine and lower-case for robust matching
    combined = ((producer or "") + " " + (creator or "")).lower()
    
    if not combined.strip():
        return "UNKNOWN"
        
    if "acrobat" in combined or "distiller" in combined or "adobe" in combined or "pdf library" in combined:
        return "ACROBAT"
    if "word" in combined or "microsoft" in combined or "office" in combined:
        return "WORD"
    if "indesign" in combined:
        return "INDESIGN"
    if "scan" in combined or "canon" in combined or "epson" in combined or "fujitsu" in combined or "image capture" in combined:
        return "SCANNER"
        
    return "OTHER"

def compute_page_bucket(page_count: int, buckets_def: List[Any]) -> str:
    if page_count is None:
        return "unknown"
        
    # buckets_def is expected to be a list of parsed definitions
    # But since we need to match the specific CLI format "1,2-5,6-20,21+" 
    # Let's logic it out simply based on the user request's example structure flexibility
    # For now, hardcode the parsing logic to map checking against the passed definitions.
    
    # Actually, let's implement the parsing of the string argument in main, 
    # and here we expect 'buckets_def' to be a list of functions or ranges.
    # To keep this function pure and simple with the string labels:
    
    # We will assume buckets_def is a list of tuples: (label, check_fn)
    for label, check_fn in buckets_def:
        if check_fn(page_count):
            return label
            
    return "other"

# --- Main Logic ---

def parse_page_buckets(bucket_str: str):
    """Parses '1,2-5,6-20,21+' into a list of (label, lambda n: bool)."""
    defs = []
    parts = bucket_str.split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                # Inclusive range
                defs.append((part, lambda n, s=start, e=end: s <= n <= e))
            except ValueError:
                pass # Invalid format ignored
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

def main():
    parser = argparse.ArgumentParser(description="Sample candidate PDFs from corpus index.")
    parser.add_argument("--index", required=True, help="Path to JSONL index")
    parser.add_argument("--out", required=True, help="Output file for selected candidates")
    parser.add_argument("--report", required=True, help="JSON report path")
    parser.add_argument("--n", type=int, required=True, help="Total number of candidates to select")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    parser.add_argument("--prefer-textpdf", action="store_true", help="Prefer non-scanned text PDFs")
    parser.add_argument("--scanned-share", type=float, default=0.05, help="Target share of scanned docs (0.0 to 1.0)")
    parser.add_argument("--page-buckets", default="1,2-5,6-20,21+", help="Page count bucket definitions")
    parser.add_argument("--size-buckets", default="tiny,normal,huge", help="Comma-separated size buckets to include")
    parser.add_argument("--output-field", default="path", choices=["path", "pdf_id"], help="Field to output per line")
    parser.add_argument("--min-pages", type=int, default=1, help="Minimum pages")
    parser.add_argument("--max-pages", type=int, default=0, help="Maximum pages (0 for no limit)")
    parser.add_argument("--exclude-file", help="Path to file with paths/ids to exclude")
    parser.add_argument("--allow-duplicates", action="store_true", help="Allow sampling the same doc twice (default false)")

    args = parser.parse_args()

    # 1. Setup Randomness
    rng = random.Random(args.seed)

    # 2. Parse Configs
    page_bucket_defs = parse_page_buckets(args.page_buckets)
    allowed_size_buckets = set(s.strip() for s in args.size_buckets.split(','))
    
    exclude_set = set()
    if args.exclude_file:
        try:
            with open(args.exclude_file, 'r') as f:
                for line in f:
                    clean = line.strip()
                    if clean:
                        exclude_set.add(clean)
        except Exception as e:
            print(f"Warning: Could not read exclude file: {e}", file=sys.stderr)

    # 3. Load and Stratify
    # We need to hold candidates in memory to sample from them. 
    # Structure: buckets[scanned_bool][bucket_key] -> list of records
    # bucket_key = (size, page_range, family)
    
    # We split mainly by scanned vs text because of the quota requirement.
    # text_buckets = { key -> [records] }
    # scanned_buckets = { key -> [records] }
    
    text_pool = defaultdict(list)
    scanned_pool = defaultdict(list)
    
    # Stats for report
    stats = {
        "n_requested": args.n,
        "n_selected": 0,
        "seed": args.seed,
        "filters": vars(args),
        "total_seen": 0,
        "total_kept": 0,
        "by_family": Counter(),
        "by_size": Counter(),
        "by_page": Counter(),
        "by_scanned": Counter(),
    }
    
    try:
        open_func = gzip.open if args.index.endswith('.gz') else open
        
        seen_ids = set()
        
        with open_func(args.index, 'rt') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                    
                stats["total_seen"] += 1
                
                # --- Filtering ---
                path = rec.get("path")
                pdf_id = rec.get("pdf_id")
                
                if not path or not rec.get("bytes"):
                    continue
                    
                # Exclude check (check both path and id if available)
                if path in exclude_set or (pdf_id and pdf_id in exclude_set):
                    continue
                    
                # Deduplication
                if not args.allow_duplicates and pdf_id:
                    if pdf_id in seen_ids:
                        continue
                    seen_ids.add(pdf_id)
                    
                page_count = rec.get("page_count")
                if page_count is None:
                    continue
                    
                if page_count < args.min_pages:
                    continue
                if args.max_pages > 0 and page_count > args.max_pages:
                    continue
                
                size_bucket = rec.get("size_bucket", "unknown")
                if size_bucket not in allowed_size_buckets:
                    continue

                # --- Categorization ---
                
                page_bucket = compute_page_bucket(page_count, page_bucket_defs)
                family = normalize_family(rec.get("producer"), rec.get("creator"))
                is_scanned = rec.get("likely_scanned", False)
                has_text = rec.get("has_text_ops", False)
                
                # "TextPDF-like" definition from requirements:
                # prefer-textpdf: prefer (likely_scanned == false AND has_text_ops == true)
                # So we separate into "Quota A" (Text) and "Quota B" (Scanned/Other)
                
                # Definition of the two main pools for quota:
                # Pool A (Text): likely_scanned == False AND has_text_ops == True
                # Pool B (Scanned): likely_scanned == True (regardless of text ops)
                # what about likely_scanned==False but has_text_ops==False? (Blank/Vector only?)
                # Requirement strictly says:
                # "allocate (1 - scanned_share) ... to likely_scanned == false AND has_text_ops == true"
                # "allocate scanned_share to likely_scanned == true"
                
                # Items that are neither (e.g. valid digital PDF with no text, like pure vector drawings)
                # strictly fall out of the priority quotas if we follow instructions literally.
                # However, usually we treat "non-scanned" as the main pool.
                # Let's group "Digital No Text" into the Text pool but maybe they just won't be prioritized?
                # Actually, strictly following:
                # If args.prefer_textpdf is ON:
                #   Target Text Count = (1 - scanned_share) * N
                #   Target Scanned Count = scanned_share * N
                
                is_target_text = (not is_scanned) and has_text
                is_target_scanned = is_scanned
                
                # If prefer-textpdf is OFF, we might just sample uniformly? 
                # The user requirement says "If --prefer-textpdf: ... allocate ...".
                # Implies if NOT set, we just ignore that distinction and sample from everything? 
                # Or maybe we still respect stratification but don't force the split.
                # Let's assume if prefer-textpdf is NOT set, we treat all valid files as one big pool
                # stratified by the other keys.
                
                bucket_key = (size_bucket, page_bucket, family)
                
                if args.prefer_textpdf:
                    if is_target_scanned:
                        scanned_pool[bucket_key].append(rec)
                    elif is_target_text:
                        text_pool[bucket_key].append(rec)
                    else:
                        # Fallback: Digital non-text docs. 
                        # Where do they go? 
                        # If we strictly valid "prefer-textpdf", maybe we just don't pick them unless we run out?
                        # Let's add them to text_pool for now but maybe we can filter them if we want strictly text.
                        # Given "prefer (likely_scanned == false AND has_text_ops == true)", 
                        # it implies we strongly want text.
                        # Let's put them in text_pool but maybe they are less desired?
                        # For simplicity, let's exclude them from the "Text" quota pool if they don't have text,
                        # UNLESS the user just meant "Digital PDFs".
                        # "has_text_ops == true" is specific.
                        # I will DROP them for now if they don't meet the criteria, to be safe, 
                        # or keep them as 'other'.
                        # Let's keep them in text_pool to ensure we have candidates if needed.
                        pass 
                else:
                    # Single pool mode
                    text_pool[bucket_key].append(rec)

                stats["total_kept"] += 1
                stats["by_family"][family] += 1
                stats["by_size"][size_bucket] += 1
                stats["by_page"][page_bucket] += 1
                stats["by_scanned"][str(is_scanned)] += 1

    except FileNotFoundError:
        print(f"Error: Index file {args.index} not found.")
        sys.exit(1)

    # 4. Allocate Quotas
    
    targets = {}
    if args.prefer_textpdf:
        n_scanned = int(args.n * args.scanned_share)
        n_text = args.n - n_scanned
        targets['scanned'] = n_scanned
        targets['text'] = n_text
        pools = {'scanned': scanned_pool, 'text': text_pool}
    else:
        targets['all'] = args.n
        pools = {'all': text_pool} # text_pool holds everything here

    selected_records = []
    
    bucket_counts_log = {}

    for pool_name, pool_n in targets.items():
        current_pool = pools[pool_name]
        
        # Flatten available keys
        available_keys = list(current_pool.keys())
        if not available_keys:
            continue
            
        # Strategy: Proportional allocation? Or Uniform across buckets?
        # User constraint: "Ensure each non-empty bucket gets at least 1 sample"
        # "Allocate --n across buckets proportionally"
        
        # Total items in this pool
        total_items = sum(len(v) for v in current_pool.values())
        if total_items == 0:
            continue
            
        # Initial allocation (minimum 1)
        final_allocs = {}
        remaining_n = pool_n
        
        # 1. Minimum 1 per bucket
        for k in available_keys:
            final_allocs[k] = 1
            remaining_n -= 1
        
        if remaining_n < 0:
            # We have more buckets than N. We must drop some.
            # Sample N buckets to keep.
            keys_to_keep = rng.sample(available_keys, pool_n)
            final_allocs = {k: 1 for k in keys_to_keep}
            
            # Since we only keep subset, the rest are effectively 0
            # But we only iterate final_allocs later so that is fine.
            remaining_n = 0
            
        elif remaining_n > 0:
            # Proportional distribution for the rest
            
            # Step A: Calculate ideal float numbers based on PROPORTION OF TOTAL
            # But we must respect the 1 we already gave.
            # Actually, standard proportional allocation:
            # Ideal = (count / total) * pool_n
            # But we must ensure >= 1.
            
            raw_allocs = {k: (len(v) / total_items) * pool_n for k, v in current_pool.items()}
            
            # Use raw_allocs as base but ensure at least 1?
            # Or just add remaining_n proportionally?
            
            # The previous logic was executing Step A/B/C cleanly.
            # Let's rebuild final_allocs from scratch using the prop logic
            # but ensuring min(1).
            
            # Reset final_allocs to be the proportional ones, with min 1 limit
            # This is slightly different from "give 1 to everyone then add".
            # "Give 1 to everyone then add" favors small buckets more (coverage).
            # "Proportional then min 1" favors large buckets more but might overshoot N if many small buckets.
            
            # Let's stick to the "cover then add" approach if we want good coverage of all buckets.
            # But the 'remaining_n > 0' branch was entered because we already gave 1 to everyone
            # and still have budget.
            
            # So let's allocate the *remaining* budget based on proportions.
            # Or just use the prop logic from scratch and fix sum.
            
            # Let's use the explicit prop logic I wrote before, but ensure variables match.
            
            # Calculate raw targets
            raw_targets = {k: (len(v) / total_items) * pool_n for k, v in current_pool.items()}
            
            # Enforce min 1 and integer
            target_allocs = {k: max(1, round(v)) for k, v in raw_targets.items()}
            
            # Check sum
            current_sum = sum(target_allocs.values())
            diff = pool_n - current_sum
            
            # Fix diff
            if diff > 0:
                # Add to largest buckets
                sorted_keys = sorted(available_keys, key=lambda k: len(current_pool[k]), reverse=True)
                for i in range(diff):
                    k = sorted_keys[i % len(sorted_keys)]
                    if target_allocs[k] < len(current_pool[k]):
                        target_allocs[k] += 1
            elif diff < 0:
                # Remove from largest allocs (that are > 1)
                to_remove = -diff
                while to_remove > 0:
                     dandies = [k for k in target_allocs if target_allocs[k] > 1]
                     if not dandies: break
                     dandies.sort(key=lambda k: target_allocs[k], reverse=True)
                     target_allocs[dandies[0]] -= 1
                     to_remove -= 1
            
            final_allocs = target_allocs

        # Final pass: safety check against actual availability
        # (It is possible we allocated more than exist if pool_n > total_items)
        # But we handle pool_n > total_items by capping.
        
        real_total_selected = 0
        for k in final_allocs:
            available_list = current_pool[k]
            count = min(final_allocs[k], len(available_list))
            
            # Sample
            sampled = rng.sample(available_list, count)
            selected_records.extend(sampled)
            real_total_selected += count
            
            # Log bucket stat
            bk_str = f"{k[0]}|{k[1]}|{k[2]}|{pool_name=='scanned'}" 
            bucket_counts_log[bk_str] = {
                "available": len(available_list),
                "selected": count
            }
            
    # 5. Output
    
    # Shuffle final list to mix families/types
    rng.shuffle(selected_records)
    
    # Write list
    with open(args.out, 'w') as f:
        for rec in selected_records:
            val = rec.get(args.output_field)
            if val:
                f.write(str(val) + "\n")
                
    # Write report
    stats["n_selected"] = len(selected_records)
    stats["bucket_counts"] = bucket_counts_log
    
    # Compute marginals for selected
    sel_fam = Counter()
    sel_size = Counter()
    sel_page = Counter()
    sel_scan = Counter()
    
    for r in selected_records:
        fam = normalize_family(r.get("producer"), r.get("creator"))
        sz = r.get("size_bucket", "unknown")
        pg_c = r.get("page_count")
        pg = compute_page_bucket(pg_c, page_bucket_defs)
        sc = r.get("likely_scanned", False)
        
        sel_fam[fam] += 1
        sel_size[sz] += 1
        sel_page[pg] += 1
        sel_scan[str(sc)] += 1
        
    stats["marginals"] = {
        "producer_family": dict(sel_fam),
        "size_bucket": dict(sel_size),
        "page_bucket": dict(sel_page),
        "likely_scanned": dict(sel_scan)
    }

    with open(args.report, 'w') as f:
        json.dump(stats, f, indent=2)

    print(f"Sampled {len(selected_records)} candidates to {args.out}")
    print(f"Report written to {args.report}")

if __name__ == "__main__":
    main()
