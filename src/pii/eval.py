from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from typing import Dict, List, Optional

from .consts import ADDRESS_GROUP_MAX_GAP, ADDRESS_GROUP_MAX_SPAN
from .pipeline import detect_pii, detect_pii_gateway

logger = logging.getLogger(__name__)


def load_gold_corrections(path: Optional[str]) -> dict:
    """Load gold standard corrections file."""
    if not path or not isinstance(path, str) or not os.path.exists(path):
        return {"remove_entities": []}
    with open(path) as f:
        return json.load(f)


def apply_gold_corrections(record: dict, corrections: dict) -> dict:
    """Apply corrections to a gold record by removing mislabeled entities."""
    rid = record.get('id', '')
    remove_set = {
        (c['id'], c['type'], c['start'], c['end'])
        for c in corrections.get('remove_entities', [])
    }

    corrected_entities = [
        e for e in record.get('entities', [])
        if (rid, e['type'], e['start'], e['end']) not in remove_set
    ]

    return {**record, 'entities': corrected_entities}


# --- Evaluation Logic ---

def match_entities(
        gold_ents: List[Dict],
        pred_ents: List[Dict],
        match_mode: str,
        overlap_min: int,
        type_name: Optional[str] = None
) -> tuple[list, list, list]:
    """
    Match gold and pred entities one-to-one based on criteria.
    Returns (matches, unmatched_gold, unmatched_pred).
    """
    # 1. Build candidates
    candidates = []

    for g_idx, g in enumerate(gold_ents):
        for p_idx, p in enumerate(pred_ents):
            # Check match
            is_match = False
            score = 0

            g_start, g_end = g['start'], g['end']
            p_start, p_end = p['start'], p['end']

            if match_mode == 'exact':
                if g_start == p_start and g_end == p_end:
                    is_match = True
                    score = 1e9  # Very large
            elif match_mode == 'overlap':
                # Intersection
                inter_start = max(g_start, p_start)
                inter_end = min(g_end, p_end)
                overlap_len = max(0, inter_end - inter_start)

                if overlap_len >= overlap_min:
                    is_match = True
                    score = overlap_len

            if is_match:
                # Tie-breakers: gold length, then earlier start
                g_len = g_end - g_start
                candidates.append({
                    'g_idx': g_idx,
                    'p_idx': p_idx,
                    'score': score,
                    'g_len': g_len,
                    'start_neg': -g_start
                })

    # 2. Sort candidates
    candidates.sort(key=lambda x: (x['score'], x['g_len'], x['start_neg']), reverse=True)

    # 3. Greedy assignment
    matched_g = set()
    matched_p = set()
    matches = []
    matched_pairs = []

    for c in candidates:
        if c['g_idx'] not in matched_g and c['p_idx'] not in matched_p:
            matched_g.add(c['g_idx'])
            matched_p.add(c['p_idx'])
            matches.append((gold_ents[c['g_idx']], pred_ents[c['p_idx']]))
            matched_pairs.append((c['g_idx'], c['p_idx']))

    # Allow one ADDRESS prediction to match multiple gold ADDRESS spans (within limits)
    if type_name == 'ADDRESS' and match_mode == 'overlap' and matched_pairs:
        unmatched_gold_idx = [i for i in range(len(gold_ents)) if i not in matched_g]
        if unmatched_gold_idx:
            for g_idx, p_idx in matched_pairs:
                pred = pred_ents[p_idx]
                pred_len = pred['end'] - pred['start']
                if pred_len > ADDRESS_GROUP_MAX_SPAN:
                    continue

                # Collect gold spans overlapping this prediction
                overlapping = []
                for i in unmatched_gold_idx:
                    g = gold_ents[i]
                    inter_start = max(g['start'], pred['start'])
                    inter_end = min(g['end'], pred['end'])
                    if max(0, inter_end - inter_start) >= overlap_min:
                        overlapping.append(i)

                if not overlapping:
                    continue

                # Build ordered list of all overlapping golds including the primary matched gold
                overlapping.append(g_idx)
                overlapping = sorted(set(overlapping), key=lambda i: gold_ents[i]['start'])

                # Find group around the primary matched gold with gap/span constraints
                primary_pos = overlapping.index(g_idx)
                group_start = group_end = primary_pos

                # Expand left
                while group_start - 1 >= 0:
                    left_idx = overlapping[group_start - 1]
                    cur_idx = overlapping[group_start]
                    gap = gold_ents[cur_idx]['start'] - gold_ents[left_idx]['end']
                    span = gold_ents[overlapping[group_end]]['end'] - gold_ents[left_idx]['start']
                    if gap <= ADDRESS_GROUP_MAX_GAP and span <= ADDRESS_GROUP_MAX_SPAN:
                        group_start -= 1
                    else:
                        break

                # Expand right
                while group_end + 1 < len(overlapping):
                    right_idx = overlapping[group_end + 1]
                    cur_idx = overlapping[group_end]
                    gap = gold_ents[right_idx]['start'] - gold_ents[cur_idx]['end']
                    span = gold_ents[right_idx]['end'] - gold_ents[overlapping[group_start]]['start']
                    if gap <= ADDRESS_GROUP_MAX_GAP and span <= ADDRESS_GROUP_MAX_SPAN:
                        group_end += 1
                    else:
                        break

                # Match any golds in the group that are still unmatched
                for i in overlapping[group_start:group_end + 1]:
                    if i in matched_g:
                        continue
                    matched_g.add(i)
                    matches.append((gold_ents[i], pred))

    # Unmatched
    unmatched_gold = [g for i, g in enumerate(gold_ents) if i not in matched_g]
    unmatched_pred = [p for i, p in enumerate(pred_ents) if i not in matched_p]

    return matches, unmatched_gold, unmatched_pred


