from __future__ import annotations

import json
import logging
import re
from typing import Dict, Any, List, Optional, Set

from .consts import SCORES

logger = logging.getLogger(__name__)


def load_openrouter_model(api_key: str, base_url: str = "https://openrouter.ai/api/v1",
                          model_name: str | None = None) -> dict:
    """
    Load OpenRouter model configuration.
    Returns a config dict with api_key, base_url, and model_name.
    """
    import requests

    if not api_key:
        raise RuntimeError("OpenRouter API key is required. Set PII_OPENROUTER_API_KEY or use --openrouter-api-key")

    logger.info(f"Connecting to OpenRouter at {base_url} with model {model_name}...")

    # Verify API connectivity
    try:
        resp = requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )
        resp.raise_for_status()
        logger.info("OpenRouter API connection verified.")
    except requests.exceptions.ConnectionError:
        raise RuntimeError(f"Cannot connect to OpenRouter at {base_url}")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            raise RuntimeError("Invalid OpenRouter API key")
        raise RuntimeError(f"OpenRouter API error: {e}")
    except Exception as e:
        logger.warning(f"Could not verify OpenRouter connection: {e}")

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model_name
    }


def run_openrouter_detection(model_config: dict, text: str, entity_types: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """
    Run PII detection using OpenRouter LLM (OpenAI-compatible API).
    Returns list of entity dicts with start, end, type, text, score.
    """
    import requests

    api_key = model_config["api_key"]
    base_url = model_config["base_url"]
    model = model_config["model"]

    all_types = ["PERSON", "SSN", "PHONE_NUMBER", "EMAIL", "ADDRESS", "DATE", "ACCOUNT_NUMBER", "LOCATION"]
    prompt_types = [t for t in all_types if not entity_types or t in entity_types] if entity_types else all_types
    types_str = ", ".join(prompt_types)
    prompt = f"""Extract personally identifiable information (PII) from the following text.
Return ONLY a valid JSON array of objects. Each object must have:
- "type": one of {types_str}
- "text": the exact text that was found
- "start": character offset where the entity starts (0-indexed)
- "end": character offset where the entity ends

If no PII is found, return an empty array: []"""

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"Text to analyze:\n{text}"}
                ],
                "temperature": 0.1,
                "max_tokens": 2048
            },
            timeout=120
        )
        resp.raise_for_status()
        result = resp.json()
        response_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        logger.debug(f"OpenRouter response: {response_text}")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            logger.error("OpenRouter rate limit exceeded")
        else:
            logger.error(f"OpenRouter API call failed: {e}")
        return []
    except Exception as e:
        logger.error(f"OpenRouter API call failed: {e}")
        return []

    # Parse the JSON response
    entities = []
    try:
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

                    valid_types = {"PERSON", "SSN", "PHONE_NUMBER", "EMAIL", "ADDRESS",
                                   "DATE", "ACCOUNT_NUMBER", "LOCATION", "BIRTHDATE"}
                    if entity_types:
                        valid_types = valid_types & entity_types
                    if entity_type not in valid_types:
                        continue

                    if start is None or end is None:
                        idx = text.find(entity_text)
                        if idx >= 0:
                            start = idx
                            end = idx + len(entity_text)
                        else:
                            continue

                    if not (isinstance(start, int) and isinstance(end, int)):
                        continue
                    if start < 0 or end > len(text) or start >= end:
                        continue

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
        logger.debug(f"Failed to parse OpenRouter response as JSON: {e}")
    except Exception as e:
        logger.debug(f"Error processing OpenRouter response: {e}")

    return entities
