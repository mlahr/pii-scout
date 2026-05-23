# REST API

pii-scout includes a FastAPI service for PII detection.

## Build

Local development:

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_lg
```

Docker:

```bash
docker build -t pii-scout .
docker-compose build
```

## Model Image Workflow

The repo can build a dedicated model image that bakes in SpaCy and Piiranha
models. The app image can then use that image as its base.

```bash
docker build -f Dockerfile.models -t models-latest .
docker build --build-arg MODEL_IMAGE=models-latest -t pii-scout .
```

To use a prebuilt GHCR model image:

```bash
docker pull ghcr.io/mlahr/pii-scout:models-latest
docker build --build-arg MODEL_IMAGE=ghcr.io/mlahr/pii-scout:models-latest -t pii-scout .
```

To build and push the model image locally:

```bash
docker login ghcr.io
./scripts/build_push_model_image.sh
```

## Run

Local:

```bash
uvicorn api.main:app --reload --port 9000
PII_MODEL_PROFILE=accurate uvicorn api.main:app --reload --port 9000
uvicorn api.main:app --host 0.0.0.0 --port 9000
```

Docker:

```bash
docker-compose up
docker run -p 8000:8000 pii-scout
docker run -e PII_MODEL_PROFILE=accurate -p 8000:8000 pii-scout
```

Ollama:

```bash
PII_MODEL_PROFILE=ollama PII_OLLAMA_MODEL=llama3 uvicorn api.main:app --port 9000
```

OpenRouter:

```bash
PII_MODEL_PROFILE=openrouter \
PII_OPENROUTER_API_KEY=sk-xxx \
PII_OPENROUTER_MODEL=openai/gpt-4o-mini \
uvicorn api.main:app --port 9000
```

## Endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/health` | GET | Liveness probe |
| `/ready` | GET | Readiness probe with model status |
| `/info` | GET | API version, entity types, and config |
| `/detect` | POST | Detect PII in text |
| `/entity-types` | GET | Entity types supported by the loaded configuration |

Interactive docs:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Detect Request

```bash
curl -X POST http://localhost:8000/detect \
  -H "Content-Type: application/json" \
  -d '{"text": "John Smith SSN 123-45-6789"}'
```

Response:

```json
{
  "entities": [
    {"type": "PERSON", "text": "John Smith", "start": 0, "end": 10, "score": 0.8, "source": ["ner"]},
    {"type": "SSN", "text": "123-45-6789", "start": 15, "end": 26, "score": 0.99, "source": ["regex"]}
  ],
  "meta": {
    "model_profile": "spacy-fast",
    "chars": 26,
    "entity_count": 2,
    "gateway_mode": true,
    "gateway_skipped": false
  },
  "stats": null
}
```

Request fields:

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `text` | string | required | Text to analyze |
| `min_score` | float | config default | Minimum confidence threshold |
| `include_stats` | bool | false | Include timing stats |
| `gateway` | bool | config default | Skip full detection when gateway tests find no likely PII |
| `entity_types` | string[] | all | Return only selected entity types |
| `detectors` | string[] | all | Detectors to run: `ner`, `regex`, `dict` |
| `config_override` | object | none | Request-scoped config overrides |

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `PII_MODEL_PROFILE` | `spacy-fast` | Model profile |
| `PII_MAX_TEXT_LENGTH` | `500000` | Maximum text length |
| `PII_LOG_LEVEL` | `INFO` | Logging level |
| `PII_PORT` | `8000` | Server port |
| `PII_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `PII_OLLAMA_MODEL` | `llama3.2` | Ollama model name |
| `PII_OPENROUTER_API_KEY` | none | OpenRouter API key |
| `PII_OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API endpoint |
| `PII_OPENROUTER_MODEL` | none | OpenRouter model name |
| `PII_PIIRANHA_MODEL_PATH` | none | Hugging Face model ID or local Piiranha path |

## API Tests

```bash
python -m pytest src/api/tests/ -v
python -m pytest src/api/tests/ -v --cov=api
```
