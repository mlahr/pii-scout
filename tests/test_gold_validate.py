import pytest
import json
import os
from gold_validate import validate_record, fix_record, parse_args

# Mock args
class MockArgs:
    def __init__(self, **kwargs):
        self.require_text_field = False
        self.strict = False
        self.__dict__.update(kwargs)

DEFAULT_ALLOWED = {"PERSON", "LOCATION"}

def test_valid_record():
    record = {
        "id": "doc1",
        "text": "Hello John",
        "entities": [{"type": "PERSON", "start": 6, "end": 10}]
    }
    issues = validate_record(1, record, MockArgs(), DEFAULT_ALLOWED)
    assert len(issues) == 0

def test_out_of_bounds():
    record = {
        "id": "doc1",
        "text": "Hello",
        "entities": [{"type": "PERSON", "start": 10, "end": 15}]
    }
    issues = validate_record(1, record, MockArgs(), DEFAULT_ALLOWED)
    assert len(issues) == 1
    assert issues[0]["code"] == "BAD_OFFSETS"

def test_missing_text_allowed_vs_required():
    record = {"id": "doc1", "entities": []}
    
    # Allowed missing text (warn)
    issues_warn = validate_record(1, record, MockArgs(require_text_field=False), DEFAULT_ALLOWED)
    assert any(i["code"] == "MISSING_TEXT" and i["level"] == "WARNING" for i in issues_warn)
    
    # Required missing text (error)
    issues_err = validate_record(1, record, MockArgs(require_text_field=True), DEFAULT_ALLOWED)
    assert any(i["code"] == "MISSING_TEXT" and i["level"] == "ERROR" for i in issues_err)

def test_fix_whitespace():
    record = {
        "id": "fix1",
        "text": "  John Doe  ",
        "entities": [{"type": "PERSON", "start": 1, "end": 11}] # " John Doe "
    }
    # Validate first to see error
    issues = validate_record(1, record, MockArgs(), DEFAULT_ALLOWED)
    assert any(i["code"] == "WHITESPACE_SPAN" for i in issues)
    
    # Fix
    fixed = fix_record(record)
    ent = fixed["entities"][0]
    # Expected: "John Doe" (indices 2 to 10)
    assert ent["start"] == 2
    assert ent["end"] == 10
    assert ent["text"] == "John Doe"

def test_fix_deduplication():
    record = {
        "id": "dup1",
        "text": "John John",
        "entities": [
            {"type": "PERSON", "start": 0, "end": 4},
            {"type": "PERSON", "start": 0, "end": 4}, # Duplicate
            {"type": "PERSON", "start": 5, "end": 9}
        ]
    }
    fixed = fix_record(record)
    assert len(fixed["entities"]) == 2
    # Check sorting too (0,4) should be before (5,9)
    assert fixed["entities"][0]["start"] == 0
    assert fixed["entities"][1]["start"] == 5

def test_entities_missing():
    record = {"id": "no_ents", "text": "foo"}
    issues = validate_record(1, record, MockArgs(), DEFAULT_ALLOWED)
    assert len(issues) == 1
    assert issues[0]["code"] == "MISSING_ENTITIES"
    # Should treat as empty list effectively in processing logic, no crash
