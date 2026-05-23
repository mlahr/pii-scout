import json
import os
import tempfile
import pytest
import subprocess
import sys
import gzip
from pathlib import Path

# Helper to write synthetic index
def write_jsonl(path, records):
    with open(path, 'w') as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

@pytest.fixture
def temp_index_file():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        path = f.name
    yield path
    if os.path.exists(path):
        os.remove(path)

@pytest.fixture
def temp_output_files():
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f1, \
         tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f2:
        out_path = f1.name
        report_path = f2.name
    yield out_path, report_path
    if os.path.exists(out_path):
        os.remove(out_path)
    if os.path.exists(report_path):
        os.remove(report_path)

def test_sampling_exact_n(temp_index_file, temp_output_files):
    out_path, report_path = temp_output_files
    
    # Create 100 records
    records = []
    for i in range(100):
        records.append({
            "path": f"/tmp/doc_{i}.pdf",
            "pdf_id": f"id_{i}",
            "bytes": 1000,
            "page_count": 5,
            "size_bucket": "normal",
            "producer": "Adobe",
            "creator": "Word",
            "likely_scanned": False,
            "has_text_ops": True
        })
    write_jsonl(temp_index_file, records)
    
    # Run script
    cmd = [
        sys.executable, "sample_candidates.py",
        "--index", temp_index_file,
        "--out", out_path,
        "--report", report_path,
        "--n", "10",
        "--seed", "42"
    ]
    subprocess.check_call(cmd)
    
    # Verify
    with open(out_path, 'r') as f:
        lines = f.readlines()
    assert len(lines) == 10
    
    with open(report_path, 'r') as f:
        report = json.load(f)
    assert report["n_selected"] == 10
    assert report["n_requested"] == 10

def test_scanned_share_preference(temp_index_file, temp_output_files):
    out_path, report_path = temp_output_files
    
    # Create 200 likely_scanned and 200 text docs
    records = []
    for i in range(200):
        records.append({
            "path": f"/tmp/scanned_{i}.pdf",
            "bytes": 1000,
            "page_count": 5,
            "size_bucket": "normal",
            "producer": "Scanner", 
            "likely_scanned": True,
            "has_text_ops": False
        })
    for i in range(200):
        records.append({
            "path": f"/tmp/text_{i}.pdf",
            "bytes": 1000,
            "page_count": 5,
            "size_bucket": "normal",
            "producer": "Word",
            "likely_scanned": False,
            "has_text_ops": True
        })
    write_jsonl(temp_index_file, records)
    
    # Request n=100, scanned_share=0.1 -> expect 10 scanned, 90 text
    cmd = [
        sys.executable, "sample_candidates.py",
        "--index", temp_index_file,
        "--out", out_path,
        "--report", report_path,
        "--n", "100",
        "--seed", "42",
        "--prefer-textpdf",
        "--scanned-share", "0.1"
    ]
    subprocess.check_call(cmd)
    
    with open(report_path, 'r') as f:
        report = json.load(f)
    
    scanned_count = report["marginals"]["likely_scanned"].get("True", 0)
    text_count = report["marginals"]["likely_scanned"].get("False", 0)
    
    # Due to deterministic rounding it might be exactly 10 or 11/9 etc.
    # We allocated quotas. 100 * 0.1 = 10.
    assert 9 <= scanned_count <= 11
    assert 89 <= text_count <= 91

def test_stratification(temp_index_file, temp_output_files):
    out_path, report_path = temp_output_files
    
    # Create diverse pool
    records = []
    # Tiny, 1 page
    records.append({"path": "A", "bytes": 10, "page_count": 1, "size_bucket": "tiny", "producer": "A", "likely_scanned": False, "has_text_ops": True})
    # Huge, 100 pages
    records.append({"path": "B", "bytes": 10000000, "page_count": 100, "size_bucket": "huge", "producer": "A", "likely_scanned": False, "has_text_ops": True})
    # Normal, 3 pages
    records.append({"path": "C", "bytes": 50000, "page_count": 3, "size_bucket": "normal", "producer": "A", "likely_scanned": False, "has_text_ops": True})
    
    # Add duplicates to allow sampling multiple
    records = records * 10
    write_jsonl(temp_index_file, records)
    
    cmd = [
        sys.executable, "sample_candidates.py",
        "--index", temp_index_file,
        "--out", out_path,
        "--report", report_path,
        "--n", "3", # Should pick 1 of each bucket if possible
        "--seed", "42",
        "--page-buckets", "1,2-5,6+"
    ]
    subprocess.check_call(cmd)
    
    with open(out_path, 'r') as f:
        lines = [l.strip() for l in f]
    
    assert len(lines) == 3
    # We should have one of each type if stratification works to force coverage
    # (Since total N=3 and we have >3 buckets? No, we have 3 buckets exactly: tiny/1, huge/100, normal/3)
    # Actually bucket depends on size/page/family.
    # A: tiny, 1, UNKNOWN
    # B: huge, 6+, UNKNOWN
    # C: normal, 2-5, UNKNOWN
    # So 3 distinct buckets. We requested N=3. Method ensures 1 per bucket.
    
    # Check that we got different paths
    # Note: paths are A, B, C repeated. Output file might have duplicates if we allowed them? 
    # Default is allow-duplicates=False but unique items are treated by path?
    # Actually wait, we have duplicate PATHS in input? 
    # The script treats them as separate records but uses path as output.
    # If the input contains duplicate paths (which normally shouldn't happen in index),
    # the script keys them by object/dict identity when loading?
    # No, it loads them into list.
    # But if path matches exclude it will exclude.
    # Our mocked data has same path for multiple records.
    # That's fine for this test, but better to uniqueify paths.
    
    records_uniq = []
    for i, r in enumerate(records):
        r2 = r.copy()
        r2["path"] = f"{r['path']}_{i}"
        records_uniq.append(r2)
    write_jsonl(temp_index_file, records_uniq)
    
    subprocess.check_call(cmd)
    
    with open(report_path, 'r') as f:
        report = json.load(f)
        
    marginals = report["marginals"]
    # Check we covered sizes
    assert marginals["size_bucket"].get("tiny", 0) >= 1
    assert marginals["size_bucket"].get("huge", 0) >= 1
    assert marginals["size_bucket"].get("normal", 0) >= 1
    
