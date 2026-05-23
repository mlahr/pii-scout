#!/usr/bin/env python3
import argparse
import collections
import json
import sys
from typing import List, Dict, Any

# Default allowed entity types
DEFAULT_ALLOWED_TYPES = {
    "PERSON", "LOCATION", "ADDRESS", "SSN", "PHONE_NUMBER",
    "ACCOUNT_NUMBER", "BIRTHDATE", "DATE", "EMAIL"
}

def parse_args():
    parser = argparse.ArgumentParser(description="Validate and fix gold standard JSONL annotations.")
    parser.add_argument("--in", dest="input_file", required=True, help="Input JSONL file")
    parser.add_argument("--out", dest="output_file", help="Output fixed JSONL file")
    parser.add_argument("--fix", action="store_true", help="Apply safe auto-fixes")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    parser.add_argument("--max-errors", type=int, default=200, help="Max errors to report in detail")
    parser.add_argument("--report", default="validation_report.json", help="Path to write JSON report")
    parser.add_argument("--context", type=int, default=40, help="Context chars for error reporting")
    parser.add_argument("--allowed-types", help="Comma-separated allowed entity types")
    parser.add_argument("--require-text-field", action="store_true", help="Fail if 'text' field is missing")
    return parser.parse_args()

def validate_record(line_num: int, record: Dict[str, Any], args, allowed_types: set) -> List[Dict[str, Any]]:
    issues = []
    
    # 1. Record-level checks
    rec_id = record.get("id")
    if not isinstance(rec_id, str) or not rec_id:
        issues.append({
            "code": "MISSING_ID",
            "message": "Record must have a non-empty string ID",
            "level": "ERROR"
        })
        return issues # Critical failure, return early

    text = record.get("text")
    if text is None:
        if args.require_text_field:
            issues.append({
                "code": "MISSING_TEXT",
                "message": "Record missing required 'text' field",
                "level": "ERROR"
            })
        else:
            issues.append({
                "code": "MISSING_TEXT",
                "message": "Record missing 'text' field (validation limited)",
                "level": "WARNING"
            })
    elif not isinstance(text, str):
         issues.append({
            "code": "INVALID_TEXT",
            "message": "'text' field must be a string",
            "level": "ERROR"
        })
         text = None # invalidate text for further checks

    entities = record.get("entities")
    if entities is None:
        issues.append({
            "code": "MISSING_ENTITIES",
            "message": "'entities' field missing (treated as empty)",
            "level": "WARNING"
        })
        entities = []
    elif not isinstance(entities, list):
        issues.append({
            "code": "INVALID_ENTITIES",
            "message": "'entities' field must be a list",
            "level": "ERROR"
        })
        return issues # Cannot process entities

    # 2. Entity-level checks
    for idx, entity in enumerate(entities):
        if not isinstance(entity, dict):
            issues.append({
                "id": rec_id, "entity_index": idx,
                "code": "INVALID_ENTITY_FORMAT", 
                "message": "Entity must be a JSON object",
                "level": "ERROR"
            })
            continue

        etype = entity.get("type")
        start = entity.get("start")
        end = entity.get("end")

        # Basic type and field checks
        if etype not in allowed_types:
             issues.append({
                "id": rec_id, "entity_index": idx,
                "code": "INVALID_TYPE",
                "message": f"Type '{etype}' not in allowed list",
                "level": "ERROR",
                "type": etype
            })
        
        if not isinstance(start, int) or not isinstance(end, int):
            issues.append({
                "id": rec_id, "entity_index": idx,
                "code": "INVALID_OFFSETS",
                "message": "Start/end must be integers",
                "level": "ERROR"
            })
            continue
            
        if text is not None:
            # Bounds check
            if not (0 <= start < end <= len(text)):
                issues.append({
                    "id": rec_id, "entity_index": idx,
                    "code": "BAD_OFFSETS",
                    "message": f"Offsets [{start}:{end}] out of bounds (text len {len(text)}) or invalid",
                    "level": "ERROR", 
                    "start": start, "end": end
                })
                continue
            
            span_text = text[start:end]
            
            # Content checks
            if not span_text: # Empty span (already covered by start < end check effectively, but explicit safety)
                issues.append({
                    "id": rec_id, "entity_index": idx,
                    "code": "EMPTY_SPAN",
                    "message": "Extracted span is empty",
                    "level": "ERROR"
                })
            
            if span_text.strip() != span_text:
                 issues.append({
                    "id": rec_id, "entity_index": idx,
                    "code": "WHITESPACE_SPAN",
                    "message": "Span contains leading/trailing whitespace",
                    "level": "ERROR",
                    "span": span_text
                })
            
            if len(span_text) < 2 and etype in ["PERSON", "LOCATION", "ADDRESS"]:
                 issues.append({
                    "id": rec_id, "entity_index": idx,
                    "code": "SHORT_SPAN",
                    "message": f"Span length {len(span_text)} < 2 for {etype}",
                    "level": "WARNING",
                    "span": span_text
                })
            
            if "\n" in span_text:
                 issues.append({
                    "id": rec_id, "entity_index": idx,
                    "code": "NEWLINE_IN_SPAN",
                    "message": "Span contains newline characters",
                    "level": "WARNING",
                    "span": span_text
                })
                
            if "text" in entity and entity["text"] != span_text:
                 issues.append({
                    "id": rec_id, "entity_index": idx,
                    "code": "TEXT_MISMATCH",
                    "message": f"Entity text '{entity['text']}' != extracted '{span_text}'",
                    "level": "WARNING"
                })

    # Duplicate detection
    # We warn about exact duplicates (same start, end, type)
    seen = set()
    for idx, entity in enumerate(entities):
        if not isinstance(entity, dict): continue
        sig = (entity.get("start"), entity.get("end"), entity.get("type"))
        if None in sig: continue
        if sig in seen:
            issues.append({
                "id": rec_id, "entity_index": idx,
                "code": "DUPLICATE_ENTITY",
                "message": f"Duplicate entity {sig}",
                "level": "WARNING"
            })
        else:
            seen.add(sig)

    # Attach record ID to all issues that don't have it yet
    for issue in issues:
        if "id" not in issue:
            issue["id"] = rec_id
            
    return issues

