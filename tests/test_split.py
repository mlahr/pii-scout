
import json
import os
import pytest
import subprocess
import shutil

SPLIT_SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'split.py')

@pytest.fixture
def temp_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d

def create_gold_jsonl(path, records):
    with open(path, 'w') as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

def test_random_split_determinism(temp_dir):
    input_file = temp_dir / "gold.jsonl"
    out_dir = temp_dir / "out"
    
    # 10 files, each with 1 record
    records = []
    for i in range(10):
        records.append({"id": f"FILE=doc_{i}/P=0", "text": "foo", "entities": []})
    
    create_gold_jsonl(input_file, records)
    
    # Run once
    cmd = [
        "python3", SPLIT_SCRIPT,
        "--in", str(input_file),
        "--out-dir", str(out_dir),
        "--mode", "random",
        "--seed", "42",
        "--dev-ratio", "0.5"
    ]
    subprocess.check_call(cmd)
    
    with open(out_dir / "dev_files.txt") as f:
        dev1 = sorted(f.read().splitlines())
        
    # Run again
    subprocess.check_call(cmd)
    with open(out_dir / "dev_files.txt") as f:
        dev2 = sorted(f.read().splitlines())
        
    assert dev1 == dev2, "Random split must be deterministic with same seed"
    assert len(dev1) == 5

def test_no_leakage(temp_dir):
    input_file = temp_dir / "gold.jsonl"
    out_dir = temp_dir / "out"
    
    # 2 files, multiple paragraphs each
    records = [
        {"id": "FILE=A/P=1", "text": "p1", "entities": []},
        {"id": "FILE=A/P=2", "text": "p2", "entities": []},
        {"id": "FILE=B/P=1", "text": "p3", "entities": []},
        {"id": "FILE=B/P=2", "text": "p4", "entities": []},
    ]
    create_gold_jsonl(input_file, records)
    
    subprocess.check_call([
        "python3", SPLIT_SCRIPT,
        "--in", str(input_file),
        "--out-dir", str(out_dir),
        "--dev-ratio", "0.5",
        "--mode", "random"
    ])
    
    with open(out_dir / "dev_files.txt") as f:
        dev_files = set(f.read().splitlines())
    with open(out_dir / "test_files.txt") as f:
        test_files = set(f.read().splitlines())
        
    assert dev_files.isdisjoint(test_files), "Files must not overlap between splits"
    assert len(dev_files) + len(test_files) == 2

def test_stratified_split_rare_type(temp_dir):
    input_file = temp_dir / "gold.jsonl"
    out_dir = temp_dir / "out"
    
    # Needs to force a rare type into test even if ratios suggest otherwise?
    # Or at least check it tries to balance.
    
    # File A: 100 records, NO rare type
    # File B: 1 record, HAS rare type (SSN)
    
    # If we want dev_ratio 0.8:
    # A -> Dev (100 recs)
    # B -> Test (1 rec)
    # This naturally happens if we fill dev first.
    
    # Let's make it harder:
    # File A: 10 records (Dev target ~8)
    # File B: 2 records (SSN)
    
    # If random, B might end up in Dev.
    # We want to ensure SSN in Test if min_positives_test=1.
    
    records = []
    # File A (Common)
    for i in range(10):
        records.append({"id": f"FILE=A/P={i}", "text": "common", "entities": []})
        
    # File B (Rare)
    records.append({
        "id": "FILE=B/P=0", "text": "rare", 
        "entities": [{"type": "SSN", "start": 0, "end": 4}]
    })
    
    create_gold_jsonl(input_file, records)
    
    # Run Stratified
    subprocess.check_call([
        "python3", SPLIT_SCRIPT,
        "--in", str(input_file),
        "--out-dir", str(out_dir),
        "--mode", "stratified",
        "--allowed-types", "SSN,PERSON",
        "--rare-types", "SSN",
        "--min-positives-test", "1",
        "--dev-ratio", "0.8"
    ])
    
    # Check report
    with open(out_dir / "split_report.json") as f:
        report = json.load(f)
        
    test_counts = report["splits"]["test"]["counts"]
    assert test_counts.get("SSN", 0) >= 1, "Test set should have at least 1 SSN"
    
    # Verify file distribution
    with open(out_dir / "test_files.txt") as f:
        test_files = f.read().splitlines()
    assert "B" in test_files

def test_impossible_constraint(temp_dir):
    input_file = temp_dir / "gold.jsonl"
    out_dir = temp_dir / "out"
    
    # Only 1 file with SSN. 
    # If we demand min_positives_test=1, it must go to Test.
    # What if we have only 1 file TOTAL?
    
    records = [
        {"id": "FILE=A/P=0", "text": "rare", "entities": [{"type": "SSN", "start": 0, "end": 3}]}
    ]
    create_gold_jsonl(input_file, records)
    
    # Expect failure (exit code 1) because dev will be empty? 
    # Or successful but warning?
    # Actually if only 1 file, "Only 1 file found. Cannot split strictly." warning.
    # If split puts it in test, dev is empty. That's allowed but weird.
    
    # Let's test the repair logic failure case.
    # File A: SSN. File B: SSN. Dev ratio 0.9.
    # If min_positives_test=100 (HIGH). Impossible.
    
    records = [
        {"id": "FILE=A/P=0", "text": "rare", "entities": [{"type": "SSN", "start": 0, "end": 3}]},
        {"id": "FILE=B/P=0", "text": "rare", "entities": [{"type": "SSN", "start": 0, "end": 3}]}
    ]
    create_gold_jsonl(input_file, records)
    
    try:
        subprocess.check_call([
            "python3", SPLIT_SCRIPT,
            "--in", str(input_file),
            "--out-dir", str(out_dir),
            "--mode", "stratified",
            "--min-positives-test", "100" # Impossible
        ])
        failed = False
    except subprocess.CalledProcessError:
        failed = True
        
    assert failed, "Should fail with exit code 1 when constraints unsatisfiable"