def get_match_mode_for_type(type_name: str, mode_setting: str) -> str:
    if mode_setting == 'exact':
        return 'exact'
    if mode_setting == 'overlap':
        return 'overlap'
    # Hybrid: use exact only for SSN and ACCOUNT_NUMBER (fixed formats)
    # Use overlap for BIRTHDATE and PHONE_NUMBER (variable formats with boundary issues)
    if type_name in ['SSN', 'ACCOUNT_NUMBER']:
        return 'exact'
    return 'overlap'


# --- Miss Categorization Helpers ---

def compute_char_overlap(ent1: dict, ent2: dict) -> int:
    """Compute character overlap between two entities."""
    start = max(ent1['start'], ent2['start'])
    end = min(ent1['end'], ent2['end'])
    return max(0, end - start)


def find_nearest_pred(gold_ent: dict, all_preds: list) -> dict:
    """Find the nearest prediction to a gold entity."""
    g_start, g_end = gold_ent['start'], gold_ent['end']
    nearest = None
    min_dist = float('inf')

    for p in all_preds:
        # Distance is 0 if overlapping, else gap between spans
        if p['end'] <= g_start:
            dist = g_start - p['end']
        elif p['start'] >= g_end:
            dist = p['start'] - g_end
        else:
            dist = 0  # overlapping

        if dist < min_dist:
            min_dist = dist
            nearest = p

    if nearest:
        return {'pred': nearest, 'distance': min_dist}
    return None


def categorize_miss(gold_ent: dict, all_preds_by_type: dict, all_preds_flat: list,
                    match_mode: str, overlap_min: int, proximity_threshold: int = 50) -> dict:
    """
    Categorize why a gold entity was missed.

    Categories:
    - no_prediction: No prediction anywhere near the gold entity
    - wrong_type: A prediction overlaps but has different type
    - partial_overlap: Prediction overlaps but didn't meet match threshold
    - boundary_mismatch: Correct type, overlap, but boundaries don't align (exact mode)

    Returns: {category: str, details: dict}
    """
    g_start, g_end = gold_ent['start'], gold_ent['end']
    g_type = gold_ent['type']

    # Check for wrong_type predictions (any type that overlaps)
    for pred_type, preds in all_preds_by_type.items():
        if pred_type == g_type:
            continue
        for p in preds:
            overlap = compute_char_overlap(p, gold_ent)
            if overlap > 0:
                return {
                    'category': 'wrong_type',
                    'details': {
                        'pred': p,
                        'predicted_type': pred_type,
                        'overlap_chars': overlap
                    }
                }

    # Check for partial_overlap or boundary_mismatch with correct type
    same_type_preds = all_preds_by_type.get(g_type, [])
    for p in same_type_preds:
        overlap = compute_char_overlap(p, gold_ent)
        if overlap > 0:
            if match_mode == 'exact':
                # Has overlap but not exact match
                return {
                    'category': 'boundary_mismatch',
                    'details': {
                        'pred': p,
                        'gold_span': (g_start, g_end),
                        'pred_span': (p['start'], p['end']),
                        'overlap_chars': overlap
                    }
                }
            elif overlap < overlap_min:
                # Overlap mode but below threshold
                return {
                    'category': 'partial_overlap',
                    'details': {
                        'pred': p,
                        'overlap_chars': overlap,
                        'required': overlap_min
                    }
                }

    # Check proximity (any prediction within threshold)
    nearest = find_nearest_pred(gold_ent, all_preds_flat)
    if nearest and nearest['distance'] <= proximity_threshold and nearest['distance'] > 0:
        return {
            'category': 'near_miss',
            'details': {
                'pred': nearest['pred'],
                'distance': nearest['distance']
            }
        }

    # No prediction anywhere near
    return {'category': 'no_prediction', 'details': {}}