def fix_record(record: Dict[str, Any]) -> Dict[str, Any]:
    text = record.get("text")
    if not text or not isinstance(text, str):
        return record # Cannot fix without text
    
    entities = record.get("entities", [])
    if not isinstance(entities, list):
        return record
    
    valid_entities = []
    seen = set()
    
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        
        start = entity.get("start")
        end = entity.get("end")
        etype = entity.get("type")
        
        if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text)):
            # If invalid offsets, we generally cannot safely auto-fix them without more logic.
            # We keep them BUT we don't include them in 'valid_entities' if they are totally broken?
            # Actually, the user asked to FIX common issues.
            # If offsets are bad, we might just have to skip fixing this entity or keep it as is.
            # Let's keep it as is but not attempt trim logic if OOB.
            valid_entities.append(entity)
            continue

        # Trim whitespace logic
        span_text = text[start:end]
        leading = len(span_text) - len(span_text.lstrip())
        trailing = len(span_text) - len(span_text.rstrip())
        
        if leading > 0 or trailing > 0:
            new_start = start + leading
            new_end = end - trailing
            # Ensure we didn't inverse if it was all whitespace
            if new_start < new_end:
                start, end = new_start, new_end
                entity["start"] = start
                entity["end"] = end
        
        # Sync text field
        entity["text"] = text[start:end]
        
        # Dedup logic
        sig = (start, end, etype)
        if sig not in seen:
            seen.add(sig)
            valid_entities.append(entity)
    
    # Sort
    # Python 3 sort is stable. Sort by start, then end, then type.
    valid_entities.sort(key=lambda x: (x.get("start", 0), x.get("end", 0), x.get("type", "")))
    
    record["entities"] = valid_entities
    return record

def main():
    args = parse_args()
    
    allowed_types = DEFAULT_ALLOWED_TYPES
    if args.allowed_types:
        allowed_types = set(t.strip() for t in args.allowed_types.split(","))

    stats = {
        "total_records": 0,
        "total_entities": 0,
        "records_with_errors": 0,
        "error_counts": collections.defaultdict(int),
    }
    
    all_issues = []
    
    # Setup output if needed
    out_f = None
    if args.output_file:
        try:
            out_f = open(args.output_file, 'w', encoding='utf-8')
        except IOError as e:
            sys.stderr.write(f"Error opening output file: {e}\n")
            sys.exit(1)

    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line: continue
                
                stats["total_records"] += 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    issue = {
                        "id": f"LINE_{line_num}",
                        "code": "JSON_PARSE_ERROR",
                        "message": f"Invalid JSON on line {line_num}: {e}",
                        "level": "ERROR"
                    }
                    all_issues.append(issue)
                    stats["error_counts"][issue["code"]] += 1
                    stats["records_with_errors"] += 1
                    continue
                
                # Count entities before validation for stats
                ents = record.get("entities", [])
                if isinstance(ents, list):
                    stats["total_entities"] += len(ents)

                # Validate
                issues = validate_record(line_num, record, args, allowed_types)
                
                if issues:
                    stats["records_with_errors"] += 1
                    for i in issues:
                        stats["error_counts"][i["code"]] += 1
                        # Enforce limit on stored issues
                        if len(all_issues) < args.max_errors:
                            all_issues.append(i)

                # Fix and Output
                if out_f:
                    if args.fix:
                        record = fix_record(record)
                    # Write back to JSONL
                    out_f.write(json.dumps(record, ensure_ascii=False) + "\n")

    except FileNotFoundError:
        sys.stderr.write(f"Error: Input file '{args.input_file}' not found.\n")
        sys.exit(1)
    finally:
        if out_f:
            out_f.close()

    # Reporting
    has_errors = any(i["level"] == "ERROR" for i in all_issues)
    has_warnings = any(i["level"] == "WARNING" for i in all_issues)
    
    # Calculate exit code
    exit_code = 0
    if has_errors:
        exit_code = 1
    if args.strict and has_warnings:
        exit_code = 1
        
    # Stderr Summary
    sys.stderr.write("Validation Summary:\n")
    sys.stderr.write(f"  Total Records: {stats['total_records']}\n")
    sys.stderr.write(f"  Total Entities: {stats['total_entities']}\n")
    sys.stderr.write(f"  Records w/ Issues: {stats['records_with_errors']}\n")
    if stats['error_counts']:
        sys.stderr.write("  Issues by Category:\n")
        for code, count in stats['error_counts'].items():
            sys.stderr.write(f"    {code}: {count}\n")
    else:
        sys.stderr.write("  No issues found.\n")

    # JSON Report
    report_data = {
        "summary": stats,
        "issues": all_issues
    }
    try:
        with open(args.report, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        sys.stderr.write(f"Warning: Could not write report to {args.report}: {e}\n")

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
