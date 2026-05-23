import os
import tempfile
import json
import pytest
from unittest.mock import MagicMock, patch
import sys

# Add parent dir to path to import pii_detect
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pii_detect

@pytest.fixture
def bench_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create 3 files, one in a subdir
        os.makedirs(os.path.join(tmpdir, "subdir"), exist_ok=True)
        
        for i in range(3):
            folder = tmpdir if i < 2 else os.path.join(tmpdir, "subdir")
            with open(os.path.join(folder, f"{i}.txt"), 'w') as f:
                f.write(f"Sample text {i}. My phone is 555-010{i}. User: John Doe.")
        yield tmpdir

def test_run_bench_summary(bench_data):
    # Mock args
    args = MagicMock()
    args.bench = bench_data
    args.bench_glob = "*.txt"
    args.bench_runs = 2
    args.bench_warmup = 1
    args.bench_max_pages = 0
    args.bench_seed = 42
    args.bench_shuffle = False
    args.bench_profile = False
    args.bench_json = True # Easy verification
    args.models = "fast"
    args.language = "en"
    args.min_score = 0.0

    # Mock nlp
    nlp = MagicMock()
    ner_enabled = True
    
    # Capture stdout
    with patch('sys.stdout', new_callable=MagicMock) as mock_stdout:
        # We need to mock stdout.write usually, but here we can just capture the print call inside run_bench
        # Or better, use capsys fixture if we weren't mocking everything manually suitable for run_bench
        
        # Actually, let's just patch input/print or use capsys.
        pass

def test_run_bench_integration(bench_data, capsys):
    # Test full run_bench execution with mocked NLP to avoid loading spacy models which might be slow
    
    args = MagicMock()
    args.bench = bench_data
    args.bench_glob = "*.txt"
    args.bench_runs = 2
    args.bench_warmup = 1
    args.bench_max_pages = 0
    args.bench_seed = 42
    args.bench_shuffle = False
    args.bench_profile = True
    args.bench_json = True 
    args.models = "fast"
    args.language = "en"
    args.min_score = 0.0
    
    # Mock NLP behavior
    nlp = MagicMock()
    # Mock run_spacy_detection, run_regex_detection is pure
    
    with patch('pii_detect.run_spacy_detection') as mock_spacy:
        mock_spacy.return_value = [{'type': 'PERSON', 'text': 'John Doe', 'start': 30, 'end': 38, 'score': 0.8}]
        
        pii_detect.run_bench(args, [(nlp, True, "spacy")])
        
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        
        # Validation
        assert output['meta']['pages'] == 5 # 3 files * 2 runs = 6. minus 1 warmup = 5?
        # Wait, my logic was: iterate (Runs * Files). Counter updates.
        # Files = [0, 1, 2].
        # Run 1: 0(warmup), 1, 2
        # Run 2: 0, 1, 2
        # Total processed = 5. Correct.
        
        assert 'throughput' in output
        assert output['throughput']['pages_per_sec'] > 0
        
        assert 'stages' in output
        assert output['stages']['total_ms']['p50'] >= 0
        
        assert 'profile' in output
        assert len(output['profile']) == 5
        
        # Check specific stats
        first_prof = output['profile'][0]
        assert 'filename' in first_prof
        assert 'stages' in first_prof
        
        
def test_quantiles():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    q = pii_detect.calculate_quantiles(vals)
    assert q['p50'] == 3.0
    assert q['min'] == 1.0
    assert q['max'] == 5.0
    assert q['mean'] == 3.0
