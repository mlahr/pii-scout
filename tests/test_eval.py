
import json
import pytest
import os
from unittest.mock import MagicMock, patch
import pii_detect

# --- Tests for Match Logic ---

def test_match_entities_exact():
    # Gold: [10-20], Pred: [10-20] -> Match
    gold = [{"start": 10, "end": 20}]
    pred = [{"start": 10, "end": 20}]
    matches, fn, fp = pii_detect.match_entities(gold, pred, "exact", 1)
    
    assert len(matches) == 1
    assert len(fn) == 0
    assert len(fp) == 0
    assert matches[0][0] == gold[0]
    assert matches[0][1] == pred[0]

def test_match_entities_overlap_threshold():
    # Gold: [10-20] length 10
    # Pred: [15-25] length 10
    # Overlap: [15-20] length 5
    
    gold = [{"start": 10, "end": 20}]
    pred = [{"start": 15, "end": 25}]
    
    # Overlap min 1 -> Match
    matches, fn, fp = pii_detect.match_entities(gold, pred, "overlap", 1)
    assert len(matches) == 1
    
    # Overlap min 6 -> No match
    matches, fn, fp = pii_detect.match_entities(gold, pred, "overlap", 6)
    assert len(matches) == 0
    assert len(fn) == 1
    assert len(fp) == 1

def test_match_entities_greedy_one_to_one():
    # Gold 1: [0-10]
    # Gold 2: [5-15]
    # Pred 1: [2-8] (overlaps both)
    
    # If overlap matching:
    # Pred 1 overlaps Gold 1 by 6 (2-8)
    # Pred 1 overlaps Gold 2 by 3 (5-8)
    # Should match Gold 1 because score is higher (overlap length)
    
    g1 = {"id": "g1", "start": 0, "end": 10}
    g2 = {"id": "g2", "start": 5, "end": 15}
    p1 = {"id": "p1", "start": 2, "end": 8}
    
    matches, fn, fp = pii_detect.match_entities([g1, g2], [p1], "overlap", 1)
    
    assert len(matches) == 1
    assert matches[0][0] == g1
    assert matches[0][1] == p1
    assert len(fn) == 1
    assert fn[0] == g2
    assert len(fp) == 0

def test_match_priority_length():
    # Tie breaking by gold length
    # Pred 1 overlaps Gold 1 (len 10) by 5
    # Pred 1 overlaps Gold 2 (len 20) by 5
    # Should pick Gold 2
    
    g1 = {"start": 0, "end": 10}
    g2 = {"start": 0, "end": 20}
    p1 = {"start": 0, "end": 5}
    
    matches, fn, fp = pii_detect.match_entities([g1, g2], [p1], "overlap", 1)
    
    assert len(matches) == 1
    assert matches[0][0] == g2

# --- End-to-End Eval Test ---

def test_eval_e2e(tmp_path):
    # Setup Gold
    gold_data = [
        {"id": "FILE=A/1", "text": "Hello John Doe", "entities": [{"type": "PERSON", "start": 6, "end": 14}]}, # Match
        {"id": "FILE=A/2", "text": "Nothing here", "entities": []}, # Clean
        {"id": "FILE=B/1", "text": "Secret 123", "entities": [{"type": "SSN", "start": 7, "end": 10}]} # FN (missed)
    ]
    gold_file = tmp_path / "gold.jsonl"
    with open(gold_file, "w") as f:
        for r in gold_data:
            f.write(json.dumps(r) + "\n")
            
    # Setup IDs
    ids_file = tmp_path / "ids.txt"
    with open(ids_file, "w") as f:
        f.write("FILE=A/1\n")
        f.write("FILE=A/2\n")
        f.write("FILE=B/1\n")

    # Mock Detector to control predictions
    # detect_pii returns (ents, stats)
    def mock_detect(text, *args, **kwargs):
        if "John Doe" in text:
            # Predict "John Doe" exactly
            return [{"type": "PERSON", "start": 6, "end": 14, "score": 0.9}], {}
        if "Nothing here" in text:
            # Predict nothing
            return [], {}
        if "Secret" in text:
            # Predict nothing -> FN
            return [], {}
        return [], {}

    with patch("pii_detect.detect_pii", side_effect=mock_detect):
        # Args
        args = MagicMock()
        args.eval = str(gold_file)
        args.ids = str(ids_file)
        args.files = None
        args.match = "hybrid"
        args.overlap_min_chars = 1
        args.types = "PERSON,SSN"
        args.report_dir = str(tmp_path / "report")
        args.write_fp = True
        args.json = True
        args.pretty = False
        args.min_score = 0.5
        args.max_errors = 10
        args.context = 10
        args.max_examples = 50
        args.detectors = "ner,regex,dict"
        args.checkpoint_every = 0
        args.gold_corrections = None
        args.eval_max_records = 0

        # We need to capture stdout to verify JSON
        # Since run_eval prints to verify
        # We can just run it and check side effects (files)
        
        pii_detect.run_eval(args, [(None, True, "spacy")])
        
        # Check Output Report
        fn_file = tmp_path / "report" / "fn_SSN.jsonl"
        assert fn_file.exists()
        with open(fn_file) as f:
            fns = [json.loads(line) for line in f]
            assert len(fns) == 1
            assert fns[0]['type'] == 'SSN'
            # Check context bracket
            assert "[[123]]" in fns[0]['context']


