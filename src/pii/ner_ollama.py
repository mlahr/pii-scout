from __future__ import annotations

import json
import logging
import re
from typing import Dict, Any, List, Optional, Set

from .consts import SCORES

logger = logging.getLogger(__name__)


def load_ollama_model(base_url: str = "http://localhost:11434", model_name: str = "llama3.2") -> dict:
    """
    Load Ollama model configuration.
    Returns a config dict with base_url and model_name.
    """
    import requests

    logger.info(f"Connecting to Ollama at {base_url} with model {model_name}...")

    # Verify Ollama is running
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        available_models = [m['name'] for m in resp.json().get('models', [])]

        # Check if model is available (handle tags like 'llama3.2:latest')
        model_available = any(
            model_name == m or model_name == m.split(':')[0]
            for m in available_models
        )

        if not model_available:
            logger.warning(f"Model '{model_name}' not found. Available: {available_models}")
            logger.warning("You may need to run: ollama pull " + model_name)
    except requests.exceptions.ConnectionError:
        raise RuntimeError(f"Cannot connect to Ollama at {base_url}. Is Ollama running?")
    except Exception as e:
        logger.warning(f"Could not verify Ollama models: {e}")

    logger.info("Ollama model configured successfully.")
    return {
        "base_url": base_url,
        "model": model_name
    }


def run_ollama_detection(model_config: dict, text: str, entity_types: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """
    Run PII detection using Ollama LLM.
    Returns list of entity dicts with start, end, type, text, score.
    """
    import requests

    base_url = model_config["base_url"]
    model = model_config["model"]

    # Build the prompt for entity extraction
    all_types = ["PERSON", "SSN", "PHONE_NUMBER", "EMAIL", "ADDRESS", "DATE", "ACCOUNT_NUMBER", "LOCATION"]
    prompt_types = [t for t in all_types if not entity_types or t in entity_types] if entity_types else all_types
    types_str = ", ".join(prompt_types)
    prompt = f"""Extract personally identifiable information (PII) from the following text.
Return ONLY a valid JSON array of objects. Each object must have:
- "type": one of {types_str}
- "text": the exact text that was found
- "start": character offset where the entity starts (0-indexed)
- "end": character offset where the entity ends

If no PII is found, return an empty array: []

Text to analyze:
{text}

JSON array of PII entities:"""

    try:
        resp = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 2048
                }
            },
            timeout=120
        )
        resp.raise_for_status()
        result = resp.json()
        response_text = result.get("response", "")
        print(response_text)
    except Exception as e:
        logger.error(f"Ollama API call failed: {e}")
        return []

    # Parse the JSON response
    entities = []
    try:
        # Find JSON array in response (handle potential markdown code blocks)
        json_match = re.search(r'\[[\s\S]*?\]', response_text)
        if json_match:
            parsed = json.loads(json_match.group())
            if isinstance(parsed, list):
                for item in parsed:
                    if not isinstance(item, dict):
                        continue

                    entity_type = item.get("type", "")
                    entity_text = item.get("text", "")
                    start = item.get("start")
                    end = item.get("end")

                    # Validate entity type
                    valid_types = {"PERSON", "SSN", "PHONE_NUMBER", "EMAIL", "ADDRESS",
                                   "DATE", "ACCOUNT_NUMBER", "LOCATION", "BIRTHDATE"}
                    if entity_types:
                        valid_types = valid_types & entity_types
                    if entity_type not in valid_types:
                        continue

                    # If start/end not provided, try to find the text in the original
                    if start is None or end is None:
                        idx = text.find(entity_text)
                        if idx >= 0:
                            start = idx
                            end = idx + len(entity_text)
                        else:
                            continue

                    # Validate offsets
                    if not (isinstance(start, int) and isinstance(end, int)):
                        continue
                    if start < 0 or end > len(text) or start >= end:
                        continue

                    # Use base score from SCORES dict
                    score = SCORES.get(entity_type, 0.75)

                    entities.append({
                        "type": entity_type,
                        "text": entity_text,
                        "start": start,
                        "end": end,
                        "score": round(score, 2),
                        "source": "ner"
                    })
    except json.JSONDecodeError as e:
        logger.debug(f"Failed to parse Ollama response as JSON: {e}")
    except Exception as e:
        logger.debug(f"Error processing Ollama response: {e}")

    return entities