def test_exclude_file(temp_index_file, temp_output_files):
    out_path, report_path = temp_output_files
    
    records = [
        {"path": "/tmp/a.pdf", "bytes": 10, "page_count": 1, "size_bucket": "normal"},
        {"path": "/tmp/b.pdf", "bytes": 10, "page_count": 1, "size_bucket": "normal"},
        {"path": "/tmp/c.pdf", "bytes": 10, "page_count": 1, "size_bucket": "normal"},
    ]
    write_jsonl(temp_index_file, records)
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("/tmp/b.pdf\n")
        exclude_path = f.name
        
    try:
        cmd = [
            sys.executable, "sample_candidates.py",
            "--index", temp_index_file,
            "--out", out_path,
            "--report", report_path,
            "--n", "3",
            "--exclude-file", exclude_path
        ]
        subprocess.check_call(cmd)
        
        with open(out_path, 'r') as f:
            selected = [l.strip() for l in f]
            
        assert "/tmp/b.pdf" not in selected
        assert "/tmp/a.pdf" in selected
        assert "/tmp/c.pdf" in selected
        assert len(selected) == 2 # Only 2 available after exclude
        
    finally:
        os.remove(exclude_path)

def test_determinism(temp_index_file, temp_output_files):
    out_path, report_path = temp_output_files
    
    records = []
    for i in range(50):
        records.append({
            "path": f"/tmp/{i}.pdf",
            "bytes": 100,
            "page_count": 1,
            "size_bucket": "normal",
            "producer": f"Prod{i%5}",
        })
    write_jsonl(temp_index_file, records)
    
    cmd = [
        sys.executable, "sample_candidates.py",
        "--index", temp_index_file,
        "--out", out_path,
        "--report", report_path,
        "--n", "10",
        "--seed", "12345"
    ]
    
    subprocess.check_call(cmd)
    with open(out_path, 'r') as f:
        run1 = f.readlines()
        
    subprocess.check_call(cmd)
    with open(out_path, 'r') as f:
        run2 = f.readlines()
        

    assert run1 == run2

def test_gzip_input(temp_output_files):
    out_path, report_path = temp_output_files
    
    # Create a gzipped index file
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.jsonl.gz', delete=False) as f:
        gz_path = f.name
        
    try:
        records = [
            {"path": "/tmp/g1.pdf", "bytes": 10, "page_count": 1, "size_bucket": "normal"},
            {"path": "/tmp/g2.pdf", "bytes": 10, "page_count": 1, "size_bucket": "normal"}
        ]
        
        with gzip.open(gz_path, 'wt') as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
                
        cmd = [
            sys.executable, "sample_candidates.py",
            "--index", gz_path,
            "--out", out_path,
            "--report", report_path,
            "--n", "2"
        ]
        subprocess.check_call(cmd)
        
        with open(out_path, 'r') as f:
            lines = [l.strip() for l in f]
            
        assert len(lines) == 2
        assert "/tmp/g1.pdf" in lines or "/tmp/g2.pdf" in lines
        
    finally:
        if os.path.exists(gz_path):
            os.remove(gz_path)

def test_deduplication(temp_index_file, temp_output_files):
    out_path, report_path = temp_output_files
    
    # Same ID, different paths
    records = [
        {"path": "/tmp/a.pdf", "pdf_id": "HASH1", "bytes": 10, "page_count": 1, "size_bucket": "normal"},
        {"path": "/tmp/b.pdf", "pdf_id": "HASH1", "bytes": 10, "page_count": 1, "size_bucket": "normal"}, # Duplicate ID
        {"path": "/tmp/c.pdf", "pdf_id": "HASH2", "bytes": 10, "page_count": 1, "size_bucket": "normal"},
    ]
    write_jsonl(temp_index_file, records)
    
    # Run 1: Default (No duplicates)
    cmd = [
        sys.executable, "sample_candidates.py",
        "--index", temp_index_file,
        "--out", out_path,
        "--report", report_path,
        "--n", "10"
    ]
    subprocess.check_call(cmd)
    
    with open(out_path, 'r') as f:
        lines = [l.strip() for l in f]
    
    assert len(lines) == 2 # HASH1 and HASH2
    
    # Run 2: Allow duplicates
    cmd = [
        sys.executable, "sample_candidates.py",
        "--index", temp_index_file,
        "--out", out_path,
        "--report", report_path,
        "--n", "10",
        "--allow-duplicates"
    ]
    subprocess.check_call(cmd)
    
    with open(out_path, 'r') as f:
        lines = [l.strip() for l in f]
    
    assert len(lines) == 3 # a, b, c all present
