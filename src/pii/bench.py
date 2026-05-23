from __future__ import annotations

import json
import logging
import os
import pathlib
import random
import sys
import time
from typing import Dict, List

from .pipeline import detect_pii

logger = logging.getLogger(__name__)


def calculate_quantiles(values: List[float]) -> Dict[str, float]:
    if not values:
        return {k: 0.0 for k in ['p50', 'p90', 'p95', 'p99', 'mean', 'min', 'max']}

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    import math

    def get_p(p):
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_vals[int(k)]
        d0 = sorted_vals[int(f)] * (c - k)
        d1 = sorted_vals[int(c)] * (k - f)
        return d0 + d1

    return {
        'p50': get_p(0.50),
        'p90': get_p(0.90),
        'p95': get_p(0.95),
        'p99': get_p(0.99),
        'mean': sum(values) / n,
        'min': sorted_vals[0],
        'max': sorted_vals[-1]
    }


def run_bench(args, models):
    detectors = set(args.detectors.lower().split(","))

    # Gather files
    files = []
    if os.path.isdir(args.bench):
        p = pathlib.Path(args.bench)
        files = [str(f) for f in p.rglob(args.bench_glob)]
        files.sort()  # standard order before shuffle
    elif os.path.isfile(args.bench):
        files = [args.bench]
    else:
        logger.error(f"Benchmark path not found: {args.bench}")
        sys.exit(1)

    if not files:
        logger.error("No files found to benchmark.")
        sys.exit(1)

    if args.bench_shuffle:
        random.seed(args.bench_seed)
        random.shuffle(files)

    if args.bench_max_pages > 0:
        files = files[:args.bench_max_pages]

    total_runs = args.bench_runs
    warmup_count = args.bench_warmup

    all_timings = []
    per_file_stats = []  # tuple (filename, chars, ent_count, total_ms, breakdown)

    global_idx = 0
    t_wall_start = time.perf_counter()

    processed_count = 0
    errors = 0

    for run_i in range(total_runs):
        for fpath in files:
            is_warmup = global_idx < warmup_count
            global_idx += 1

            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    t_read_start = time.perf_counter()
                    text = f.read()
                    t_read_end = time.perf_counter()
            except Exception as e:
                logger.error(f"Failed to read {fpath}: {e}")
                errors += 1
                continue

            read_ms = (t_read_end - t_read_start) * 1000

            # Record total time including read
            t_page_start = time.perf_counter()

            ents, stats = detect_pii(text, models, args.min_score, detectors=detectors)

            t_page_end = time.perf_counter()
            total_ms = (t_page_end - t_page_start) * 1000 + read_ms

            if not is_warmup:
                processed_count += 1
                # full record
                record = {
                    'read_ms': read_ms,
                    'normalize_ms': stats['normalize_ms'],
                    'ner_ms': stats['ner_ms'],
                    'regex_ms': stats['regex_ms'],
                    'merge_ms': stats['merge_ms'],
                    'total_ms': total_ms,
                    'chars': len(text),
                    'entities': len(ents)
                }
                all_timings.append(record)

                if args.bench_profile:
                    per_file_stats.append({
                        'filename': os.path.basename(fpath),
                        'chars': len(text),
                        'entities': len(ents),
                        'total_ms': total_ms,
                        'stages': record
                    })

    t_wall_end = time.perf_counter()
    total_wall_ms = (t_wall_end - t_wall_start) * 1000

    if processed_count == 0:
        if errors > 0:
            logger.error("All files failed to process.")
        else:
            logger.error("No pages processed (check warmup vs count?).")
        sys.exit(1)

    # Aggregate
    agg_stages = {}
    stage_keys = ['read_ms', 'normalize_ms', 'ner_ms', 'regex_ms', 'merge_ms', 'total_ms']

    for key in stage_keys:
        vals = [r[key] for r in all_timings]
        agg_stages[key] = calculate_quantiles(vals)

    throughput = processed_count / (total_wall_ms / 1000.0) if total_wall_ms > 0 else 0

    result = {
        "meta": {
            "path": args.bench,
            "runs": args.bench_runs,
            "warmup": args.bench_warmup,
            "pages": processed_count,
            "profile": args.bench_profile,
            "model_profile": args.models,
            "language": args.language
        },
        "throughput": {
            "pages_per_sec": round(throughput, 2),
            "wall_ms": round(total_wall_ms, 1)
        },
        "stages": agg_stages
    }

    if args.bench_json:
        if args.bench_profile:
            result['profile'] = per_file_stats
        print(json.dumps(result, indent=2))
    else:
        # Readable summary to stderr
        print(f"Benchmark Summary:", file=sys.stderr)
        print(f"  Files: {len(files)}", file=sys.stderr)
        print(f"  Pages Processed: {processed_count}", file=sys.stderr)
        print(f"  Wall Time: {round(total_wall_ms, 2)} ms", file=sys.stderr)
        print(f"  Throughput: {round(throughput, 2)} pages/sec", file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f"Stage Breakdown (ms):", file=sys.stderr)

        headers = ["Stage", "p50", "p95", "Mean", "Min", "Max"]
        print(f"{headers[0]:<12} {headers[1]:<8} {headers[2]:<8} {headers[3]:<8} {headers[4]:<8} {headers[5]:<8}",
              file=sys.stderr)
        print("-" * 60, file=sys.stderr)

        for stage in stage_keys:
            s = agg_stages[stage]
            print(f"{stage:<12} {s['p50']:<8.2f} {s['p95']:<8.2f} {s['mean']:<8.2f} {s['min']:<8.2f} {s['max']:<8.2f}",
                  file=sys.stderr)

        if args.bench_profile:
            print(f"\nPer-File Profile:", file=sys.stderr)
            print(f"{'Filename':<30} {'Len':<8} {'Ents':<6} {'Total(ms)':<10}", file=sys.stderr)
            for item in per_file_stats:
                print(f"{item['filename']:<30} {item['chars']:<8} {item['entities']:<6} {item['total_ms']:<10.2f}",
                      file=sys.stderr)
