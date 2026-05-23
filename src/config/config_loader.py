"""Configuration loader for PII detection."""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

import yaml

from .pii_config import PIIConfig, SourceRef

logger = logging.getLogger(__name__)

# Module-level cache
_cached_config: Optional[PIIConfig] = None
_cached_path: Optional[str] = None

# Default search paths for config file
DEFAULT_SEARCH_PATHS = [
    "./pii_config.yaml",
    "./config/pii_config.yaml",
    "~/.pii_config.yaml",
]


def load_source_file(source_path: str, config_dir: Path) -> List[str]:
    """
    Load items from an external file (txt or json).

    Args:
        source_path: Path to the source file (relative to config_dir or absolute)
        config_dir: Directory containing the config file (for relative path resolution)

    Returns:
        List of strings loaded from the file

    Raises:
        FileNotFoundError: If the source file doesn't exist
        ValueError: If the file format is unsupported or invalid

    File formats:
        - .txt: One item per line, empty lines and # comments are ignored
        - .json: Must contain a JSON array of strings
    """
    # Resolve path relative to config dir if not absolute
    path = Path(source_path)
    if not path.is_absolute():
        path = config_dir / path

    path = path.resolve()

    if not path.exists():
        # Fallbacks for src/ layout: try repo root and repo_root/src
        repo_root = Path(__file__).resolve().parents[2]
        rel_path = Path(source_path)
        if not rel_path.is_absolute():
            for base in (repo_root, repo_root / "src"):
                candidate = (base / rel_path).resolve()
                if candidate.exists():
                    path = candidate
                    break

    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")

    suffix = path.suffix.lower()

    if suffix == '.json':
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"JSON source file must contain an array: {path}")
        # Ensure all items are strings
        return [str(item) for item in data]

    elif suffix == '.txt':
        items = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                items.append(line)
        return items

    else:
        raise ValueError(f"Unsupported source file format '{suffix}': {path}. Use .txt or .json")


def resolve_sources(config: PIIConfig, config_dir: Path) -> PIIConfig:
    """
    Resolve all SourceRef instances in the config, replacing them with loaded content.

    This function walks through patterns and context_keywords, loading any external
    source files and replacing SourceRef objects with the actual list of strings.

    Args:
        config: PIIConfig instance with potential SourceRef values
        config_dir: Directory containing the config file (for relative path resolution)

    Returns:
        New PIIConfig with all sources resolved to List[str]

    Raises:
        FileNotFoundError: If any source file doesn't exist
        ValueError: If any source file has invalid format
    """
    config_dict = config.model_dump()

    # Resolve patterns
    if 'patterns' in config_dict:
        resolved_patterns = {}
        for entity_type, value in config_dict['patterns'].items():
            if isinstance(value, dict) and 'source' in value:
                # It's a SourceRef
                source_path = value['source']
                logger.debug(f"Loading patterns for {entity_type} from {source_path}")
                resolved_patterns[entity_type] = load_source_file(source_path, config_dir)
            else:
                # It's already a list
                resolved_patterns[entity_type] = value
        config_dict['patterns'] = resolved_patterns

    # Resolve context_keywords
    if 'context_keywords' in config_dict:
        resolved_keywords = {}
        for entity_type, value in config_dict['context_keywords'].items():
            if isinstance(value, dict) and 'source' in value:
                # It's a SourceRef
                source_path = value['source']
                logger.debug(f"Loading context keywords for {entity_type} from {source_path}")
                resolved_keywords[entity_type] = load_source_file(source_path, config_dir)
            else:
                # It's already a list
                resolved_keywords[entity_type] = value
        config_dict['context_keywords'] = resolved_keywords

    # Note: name_lists SourceRefs are NOT resolved here - they are passed through
    # to be used by the name_dict_detector initialization which handles its own loading

    return PIIConfig(**config_dict)


def get_default_config() -> PIIConfig:
    """Return a new PIIConfig with all defaults."""
    return PIIConfig()


def load_config(path: Optional[str] = None, use_cache: bool = True) -> PIIConfig:
    """
    Load PII configuration from YAML file.

    Args:
        path: Explicit path to config file. If None, searches default paths.
        use_cache: If True, return cached config if available for same path.

    Returns:
        PIIConfig instance with loaded or default values.

    Search order (when path is None):
        1. ./pii_config.yaml
        2. ./config/pii_config.yaml
        3. ~/.pii_config.yaml

    If no config file is found, returns default configuration.
    """
    global _cached_config, _cached_path

    # Check cache
    if use_cache and _cached_config is not None:
        if path is None or path == _cached_path:
            logger.debug("Using cached PII config")
            return _cached_config

    # Determine config path
    config_path = None
    if path:
        config_path = Path(path).expanduser()
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
    else:
        # Search default paths
        for search_path in DEFAULT_SEARCH_PATHS:
            candidate = Path(search_path).expanduser()
            if candidate.exists():
                config_path = candidate
                logger.debug(f"Found config file at {config_path}")
                break

    # Load config or use defaults
    if config_path and config_path.exists():
        logger.debug(f"Loading PII config from {config_path}")
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if data is None:
            data = {}

        config = PIIConfig(**data)

        # Resolve external sources (patterns, context_keywords from files)
        config_dir = config_path.parent
        config = resolve_sources(config, config_dir)

        logger.debug("PII config loaded from file")
    else:
        logger.debug("No config file found, using defaults")
        config = get_default_config()

    # Cache the result
    _cached_config = config
    _cached_path = str(config_path) if config_path else None

    return config


def reset_config() -> None:
    """Reset the cached configuration. Useful for testing."""
    global _cached_config, _cached_path
    _cached_config = None
    _cached_path = None
    logger.debug("PII config cache reset")


def apply_overrides(config: PIIConfig, overrides: dict) -> PIIConfig:
    """
    Apply runtime overrides to a config.

    Args:
        config: Base PIIConfig instance
        overrides: Dict of overrides to apply

    Returns:
        New PIIConfig with overrides applied
    """
    # Convert to dict, apply overrides, create new config
    config_dict = config.model_dump()

    # Apply top-level overrides
    if "gateway_enabled" in overrides and overrides["gateway_enabled"] is not None:
        config_dict["gateway"]["enabled"] = overrides["gateway_enabled"]

    if "min_digits_threshold" in overrides and overrides["min_digits_threshold"] is not None:
        # Find the consecutive_digits test and update threshold
        for test in config_dict["gateway"]["tests"]:
            if test["name"] == "consecutive_digits":
                test["threshold"] = overrides["min_digits_threshold"]
                break

    if "patterns" in overrides and overrides["patterns"]:
        config_dict["patterns"].update(overrides["patterns"])

    if "context_keywords" in overrides and overrides["context_keywords"]:
        config_dict["context_keywords"].update(overrides["context_keywords"])

    if "scores" in overrides and overrides["scores"]:
        config_dict["scores"].update(overrides["scores"])

    if "detector_order" in overrides and overrides["detector_order"]:
        config_dict["detection"]["detector_order"] = overrides["detector_order"]

    if "context_window" in overrides and overrides["context_window"] is not None:
        config_dict["context_window"] = overrides["context_window"]

    return PIIConfig(**config_dict)


def setup_logging(config: Optional[PIIConfig] = None) -> None:
    """Configure logging from PIIConfig. PII_LOG_LEVEL env var overrides config."""
    if config is None:
        config = get_default_config()

    level_str = os.environ.get("PII_LOG_LEVEL", config.logging.level).upper()
    level = getattr(logging, level_str, logging.INFO)

    logging.basicConfig(
        level=level,
        format=config.logging.format,
        force=True
    )
