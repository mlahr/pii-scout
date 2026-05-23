import os
import json
import pytest
from unittest.mock import MagicMock, patch
import sys
import requests as requests_lib

# Add parent dir to path to import pii_detect
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pii_detect


class TestLoadOpenRouterModel:
    """Tests for load_openrouter_model function."""

    def test_missing_api_key_raises_error(self):
        """Should raise RuntimeError when API key is empty."""
        with pytest.raises(RuntimeError, match="OpenRouter API key is required"):
            pii_detect.load_openrouter_model(api_key="")

    @patch('requests.get')
    def test_successful_connection(self, mock_get):
        """Should return config dict on successful connection."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = pii_detect.load_openrouter_model(
            api_key="sk-test-key",
            base_url="https://openrouter.ai/api/v1",
            model_name="openai/gpt-4o-mini"
        )

        assert result["api_key"] == "sk-test-key"
        assert result["base_url"] == "https://openrouter.ai/api/v1"
        assert result["model"] == "openai/gpt-4o-mini"

    @patch('requests.get')
    def test_invalid_api_key(self, mock_get):
        """Should raise RuntimeError for 401 response."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = requests_lib.exceptions.HTTPError(response=mock_response)
        mock_get.return_value = mock_response

        with pytest.raises(RuntimeError, match="Invalid OpenRouter API key"):
            pii_detect.load_openrouter_model(api_key="bad-key")

    @patch('requests.get')
    def test_connection_error(self, mock_get):
        """Should raise RuntimeError on connection error."""
        mock_get.side_effect = requests_lib.exceptions.ConnectionError()

        with pytest.raises(RuntimeError, match="Cannot connect to OpenRouter"):
            pii_detect.load_openrouter_model(api_key="sk-test-key")


class TestRunOpenRouterDetection:
    """Tests for run_openrouter_detection function."""

    @patch('requests.post')
    def test_successful_detection(self, mock_post):
        """Should parse entities from valid API response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps([
                        {"type": "PERSON", "text": "John Smith", "start": 0, "end": 10}
                    ])
                }
            }]
        }
        mock_post.return_value = mock_response

        model_config = {
            "api_key": "sk-test-key",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openai/gpt-4o-mini"
        }
        text = "John Smith lives at 123 Main St"

        entities = pii_detect.run_openrouter_detection(model_config, text)

        assert len(entities) == 1
        assert entities[0]["type"] == "PERSON"
        assert entities[0]["text"] == "John Smith"
        assert entities[0]["start"] == 0
        assert entities[0]["end"] == 10
        assert "score" in entities[0]

    @patch('requests.post')
    def test_detection_with_missing_offsets(self, mock_post):
        """Should compute offsets when missing from response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps([
                        {"type": "PERSON", "text": "John Smith"}
                    ])
                }
            }]
        }
        mock_post.return_value = mock_response

        model_config = {
            "api_key": "sk-test-key",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openai/gpt-4o-mini"
        }
        text = "John Smith lives at 123 Main St"

        entities = pii_detect.run_openrouter_detection(model_config, text)

        assert len(entities) == 1
        assert entities[0]["start"] == 0
        assert entities[0]["end"] == 10

    @patch('requests.post')
    def test_rate_limit_returns_empty(self, mock_post):
        """Should return empty list on rate limit (429)."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status.side_effect = requests_lib.exceptions.HTTPError(response=mock_response)
        mock_post.return_value = mock_response

        model_config = {
            "api_key": "sk-test-key",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openai/gpt-4o-mini"
        }

        entities = pii_detect.run_openrouter_detection(model_config, "test text")

        assert entities == []

    @patch('requests.post')
    def test_malformed_json_returns_empty(self, mock_post):
        """Should return empty list when response is not valid JSON."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "This is not JSON"
                }
            }]
        }
        mock_post.return_value = mock_response

        model_config = {
            "api_key": "sk-test-key",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openai/gpt-4o-mini"
        }

        entities = pii_detect.run_openrouter_detection(model_config, "test text")

        assert entities == []

    @patch('requests.post')
    def test_invalid_entity_type_filtered(self, mock_post):
        """Should filter out entities with invalid types."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps([
                        {"type": "INVALID_TYPE", "text": "something", "start": 0, "end": 9},
                        {"type": "PERSON", "text": "John Smith", "start": 10, "end": 20}
                    ])
                }
            }]
        }
        mock_post.return_value = mock_response

        model_config = {
            "api_key": "sk-test-key",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openai/gpt-4o-mini"
        }
        text = "something John Smith lives here"

        entities = pii_detect.run_openrouter_detection(model_config, text)

        assert len(entities) == 1
        assert entities[0]["type"] == "PERSON"

    @patch('requests.post')
    def test_empty_response_returns_empty_list(self, mock_post):
        """Should return empty list for empty array response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "[]"
                }
            }]
        }
        mock_post.return_value = mock_response

        model_config = {
            "api_key": "sk-test-key",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openai/gpt-4o-mini"
        }

        entities = pii_detect.run_openrouter_detection(model_config, "no pii here")

        assert entities == []


class TestLoadModelsOpenRouter:
    """Tests for load_models with openrouter profile."""

    @patch('pii.pipeline.load_openrouter_model')
    def test_load_openrouter_model_called(self, mock_load):
        """Should call load_openrouter_model with correct args."""
        mock_load.return_value = {"api_key": "sk-test", "base_url": "https://test", "model": "test-model"}

        args = MagicMock()
        args.models = "openrouter"
        args.use_gpu = True
        args.openrouter_api_key = "sk-test-key"
        args.openrouter_base_url = "https://openrouter.ai/api/v1"
        args.openrouter_model = "openai/gpt-4o-mini"

        models = pii_detect.load_models(args)

        mock_load.assert_called_once_with("sk-test-key", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini")
        assert len(models) == 1
        model, ner_enabled, model_type = models[0]
        assert ner_enabled is True
        assert model_type == "openrouter"