def test_eval_checkpoint(tmp_path):
    """Test that --checkpoint-every writes incremental dump files."""
    # Setup Gold with 5 records that will produce FNs
    gold_data = [
        {"id": f"FILE=A/{i}", "text": f"Text with SSN {i}12", "entities": [{"type": "SSN", "start": 14, "end": 17}]}
        for i in range(5)
    ]
    gold_file = tmp_path / "gold.jsonl"
    with open(gold_file, "w") as f:
        for r in gold_data:
            f.write(json.dumps(r) + "\n")

    # Setup IDs
    ids_file = tmp_path / "ids.txt"
    with open(ids_file, "w") as f:
        for i in range(5):
            f.write(f"FILE=A/{i}\n")

    # Mock Detector to return nothing (all FN)
    def mock_detect(text, *args, **kwargs):
        return [], {}

    with patch("pii_detect.detect_pii", side_effect=mock_detect):
        args = MagicMock()
        args.eval = str(gold_file)
        args.ids = str(ids_file)
        args.files = None
        args.match = "hybrid"
        args.overlap_min_chars = 1
        args.types = "SSN"
        args.report_dir = str(tmp_path / "report")
        args.write_fp = False
        args.json = True
        args.pretty = False
        args.min_score = 0.5
        args.max_errors = 100
        args.context = 10
        args.max_examples = 50
        args.detectors = "ner,regex,dict"
        args.checkpoint_every = 2  # Checkpoint every 2 records
        args.gold_corrections = None
        args.eval_max_records = 0

        pii_detect.run_eval(args, [(None, True, "spacy")])

        # Check Output Report
        fn_file = tmp_path / "report" / "fn_SSN.jsonl"
        assert fn_file.exists()
        with open(fn_file) as f:
            fns = [json.loads(line) for line in f]
            # Should have 5 FNs (all records missed)
            assert len(fns) == 5


# --- Tests for Gold Corrections ---

def test_load_gold_corrections_nonexistent():
    """Loading non-existent corrections file returns empty dict."""
    result = pii_detect.load_gold_corrections("/nonexistent/path.json")
    assert result == {"remove_entities": []}


def test_load_gold_corrections_none():
    """Loading None path returns empty dict."""
    result = pii_detect.load_gold_corrections(None)
    assert result == {"remove_entities": []}


def test_load_gold_corrections_valid(tmp_path):
    """Loading valid corrections file returns corrections."""
    corrections = {
        "remove_entities": [
            {"id": "test_1", "type": "BIRTHDATE", "start": 50, "end": 60}
        ]
    }
    path = tmp_path / "corrections.json"
    with open(path, "w") as f:
        json.dump(corrections, f)

    result = pii_detect.load_gold_corrections(str(path))
    assert len(result["remove_entities"]) == 1
    assert result["remove_entities"][0]["id"] == "test_1"


def test_apply_gold_corrections_removes_entity():
    """apply_gold_corrections removes matching entities."""
    record = {
        "id": "test_1",
        "text": "some text",
        "entities": [
            {"type": "BIRTHDATE", "start": 50, "end": 60},
            {"type": "PERSON", "start": 10, "end": 20}
        ]
    }
    corrections = {
        "remove_entities": [
            {"id": "test_1", "type": "BIRTHDATE", "start": 50, "end": 60}
        ]
    }

    result = pii_detect.apply_gold_corrections(record, corrections)

    assert len(result["entities"]) == 1
    assert result["entities"][0]["type"] == "PERSON"


def test_apply_gold_corrections_no_match():
    """apply_gold_corrections keeps entities when no match."""
    record = {
        "id": "test_1",
        "text": "some text",
        "entities": [
            {"type": "BIRTHDATE", "start": 50, "end": 60}
        ]
    }
    corrections = {
        "remove_entities": [
            {"id": "test_2", "type": "BIRTHDATE", "start": 50, "end": 60}  # Different ID
        ]
    }

    result = pii_detect.apply_gold_corrections(record, corrections)

    assert len(result["entities"]) == 1


def test_apply_gold_corrections_empty_corrections():
    """apply_gold_corrections with empty corrections keeps all entities."""
    record = {
        "id": "test_1",
        "text": "some text",
        "entities": [
            {"type": "BIRTHDATE", "start": 50, "end": 60}
        ]
    }
    corrections = {"remove_entities": []}

    result = pii_detect.apply_gold_corrections(record, corrections)

    assert len(result["entities"]) == 1
