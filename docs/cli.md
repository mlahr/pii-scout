# CLI

The main command is `pii_detect.py`. It supports stdin detection, benchmarking,
and evaluation.

## Basic Usage

```bash
cat examples/sample_input.txt | python pii_detect.py --pretty
```

Example input:

```text
My social security number is 123-45-6789.
```

Example output:

```json
{
  "meta": { "model_profile": "fast", "language": "en", "chars": 42 },
  "entities": [
    {
      "type": "SSN",
      "text": "123-45-6789",
      "start": 29,
      "end": 40,
      "score": 1.05
    }
  ]
}
```

## Options

- `--pretty`: Pretty-print JSON output.
- `--min-score <float>`: Filter entities by minimum confidence score.
- `--models <profile>`: Select model profile.
- `--detectors <list>`: Comma-separated detector list: `ner`, `regex`, `dict`.
- `--entity-types <list>`: Return only selected entity types.
- `--gateway`: Enable gateway mode.
- `--no-gateway`: Disable gateway mode.
- `--max-chars <int>`: Cap input size.
- `--output <path>`: Write output to file instead of stdout.
- `--config <path>`: Use a specific PII config YAML file.

## Model Profiles

| Profile | Model | Description |
| --- | --- | --- |
| `spacy-fast` / `fast` | `en_core_web_lg` | Fast SpaCy model, lower accuracy |
| `spacy-accurate` / `accurate` | `en_core_web_trf` | Transformer-based SpaCy, higher accuracy |
| `piiranha` | `iiiorg/piiranha-v1-detect-personal-information` | Hugging Face model |
| `ollama` | configurable | Local LLM through Ollama |
| `openrouter` | configurable | Cloud LLM through OpenRouter |

## Ollama

```bash
ollama serve
ollama pull llama3
echo "John Smith, SSN 123-45-6789" \
  | python pii_detect.py --models ollama --ollama-model llama3
```

Options:

- `--ollama-base-url <url>`: Ollama API base URL.
- `--ollama-model <name>`: Ollama model name.

## OpenRouter

```bash
export PII_OPENROUTER_API_KEY=sk-xxx
echo "John Smith" \
  | python pii_detect.py --models openrouter --openrouter-model openai/gpt-4o-mini
```

Options:

- `--openrouter-api-key <key>`: OpenRouter API key.
- `--openrouter-base-url <url>`: OpenRouter API base URL.
- `--openrouter-model <name>`: OpenRouter model name.

## Gateway Mode

Gateway mode skips expensive model calls when lightweight tests find no likely
PII. Emails and dates are still detected through regex.

```bash
echo "Contact: test@example.com" \
  | python pii_detect.py --gateway --models spacy-fast --pretty
```

The output metadata includes:

```json
{
  "meta": {
    "gateway_mode": true,
    "gateway_skipped": true
  }
}
```

When `gateway_skipped` is `true`, the expensive NER model was not called.

## Benchmarking

```bash
python pii_detect.py --bench /path/to/corpus --bench-runs 3 --bench-warmup 1
```

Benchmark options:

- `--bench <path>`: Path to a file or directory of `.txt` files.
- `--bench-glob <pattern>`: Glob pattern for directory search.
- `--bench-runs <int>`: Number of times to process the corpus.
- `--bench-warmup <int>`: Number of initial files to process as warmup.
- `--bench-max-pages <int>`: Limit total files to process.
- `--bench-shuffle`: Shuffle file order before processing.
- `--bench-profile`: Enable per-file timing breakdown.
- `--bench-json`: Output results as JSON.

## Testing

```bash
python -m pytest
```
