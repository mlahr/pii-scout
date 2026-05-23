"""
Dictionary-based NAME detector using Bloom filter + marisa-trie.

Uses an in-memory Bloom filter for fast negative rejection and a marisa-trie
for exact membership verification. Designed for detecting names from a
large dictionary (3.5M+ entries) with minimal memory footprint.
"""

import hashlib
import json
import logging
import os
import pickle
import re
import threading
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Module-level singletons
_bloom_filter: Optional[Any] = None
_name_trie: Optional[Any] = None
_max_words: int = 3
_init_lock = threading.Lock()
_initialized = False

# Constants
DEFAULT_FIRST_NAMES_PATH = "runtime_data/first_names.txt"
DEFAULT_LAST_NAMES_PATH = "runtime_data/last_names.txt"
DEFAULT_STOPWORDS_PATH = "runtime_data/stopwords-en.json"
CACHE_BASE_PATH = "runtime_data/names"
BLOOM_ERROR_RATE = 0.001  # 0.1% false positive rate
DICT_NAME_SCORE = 0.85

# Token pattern: alphanumeric sequences with internal hyphens/apostrophes
# Captures "Mary-Jane", "O'Brien", etc. as single tokens
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9\u00C0-\u024F]+(?:[-'][A-Za-z0-9\u00C0-\u024F]+)*")


def normalize_name(s: str) -> str:
    """
    Normalize a name string for dictionary matching.

    Applied both when building the dictionary and at runtime.

    Steps:
    1. Unicode NFKC normalization (handles accents, ligatures)
    2. Casefold (handles unicode-aware lowercasing)
    3. Collapse internal whitespace to single space
    4. Strip leading/trailing punctuation
    """
    if not s:
        return ""

    # NFKC normalization
    s = unicodedata.normalize("NFKC", s)

    # Casefold (better than lower() for unicode)
    s = s.casefold()

    # Collapse whitespace
    s = " ".join(s.split())

    # Strip edge punctuation but keep internal hyphens/apostrophes
    s = s.strip("\"'.,;:!?()[]{}<>")

    return s


def tokenize_with_offsets(text: str) -> List[Tuple[str, int, int]]:
    """
    Tokenize text and return list of (token, start, end) tuples.

    Tokens are alphanumeric sequences that may contain internal
    hyphens or apostrophes (e.g., "Mary-Jane", "O'Brien").

    Returns:
        List of (token_text, start_offset, end_offset) tuples
    """
    tokens = []
    for match in TOKEN_PATTERN.finditer(text):
        token_text = match.group()
        start = match.start()
        end = match.end()
        tokens.append((token_text, start, end))
    return tokens


def load_name_dictionary(
    first_names_path: str = DEFAULT_FIRST_NAMES_PATH,
    last_names_path: str = DEFAULT_LAST_NAMES_PATH,
    stopwords_path: str = DEFAULT_STOPWORDS_PATH
) -> Tuple[Set[str], int]:
    """
    Load names from text files, normalize them, return unique normalized names.

    Text files expected: one name per line.
    Names that appear in the stopwords list are excluded.

    Args:
        first_names_path: Path to first names text file
        last_names_path: Path to last names text file
        stopwords_path: Path to stopwords JSON file

    Returns:
        Tuple of (set_of_normalized_names, max_word_count)
    """
    # Load stopwords
    stopwords: Set[str] = set()
    if os.path.exists(stopwords_path):
        with open(stopwords_path, 'r', encoding='utf-8') as f:
            stopwords = set(json.load(f))
        logger.debug(f"Loaded {len(stopwords)} stopwords")

    names: Set[str] = set()
    max_words = 1

    for path in [first_names_path, last_names_path]:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                raw_name = line.strip()
                if not raw_name:
                    continue
                normalized = normalize_name(raw_name)
                if normalized and len(normalized) >= 2:  # Skip single-char names
                    if normalized not in stopwords:
                        names.add(normalized)
                        word_count = len(normalized.split())
                        if word_count > max_words:
                            max_words = word_count

    return names, max_words


def _source_checksum(*paths: str) -> str:
    """Compute a single SHA-256 hex digest over the contents of the source files."""
    h = hashlib.sha256()
    for path in paths:
        with open(path, 'rb') as f:
            h.update(f.read())
        h.update(b'\x00')  # separator between files
    return h.hexdigest()


def initialize_detector(
    first_names_path: str = DEFAULT_FIRST_NAMES_PATH,
    last_names_path: str = DEFAULT_LAST_NAMES_PATH,
    stopwords_path: str = DEFAULT_STOPWORDS_PATH,
    cache_base_path: str = CACHE_BASE_PATH
) -> None:
    """
    Initialize bloom filter and marisa trie from dictionary.

    Thread-safe singleton initialization. Safe to call multiple times;
    subsequent calls are no-ops if already initialized.

    Uses on-demand caching: builds structures from text files on first run,
    caches to .bloom and .marisa files for fast subsequent loads.

    Args:
        first_names_path: Path to first names text file
        last_names_path: Path to last names text file
        stopwords_path: Path to stopwords JSON file
        cache_base_path: Base path for cache files (without extension)

    Raises:
        FileNotFoundError: If dictionary files don't exist
        ImportError: If required libraries aren't installed
    """
    global _bloom_filter, _name_trie, _max_words, _initialized

    if _initialized:
        return

    with _init_lock:
        if _initialized:
            return

        import marisa_trie

        bloom_path = cache_base_path + '.bloom'
        trie_path = cache_base_path + '.marisa'
        checksum_path = cache_base_path + '.sha256'

        current_checksum = _source_checksum(first_names_path, last_names_path, stopwords_path)

        # Fast path: load cached files if checksum matches
        cache_valid = False
        if os.path.exists(bloom_path) and os.path.exists(trie_path):
            if os.path.exists(checksum_path):
                with open(checksum_path, 'r') as f:
                    cached_checksum = f.read().strip()
                cache_valid = (cached_checksum == current_checksum)
            if not cache_valid:
                logger.debug("Source files changed, rebuilding cache")

        if cache_valid:
            logger.debug("Loading cached name dictionary...")
            with open(bloom_path, 'rb') as f:
                _bloom_filter = pickle.load(f)
            _name_trie = marisa_trie.Trie()
            _name_trie.load(trie_path)
            _max_words = 3  # Known constant for this dataset
            _initialized = True
            logger.debug("Name dictionary loaded from cache")
            return

        # Slow path: build from text files and cache
        logger.debug(f"Building name dictionary from {first_names_path} and {last_names_path}...")
        names, max_words = load_name_dictionary(first_names_path, last_names_path, stopwords_path)

        logger.debug(f"Building bloom filter for {len(names)} names...")
        from pybloom_live import BloomFilter
        _bloom_filter = BloomFilter(capacity=len(names), error_rate=BLOOM_ERROR_RATE)
        for name in names:
            _bloom_filter.add(name)

        logger.debug("Building marisa trie...")
        _name_trie = marisa_trie.Trie(names)

        # Cache for next time
        with open(bloom_path, 'wb') as f:
            pickle.dump(_bloom_filter, f)
        _name_trie.save(trie_path)
        with open(checksum_path, 'w') as f:
            f.write(current_checksum)
        logger.debug(f"Cached to {bloom_path} and {trie_path}")

        _max_words = max_words
        _initialized = True
        logger.debug(f"Name dictionary loaded: {len(names)} unique names, max {max_words} words")


def is_initialized() -> bool:
    """Check if detector is initialized."""
    return _initialized


def run_dict_name_detection(text: str) -> List[Dict[str, Any]]:
    """
    Run dictionary-based name detection on text.

    Algorithm:
    1. Tokenize text with character offsets
    2. For each position, check 3-, 2-, 1-grams (longest first)
    3. Bloom filter for fast negative rejection
    4. Trie for exact verification on bloom positive
    5. On match, skip consumed tokens (greedy longest match)

    Args:
        text: Input text to scan for names

    Returns:
        List of entity dicts with keys:
        - type: "PERSON"
        - text: The matched text from original input
        - start: Start character offset
        - end: End character offset (exclusive)
        - score: Confidence score (0.85)
        - source: "dictionary"
    """
    if not _initialized:
        logger.debug("Dictionary detector not initialized, skipping")
        return []

    entities = []
    tokens = tokenize_with_offsets(text)
    n_tokens = len(tokens)

    i = 0
    while i < n_tokens:
        best_match = None
        best_n = 0

        # Try longest n-gram first (greedy longest match)
        for n in range(min(_max_words, n_tokens - i), 0, -1):
            ngram_tokens = tokens[i:i+n]
            combined = " ".join(t[0] for t in ngram_tokens)
            normalized = normalize_name(combined)

            if not normalized or len(normalized) < 2:
                continue

            # Fast bloom check
            if normalized not in _bloom_filter:
                continue

            # Verify with trie (handles bloom false positives)
            if normalized in _name_trie:
                start = ngram_tokens[0][1]
                end = ngram_tokens[-1][2]
                original_text = text[start:end]

                best_match = {
                    "type": "PERSON",
                    "text": original_text,
                    "start": start,
                    "end": end,
                    "score": DICT_NAME_SCORE,
                    "source": "dictionary"
                }
                best_n = n
                break  # Found longest match at this position

        if best_match:
            entities.append(best_match)
            i += best_n  # Skip consumed tokens
        else:
            i += 1  # Move to next token

    return entities
