from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

from .bench import run_bench
from .eval import run_eval
from .pipeline import detect_pii, detect_pii_gateway, load_models

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    parser = argparse.ArgumentParser(description="PII Detection CLI")

    # Common Args
    parser.add_argument("--pretty", action="store_true", help="Pretty print JSON")
    parser.add_argument("--min-score", type=float, default=None, help="Minimum score threshold (default: from config)")
    parser.add_argument("--models", default=None,
                        help="Model profile(s), comma-separated: spacy-fast, spacy-accurate, piiranha, ollama, openrouter (default: from config or spacy-accurate)")
    parser.add_argument("--detectors", default="ner,regex,dict",
                        help="Comma-separated list of detectors to run: ner,regex,dict (default: all)")
    parser.add_argument("--entity-types", default=None,
                        help="Comma-separated entity types to return (default: all)")
    parser.add_argument("--language", default="en", help="Language code")
    parser.add_argument("--max-chars", type=int, default=200000, help="Max characters to process")
    parser.add_argument("--output", help="Output file path (standard mode)")

    # Ollama Args
    parser.add_argument("--ollama-base-url", default=None,
                        help="Ollama API base URL (default: from config or http://localhost:11434)")
    parser.add_argument("--ollama-model", default=None, help="Ollama model name (default: from config or llama3.2)")

    # OpenRouter Args
    parser.add_argument("--openrouter-api-key", default=os.environ.get("PII_OPENROUTER_API_KEY", ""),
                        help="OpenRouter API key")
    parser.add_argument("--openrouter-base-url", default=None,
                        help="OpenRouter API base URL (default: from config or https://openrouter.ai/api/v1)")
    parser.add_argument("--openrouter-model", default=None,
                        help="OpenRouter model name (required when using --models openrouter)")

    # Bench Args
    parser.add_argument("--bench", help="Benchmark mode: path to file or directory")
    parser.add_argument("--bench-glob", default="*.txt", help="Glob pattern for dir (default *.txt)")
    parser.add_argument("--bench-runs", type=int, default=1, help="Runs per corpus")
    parser.add_argument("--bench-warmup", type=int, default=3, help="Warmup pages")
    parser.add_argument("--bench-max-pages", type=int, default=0, help="Max pages total")
    parser.add_argument("--bench-seed", type=int, default=42, help="Seed for shuffle")
    parser.add_argument("--bench-shuffle", action="store_true", help="Shuffle files")
    parser.add_argument("--bench-profile", action="store_true", help="Enable per-file profiling")
    parser.add_argument("--bench-json", action="store_true", help="Output bench results as JSON")

    # Eval Args
    parser.add_argument("--eval", help="Evaluation mode: path to gold.jsonl")
    parser.add_argument("--gold-corrections", help="Path to gold corrections JSON file")
    parser.add_argument("--eval-max-records", type=int, default=0, help="Max records to evaluate (0=all)")
    parser.add_argument("--ids", help="Split IDs file (one per line)")
    parser.add_argument("--files", help="Split Files file (one per line)")
    parser.add_argument("--match", choices=["exact", "overlap", "hybrid"], default="hybrid", help="Match mode")
    parser.add_argument("--overlap-min-chars", type=int, default=1, help="Min overlap for match")
    parser.add_argument("--types",
                        default="PERSON,LOCATION,ADDRESS,SSN,PHONE_NUMBER,ACCOUNT_NUMBER,DATE,BIRTHDATE,EMAIL",
                        help="Comma-separated types")
    parser.add_argument("--report-dir", default=None, help="Report directory (default: eval_report/YYYY-MM-DD-HHMM-MODEL)")
    parser.add_argument("--write-fp", action="store_true", help="Dump false positives")
    parser.add_argument("--json", action="store_true", help="Print evaluation JSON summary to stdout")
    parser.add_argument("--max-errors", type=int, default=2000, help="Max error dump lines per type")
    parser.add_argument("--context", type=int, default=50, help="Context chars for error dump")
    parser.add_argument("--detailed-report", action="store_true",
                        help="Generate detailed HTML report with miss analysis")
    parser.add_argument("--report-format", choices=["html", "markdown"], default="html",
                        help="Format for detailed report")
    parser.add_argument("--max-examples", type=int, default=50, help="Max examples per category in detailed report")
    parser.add_argument("--proximity-threshold", type=int, default=50,
                        help="Char distance for near_miss categorization")
    parser.add_argument("--log", action="store_true",
                        help="Log whether gateway was triggered per document (requires --gateway)")
    parser.add_argument("--checkpoint-every", type=int, default=0,
                        help="Write fn/fp dump files every N records (0=disabled)")

    # Gateway mode
    parser.add_argument("--gateway", action="store_true", default=None,
                        help="Enable gateway mode (overrides config)")
    parser.add_argument("--no-gateway", action="store_true",
                        help="Disable gateway mode (overrides config)")

    # Config file
    parser.add_argument("--config", help="Path to PII config YAML file")

    args = parser.parse_args()

    # Enable debug logging if --log is set
    if args.log:
        logging.getLogger(__name__).setLevel(logging.DEBUG)

    # Load PII config
    pii_config = None
    try:
        from config.config_loader import load_config
        pii_config = load_config(path=args.config if args.config else None)
        logger.debug("PII config loaded")
    except FileNotFoundError as e:
        logger.error(f"Config file not found: {e}")
        sys.exit(1)
    except Exception as e:
        logger.debug(f"Config loading failed, using defaults: {e}")
        pii_config = None

    # Merge CLI args with config values (CLI overrides config)
    # Models: CLI -> config -> hardcoded default
    if args.models is None:
        args.models = pii_config.models.profile if pii_config else "spacy-accurate"
    if args.ollama_base_url is None:
        args.ollama_base_url = pii_config.models.ollama.base_url if pii_config else "http://localhost:11434"
    if args.ollama_model is None:
        args.ollama_model = pii_config.models.ollama.model if pii_config else "llama3.2"
    if args.openrouter_base_url is None:
        args.openrouter_base_url = pii_config.models.openrouter.base_url if pii_config else "https://openrouter.ai/api/v1"
    if args.openrouter_model is None:
        args.openrouter_model = pii_config.models.openrouter.model if pii_config else ""

    # Piiranha model path: env var -> config -> default
    args.piiranha_model_path = pii_config.models.piiranha.model_path if pii_config else None

    # Min score: CLI -> config -> 0.0
    if args.min_score is None:
        args.min_score = pii_config.scoring_rules.min_score if pii_config else 0.0

    # Gateway: --no-gateway forces False, --gateway forces True, else use config
    if args.no_gateway:
        args.gateway = False
    elif args.gateway is None:
        args.gateway = pii_config.gateway.enabled if pii_config else False

    # Load Model(s) (Global)
    try:
        models = load_models(args)
    except Exception as e:
        logger.error(f"Critical error loading models: {e}")
        sys.exit(1)

    # Log startup configuration
    model_types = ",".join(mt for _, _, mt in models)
    logger.debug(f"model: {args.models} (type={model_types})")
    if args.gateway:
        if pii_config and pii_config.gateway.tests:
            enabled_tests = [t.name for t in pii_config.gateway.tests if t.enabled]
            logger.debug(f"gateway: enabled, tests={enabled_tests}")
        else:
            logger.debug("gateway: enabled, tests=[consecutive_digits, name_dictionary]")
    else:
        logger.debug("gateway: disabled")

    # Initialize dictionary detector if needed
    if "dict" in args.detectors.lower().split(","):
        try:
            from detectors.name_dict_detector import initialize_detector

            # Get name list paths from config if provided
            init_kwargs = {}
            if pii_config and pii_config.name_lists:
                name_lists = pii_config.name_lists
                if name_lists.first_names:
                    init_kwargs['first_names_path'] = name_lists.first_names.source
                if name_lists.last_names:
                    init_kwargs['last_names_path'] = name_lists.last_names.source
                if name_lists.stopwords:
                    init_kwargs['stopwords_path'] = name_lists.stopwords.source

            initialize_detector(**init_kwargs)
        except Exception as e:
            logger.debug(f"Dictionary detector initialization failed: {e}")

    if args.bench:
        run_bench(args, models)
        sys.exit(0)

    # Set default report directory for eval mode
    if args.eval and args.report_dir is None:
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        args.report_dir = os.path.join("eval_report", f"{timestamp}-{args.models}")

    if args.eval:
        run_eval(args, models, pii_config)
        sys.exit(0)

    # Standard CLI Mode
    # Timing
    t0 = time.perf_counter()
    timings = {}

    # Read Input
    try:
        text = sys.stdin.read()
    except Exception as e:
        logger.error(f"Error reading stdin: {e}")
        sys.exit(1)

    if len(text) > args.max_chars:
        # Safety cap logic
        logger.warning(f"Input exceeds max-chars ({args.max_chars}). Truncating.")
        text = text[:args.max_chars]

    detectors = set(args.detectors.lower().split(","))

    # Parse entity types filter
    entity_types = None
    if args.entity_types:
        entity_types = {t.strip().upper() for t in args.entity_types.split(",")}

    # Use gateway mode if requested
    if args.gateway:
        ents, stats = detect_pii_gateway(text, models, args.min_score, detectors=detectors,
                                         config=pii_config, entity_types=entity_types)
    else:
        ents, stats = detect_pii(text, models, args.min_score, detectors=detectors,
                                 config=pii_config, entity_types=entity_types)
    timings.update(stats)

    # Safety-net: filter to requested entity types
    if entity_types:
        ents = [e for e in ents if e['type'] in entity_types]

    timings['total'] = (time.perf_counter() - t0) * 1000

    # Output structure
    output_data = {
        "meta": {
            "model_profile": args.models,
            "language": args.language,
            "chars": len(text),
            "gateway_mode": args.gateway,
            "gateway_skipped": stats.get('gateway_skipped', False)
        },
        "entities": ents
    }

    # Print timings to stderr
    print(json.dumps({"timing_ms": timings}), file=sys.stderr)

    # Print Output
    out_str = json.dumps(output_data, indent=2 if args.pretty else None)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(out_str)
    else:
        print(out_str)


if __name__ == "__main__":
    main()