def bucket_entity_length(length: int) -> str:
    """Bucket entity length for statistics."""
    if length <= 3:
        return '1-3'
    elif length <= 10:
        return '4-10'
    elif length <= 20:
        return '11-20'
    else:
        return '21+'


def generate_html_report(report_data: dict, output_path: str):
    """Generate an HTML report for detailed miss analysis."""
    import html as html_module

    meta = report_data['meta']
    by_type = report_data['by_type']
    micro = report_data['micro']
    miss_stats = report_data['miss_stats']
    miss_examples = report_data['miss_examples']

    # Category colors
    cat_colors = {
        'no_prediction': '#ffcccc',
        'wrong_type': '#ffd699',
        'partial_overlap': '#ffffcc',
        'boundary_mismatch': '#cce5ff',
        'near_miss': '#e6ccff'
    }

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>PII Detection Evaluation Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; line-height: 1.5; }}
        h1 {{ color: #333; border-bottom: 2px solid #333; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        h3 {{ color: #666; }}
        table {{ border-collapse: collapse; margin: 15px 0; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f5f5f5; }}
        tr:nth-child(even) {{ background-color: #fafafa; }}
        .summary-box {{ background: #f0f7ff; padding: 15px; border-radius: 8px; margin: 20px 0; }}
        .category-no_prediction {{ background-color: {cat_colors['no_prediction']}; }}
        .category-wrong_type {{ background-color: {cat_colors['wrong_type']}; }}
        .category-partial_overlap {{ background-color: {cat_colors['partial_overlap']}; }}
        .category-boundary_mismatch {{ background-color: {cat_colors['boundary_mismatch']}; }}
        .category-near_miss {{ background-color: {cat_colors['near_miss']}; }}
        .context {{ font-family: monospace; font-size: 12px; background: #f5f5f5; padding: 5px; border-radius: 3px; }}
        .gold-text {{ background: #ffe0e0; padding: 2px 4px; border-radius: 2px; }}
        .pred-text {{ background: #e0ffe0; padding: 2px 4px; border-radius: 2px; }}
        details {{ margin: 10px 0; }}
        summary {{ cursor: pointer; font-weight: bold; }}
    </style>
</head>
<body>
    <h1>PII Detection Evaluation Report</h1>

    <div class="summary-box">
        <h2 style="margin-top: 0;">Executive Summary</h2>
        <p><strong>Gold File:</strong> {html_module.escape(str(meta.get('gold', 'N/A')))}</p>
        <p><strong>Records Evaluated:</strong> {meta.get('records', 0)}</p>
        <p><strong>Match Mode:</strong> {meta.get('match', 'N/A')}</p>
        <p><strong>Overall Metrics:</strong> Recall: {micro['recall']:.2%} | Precision: {micro['precision']:.2%} | F1: {micro['f1']:.4f}</p>
        <p><strong>Total Misses (FN):</strong> {micro['fn']}</p>
    </div>

    <details>
        <summary>Configuration</summary>
        <table>
            <tr><th>Setting</th><th>Value</th></tr>
            <tr><td>Models</td><td>{html_module.escape(str(meta.get('config', {}).get('models', 'N/A')))}</td></tr>
            <tr><td>Model Path</td><td>{html_module.escape(str(meta.get('config', {}).get('model_path', 'N/A')))}</td></tr>
            <tr><td>Detectors</td><td>{html_module.escape(str(meta.get('config', {}).get('detectors', 'N/A')))}</td></tr>
            <tr><td>Gateway</td><td>{html_module.escape(str(meta.get('config', {}).get('gateway', 'N/A')))}</td></tr>
            <tr><td>Types</td><td>{html_module.escape(str(meta.get('config', {}).get('types', 'N/A')))}</td></tr>
            <tr><td>Config File</td><td>{html_module.escape(str(meta.get('config', {}).get('config_file', 'N/A')))}</td></tr>
            <tr><td>Min Score</td><td>{meta.get('min_score', 0)}</td></tr>
        </table>
    </details>

    <h2>Miss Category Breakdown</h2>
    <table>
        <tr>
            <th>Category</th>
"""

    # Add type columns
    types = sorted(by_type.keys())
    for t in types:
        html += f"            <th>{html_module.escape(t)}</th>\n"
    html += "            <th>Total</th>\n        </tr>\n"

    # Add rows for each category
    categories = ['no_prediction', 'wrong_type', 'partial_overlap', 'boundary_mismatch', 'near_miss']
    for cat in categories:
        total = 0
        html += f"        <tr class='category-{cat}'>\n            <td>{cat.replace('_', ' ').title()}</td>\n"
        for t in types:
            count = miss_stats['by_category'].get(cat, {}).get(t, 0)
            total += count
            html += f"            <td>{count}</td>\n"
        html += f"            <td><strong>{total}</strong></td>\n        </tr>\n"

    html += "    </table>\n"

    # Per-type metrics table
    html += """
    <h2>Per-Type Metrics</h2>
    <table>
        <tr>
            <th>Type</th>
            <th>TP</th>
            <th>FN</th>
            <th>FP</th>
            <th>Recall</th>
            <th>Precision</th>
            <th>F1</th>
        </tr>
"""
    for t in types:
        res = by_type[t]
        html += f"""        <tr>
            <td>{html_module.escape(t)}</td>
            <td>{res['tp']}</td>
            <td>{res['fn']}</td>
            <td>{res['fp']}</td>
            <td>{res['recall']:.2%}</td>
            <td>{res['precision']:.2%}</td>
            <td>{res['f1']:.4f}</td>
        </tr>
"""
    html += "    </table>\n"

    # Entity length distribution
    html += """
    <h2>Entity Length Distribution of Misses</h2>
    <table>
        <tr>
            <th>Length Bucket</th>
"""
    for t in types:
        html += f"            <th>{html_module.escape(t)}</th>\n"
    html += "            <th>Total</th>\n        </tr>\n"

    for bucket in ['1-3', '4-10', '11-20', '21+']:
        total = 0
        html += f"        <tr>\n            <td>{bucket} chars</td>\n"
        for t in types:
            count = miss_stats['by_length'].get(bucket, {}).get(t, 0)
            total += count
            html += f"            <td>{count}</td>\n"
        html += f"            <td><strong>{total}</strong></td>\n        </tr>\n"

    html += "    </table>\n"

    # Common missed patterns
    html += "    <h2>Common Missed Patterns</h2>\n"
    for t in types:
        patterns = miss_stats['common_texts'].get(t, [])
        if patterns:
            html += f"    <details>\n        <summary>{html_module.escape(t)} (top {len(patterns[:20])})</summary>\n        <ol>\n"
            for text, count in patterns[:20]:
                html += f"            <li><code>{html_module.escape(text)}</code> ({count} occurrences)</li>\n"
            html += "        </ol>\n    </details>\n"

    # Sample misses by category
    html += "    <h2>Sample Misses by Category</h2>\n"
    for cat in categories:
        examples = miss_examples.get(cat, [])
        if examples:
            html += f"""    <details>
        <summary class="category-{cat}">{cat.replace('_', ' ').title()} ({len(examples)} examples)</summary>
        <table>
            <tr>
                <th>Record ID</th>
                <th>Type</th>
                <th>Gold Text</th>
                <th>Context</th>
                <th>Details</th>
            </tr>
"""
            for ex in examples[:50]:
                gold_text = html_module.escape(ex.get('gold_text', 'N/A'))
                context = html_module.escape(ex.get('context', 'N/A'))
                details_str = ""
                details = ex.get('details', {})
                if cat == 'wrong_type':
                    details_str = f"Predicted as: {details.get('predicted_type', '?')}"
                elif cat == 'partial_overlap':
                    details_str = f"Overlap: {details.get('overlap_chars', 0)} chars (need {details.get('required', 0)})"
                elif cat == 'boundary_mismatch':
                    details_str = f"Gold: {details.get('gold_span', '?')}, Pred: {details.get('pred_span', '?')}"
                elif cat == 'near_miss':
                    details_str = f"Nearest pred {details.get('distance', '?')} chars away"

                html += f"""            <tr>
                <td>{html_module.escape(ex.get('id', 'N/A'))}</td>
                <td>{html_module.escape(ex.get('type', 'N/A'))}</td>
                <td class="gold-text">{gold_text}</td>
                <td class="context">{context}</td>
                <td>{html_module.escape(details_str)}</td>
            </tr>
"""
            html += "        </table>\n    </details>\n"

    # Documents with most misses
    html += """
    <h2>Documents with Most Misses</h2>
    <table>
        <tr>
            <th>Document ID</th>
            <th>FN Count</th>
            <th>TP Count</th>
            <th>Recall</th>
        </tr>
"""
    # Sort by FN count descending
    doc_stats = sorted(miss_stats.get('per_document', {}).items(),
                       key=lambda x: x[1]['fn'], reverse=True)[:20]
    for doc_id, stats in doc_stats:
        fn = stats['fn']
        tp = stats['tp']
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        html += f"""        <tr>
            <td>{html_module.escape(doc_id)}</td>
            <td>{fn}</td>
            <td>{tp}</td>
            <td>{recall:.2%}</td>
        </tr>
"""

    html += """    </table>
</body>
</html>
"""

    with open(output_path, 'w') as f:
        f.write(html)

    logger.info(f"Detailed report written to {output_path}")


def run_eval(args, models, pii_config=None):
    import collections

    detectors = set(args.detectors.lower().split(","))

    # Load gold corrections if provided
    gold_corrections = load_gold_corrections(getattr(args, 'gold_corrections', None))
    if gold_corrections.get('remove_entities'):
        logger.debug(f"Loaded {len(gold_corrections['remove_entities'])} gold corrections")

    # 1. Load splits
    allowed_ids = set()
    allowed_files = set()

    if args.ids:
        try:
            with open(args.ids, 'r') as f:
                for line in f:
                    allowed_ids.add(line.strip())
        except Exception as e:
            logger.error(f"Failed to load ids file: {e}")
            sys.exit(1)

    if args.files:
        try:
            with open(args.files, 'r') as f:
                for line in f:
                    allowed_files.add(line.strip())
        except Exception as e:
            logger.error(f"Failed to load files list: {e}")
            sys.exit(1)

    if not args.ids and not args.files:
        logger.error("Neither --ids nor --files provided.")
        sys.exit(1)

    # Determine total records for progress reporting
    total_expected = len(allowed_ids) if args.ids else len(allowed_files)

    # Dynamic progress interval based on dataset size
    if total_expected <= 50:
        progress_interval = 10
    elif total_expected <= 200:
        progress_interval = 5
    elif total_expected <= 1000:
        progress_interval = 3
    elif total_expected <= 5000:
        progress_interval = 2
    else:
        progress_interval = 1

    # 2. Iterate gold
    # Stats containers
    stats = collections.defaultdict(lambda: {'tp': 0, 'fn': 0, 'fp': 0, 'gold': 0, 'pred': 0})

    # Analysis dumps
    fn_dumps = collections.defaultdict(list)
    fp_dumps = collections.defaultdict(list)

    # Detailed report data structures
    miss_stats = {
        'by_category': collections.defaultdict(lambda: collections.defaultdict(int)),
        'by_length': collections.defaultdict(lambda: collections.defaultdict(int)),
        'common_texts': collections.defaultdict(lambda: collections.defaultdict(int)),
        'per_document': collections.defaultdict(lambda: {'fn': 0, 'tp': 0})
    }
    miss_examples = collections.defaultdict(list)
    max_examples_per_cat = getattr(args, 'max_examples', 50)
    proximity_threshold = getattr(args, 'proximity_threshold', 50)

    processed_records = 0
    last_progress = 0
    eval_start_time = time.perf_counter()

    # Clear existing dump files if checkpoint mode is enabled
    if args.checkpoint_every > 0:
        if not os.path.exists(args.report_dir):
            os.makedirs(args.report_dir)
        for t in args.types.split(','):
            for prefix in ['fn_', 'fp_']:
                path = os.path.join(args.report_dir, f"{prefix}{t}.jsonl")
                if os.path.exists(path):
                    os.remove(path)
        logger.debug(f"Checkpoint mode enabled: cleared existing dump files in {args.report_dir}")

    try:
        with open(args.eval, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue

                rid = record.get('id', '')

                # Check split inclusion
                keep = False
                if args.ids and rid in allowed_ids:
                    keep = True
                elif args.files:
                    # Parse FILE id: ^FILE=([^/]+)
                    m = re.search(r'FILE=([^/]+)', rid)
                    if m and m.group(1) in allowed_files:
                        keep = True

                if not keep:
                    continue

                # Early exit for testing
                if args.eval_max_records > 0 and processed_records >= args.eval_max_records:
                    break

                processed_records += 1

                # Progress reporting
                if total_expected > 0:
                    progress_pct = int((processed_records / total_expected) * 100)
                    if progress_pct >= last_progress + progress_interval or processed_records == total_expected:
                        elapsed = time.perf_counter() - eval_start_time
                        rate = processed_records / elapsed if elapsed > 0 else 0
                        remaining = total_expected - processed_records
                        eta_sec = remaining / rate if rate > 0 else 0
                        if eta_sec >= 60:
                            eta_str = f"{int(eta_sec // 60)}m {int(eta_sec % 60)}s"
                        else:
                            eta_str = f"{int(eta_sec)}s"
                        eta_display = f"ETA {eta_str}" if remaining > 0 else "done"
                        print(
                            f"Progress: {processed_records}/{total_expected} ({progress_pct}%) - {rate:.1f} rec/s - {eta_display}",
                            file=sys.stderr)
                        last_progress = progress_pct

                text = record.get('text', '')

                # Apply gold corrections if provided
                if gold_corrections.get('remove_entities'):
                    record = apply_gold_corrections(record, gold_corrections)

                gold_list = record.get('entities', [])

                # Run detection - use gateway mode if enabled
                if args.gateway:
                    pred_list, det_stats = detect_pii_gateway(text, models, args.min_score,
                                                              detectors=detectors, config=pii_config)
                else:
                    pred_list, det_stats = detect_pii(text, models, args.min_score,
                                                      detectors=detectors, config=pii_config)

                # Log gateway trigger status if requested
                if args.log and args.gateway:
                    if det_stats.get('gateway_skipped', False):
                        logger.debug(f"[{rid}] gateway=skipped")
                    else:
                        trigger = det_stats.get('gateway_trigger', 'unknown')
                        match = det_stats.get('gateway_match', '')
                        logger.debug(f"[{rid}] gateway=triggered ({trigger}: {match})")

                # Filter preds/gold by requested types
                req_types = set(args.types.split(','))

                # Group by type
                g_by_type = collections.defaultdict(list)
                p_by_type = collections.defaultdict(list)

                for g in gold_list:
                    if g['type'] in req_types:
                        g_by_type[g['type']].append(g)
                for p in pred_list:
                    if p['type'] in req_types:
                        p_by_type[p['type']].append(p)

                # Create flat list of all predictions for proximity checks
                all_preds_flat = [p for preds in p_by_type.values() for p in preds]

                # Evaluate per type
                for t in req_types:
                    g_ents = g_by_type[t]
                    p_ents = p_by_type[t]

                    stats[t]['gold'] += len(g_ents)
                    stats[t]['pred'] += len(p_ents)

                    mode = get_match_mode_for_type(t, args.match)
                    matches, fn_list, fp_list = match_entities(
                        g_ents,
                        p_ents,
                        mode,
                        args.overlap_min_chars,
                        type_name=t
                    )

                    stats[t]['tp'] += len(matches)
                    stats[t]['fn'] += len(fn_list)
                    stats[t]['fp'] += len(fp_list)

                    # Track per-document stats
                    miss_stats['per_document'][rid]['tp'] += len(matches)
                    miss_stats['per_document'][rid]['fn'] += len(fn_list)

                    # Process each FN for detailed analysis
                    for fn in fn_list:
                        # Context
                        s, e = fn['start'], fn['end']
                        ctx_s = max(0, s - args.context)
                        ctx_e = min(len(text), e + args.context)
                        snippet = text[ctx_s:s] + "[[" + text[s:e] + "]]" + text[e:ctx_e]
                        gold_text = text[s:e]

                        # Categorize the miss
                        cat_result = categorize_miss(
                            fn, p_by_type, all_preds_flat,
                            mode, args.overlap_min_chars, proximity_threshold
                        )
                        category = cat_result['category']

                        # Collect stats
                        miss_stats['by_category'][category][t] += 1
                        miss_stats['by_length'][bucket_entity_length(e - s)][t] += 1
                        miss_stats['common_texts'][t][gold_text.lower().strip()] += 1

                        # Collect examples (limited)
                        if len(miss_examples[category]) < max_examples_per_cat:
                            miss_examples[category].append({
                                'id': rid,
                                'type': t,
                                'gold_text': gold_text,
                                'context': snippet,
                                'details': cat_result['details']
                            })

                        # Store dumps (existing behavior)
                        if len(fn_dumps[t]) < args.max_errors:
                            dump_rec = {
                                "id": rid,
                                "type": t,
                                "gold": fn,
                                "context": snippet,
                                "category": category,
                                "details": cat_result['details']
                            }
                            fn_dumps[t].append(dump_rec)

                    if args.write_fp and len(fp_dumps[t]) < args.max_errors:
                        for fp in fp_list:
                            s, e = fp['start'], fp['end']
                            ctx_s = max(0, s - args.context)
                            ctx_e = min(len(text), e + args.context)
                            snippet = text[ctx_s:s] + "[[" + text[s:e] + "]]" + text[e:ctx_e]

                            fp_dumps[t].append({
                                "id": rid,
                                "type": t,
                                "pred": fp,
                                "context": snippet
                            })

                # Checkpoint: write incremental dumps if enabled
                if args.checkpoint_every > 0 and processed_records % args.checkpoint_every == 0:
                    for t, rows in fn_dumps.items():
                        if rows:
                            with open(os.path.join(args.report_dir, f"fn_{t}.jsonl"), "a") as f:
                                for r in rows:
                                    f.write(json.dumps(r) + "\n")
                    if args.write_fp:
                        for t, rows in fp_dumps.items():
                            if rows:
                                with open(os.path.join(args.report_dir, f"fp_{t}.jsonl"), "a") as f:
                                    for r in rows:
                                        f.write(json.dumps(r) + "\n")
                    fn_dumps.clear()
                    fp_dumps.clear()
                    logger.debug(f"Checkpoint written at record {processed_records}")

    except FileNotFoundError:
        logger.error(f"Gold file not found: {args.eval}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning(f"\nInterrupted. Writing partial results ({processed_records} records processed)...")

    if processed_records == 0:
        logger.error("0 records selected for evaluation.")
        sys.exit(1)

    # 3. Calculate Metrics
    results_by_type = {}
    micro_stats = {'tp': 0, 'fn': 0, 'fp': 0}
    pl_stats = {'tp': 0, 'fn': 0, 'fp': 0}  # Person+Location

    def safe_div(n, d):
        return n / d if d > 0 else 0.0

    def calc_f1(p, r):
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    for t in sorted(args.types.split(',')):
        s = stats[t]
        tp, fn, fp = s['tp'], s['fn'], s['fp']

        recall = safe_div(tp, tp + fn)
        precision = safe_div(tp, tp + fp)
        f1 = calc_f1(precision, recall)

        results_by_type[t] = {
            "tp": tp, "fn": fn, "fp": fp,
            "recall": round(recall, 4),
            "precision": round(precision, 4),
            "f1": round(f1, 4)
        }

        micro_stats['tp'] += tp
        micro_stats['fn'] += fn
        micro_stats['fp'] += fp

        if t in ['PERSON', 'LOCATION']:
            pl_stats['tp'] += tp
            pl_stats['fn'] += fn
            pl_stats['fp'] += fp

    # Aggregates
    def compute_agg(s):
        r = safe_div(s['tp'], s['tp'] + s['fn'])
        p = safe_div(s['tp'], s['tp'] + s['fp'])
        f = calc_f1(p, r)
        return {"tp": s['tp'], "fn": s['fn'], "fp": s['fp'], "recall": round(r, 4), "precision": round(p, 4),
                "f1": round(f, 4)}

    micro_res = compute_agg(micro_stats)
    pl_res = compute_agg(pl_stats)

    # 4. Output
    if args.json:
        out = {
            "meta": {
                "gold": args.eval,
                "split": args.ids if args.ids else f"files:{args.files}",
                "records": processed_records,
                "match": args.match,
                "min_score": args.min_score
            },
            "by_type": results_by_type,
            "micro": micro_res,
            "person_location_micro": pl_res
        }
        print(json.dumps(out, indent=2 if args.pretty else None))
    else:
        # Readable Table
        print(f"Evaluation Report", file=sys.stderr)
        print(f"Records: {processed_records}", file=sys.stderr)
        print("-" * 85, file=sys.stderr)
        print(f"{'Type':<15} {'TP':<6} {'FN':<6} {'FP':<6} {'Recall':<8} {'Prec':<8} {'F1':<8}", file=sys.stderr)
        print("-" * 85, file=sys.stderr)
        for t, res in results_by_type.items():
            print(
                f"{t:<15} {res['tp']:<6} {res['fn']:<6} {res['fp']:<6} {res['recall']:<8.4f} {res['precision']:<8.4f} {res['f1']:<8.4f}",
                file=sys.stderr)
        print("-" * 85, file=sys.stderr)
        print(
            f"{'MICRO ALL':<15} {micro_res['tp']:<6} {micro_res['fn']:<6} {micro_res['fp']:<6} {micro_res['recall']:<8.4f} {micro_res['precision']:<8.4f} {micro_res['f1']:<8.4f}",
            file=sys.stderr)
        print(
            f"{'MICRO P+L':<15} {pl_res['tp']:<6} {pl_res['fn']:<6} {pl_res['fp']:<6} {pl_res['recall']:<8.4f} {pl_res['precision']:<8.4f} {pl_res['f1']:<8.4f}",
            file=sys.stderr)

    # 5. Write Dumps
    if not os.path.exists(args.report_dir):
        os.makedirs(args.report_dir)

    # Use append mode if checkpoint was enabled (remaining items after last checkpoint)
    mode = "a" if args.checkpoint_every > 0 else "w"
    for t, rows in fn_dumps.items():
        if rows:
            with open(os.path.join(args.report_dir, f"fn_{t}.jsonl"), mode) as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")

    if args.write_fp:
        for t, rows in fp_dumps.items():
            if rows:
                with open(os.path.join(args.report_dir, f"fp_{t}.jsonl"), mode) as f:
                    for r in rows:
                        f.write(json.dumps(r) + "\n")

    # 6. Generate detailed report (always in eval mode)
    # Convert common_texts to sorted list of (text, count) tuples
    common_texts_sorted = {}
    for t, text_counts in miss_stats['common_texts'].items():
        sorted_items = sorted(text_counts.items(), key=lambda x: x[1], reverse=True)
        common_texts_sorted[t] = sorted_items

    report_data = {
        'meta': {
            'gold': args.eval,
            'split': args.ids if args.ids else f"files:{args.files}",
            'records': processed_records,
            'match': args.match,
            'min_score': args.min_score,
            'config': {
                'models': args.models,
                'detectors': args.detectors,
                'gateway': args.gateway,
                'types': args.types,
                'config_file': args.config or '(default)',
                'model_path': pii_config.models.piiranha.model_path if pii_config else None,
            }
        },
        'by_type': results_by_type,
        'micro': micro_res,
        'miss_stats': {
            'by_category': {k: dict(v) for k, v in miss_stats['by_category'].items()},
            'by_length': {k: dict(v) for k, v in miss_stats['by_length'].items()},
            'common_texts': common_texts_sorted,
            'per_document': dict(miss_stats['per_document'])
        },
        'miss_examples': dict(miss_examples)
    }

    report_format = getattr(args, 'report_format', 'html')
    if report_format == 'html':
        report_path = os.path.join(args.report_dir, "detailed_report.html")
        generate_html_report(report_data, report_path)
    else:
        # Markdown format - simple text-based output
        report_path = os.path.join(args.report_dir, "detailed_report.md")
        with open(report_path, 'w') as f:
            f.write("# PII Detection Evaluation Report\n\n")
            f.write(f"**Records:** {processed_records}\n")
            f.write(f"**Overall Recall:** {micro_res['recall']:.2%}\n")
            f.write(f"**Overall Precision:** {micro_res['precision']:.2%}\n")
            f.write(f"**Overall F1:** {micro_res['f1']:.4f}\n\n")
            f.write("## Miss Categories\n\n")
            for cat in ['no_prediction', 'wrong_type', 'partial_overlap', 'boundary_mismatch', 'near_miss']:
                total = sum(miss_stats['by_category'].get(cat, {}).values())
                f.write(f"- **{cat}**: {total}\n")
            f.write("\n## Examples by Category\n\n")
            for cat, examples in miss_examples.items():
                f.write(f"### {cat} ({len(examples)} examples)\n\n")
                for ex in examples[:10]:
                    f.write(f"- `{ex['gold_text']}` ({ex['type']}) - {ex['context'][:80]}...\n")
                f.write("\n")
        logger.info(f"Detailed report written to {report_path}")
