import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo_root / "src"))

import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app
from api.routers import health, detect


@pytest.fixture
def mock_pii_service():
    """Mock PII service for fast unit tests."""
    mock = MagicMock()
    mock.is_ready = True
    mock.model_profile = "fast"
    mock.model_type = "spacy"
    mock._loaded = True
    mock.detect.return_value = (
        [
            {"type": "PERSON", "text": "John", "start": 0, "end": 4, "score": 0.85},
            {"type": "SSN", "text": "123-45-6789", "start": 10, "end": 21, "score": 0.99}
        ],
        {
            "normalize_ms": 0.1,
            "ner_ms": 5.0,
            "regex_ms": 1.0,
            "merge_ms": 0.1,
            "total_ms": 6.3
        }
    )
    return mock


@pytest.fixture
def client(mock_pii_service):
    """Test client with mocked service.

    Patches PIIService.load() to prevent the real model from loading during tests.
    """
    with patch('api.services.pii_service.PIIService.load'):
        with TestClient(app, raise_server_exceptions=False) as c:
            # Override with mock service for actual test calls
            health.set_pii_service(mock_pii_service)
            detect.set_pii_service(mock_pii_service)
            yield c
