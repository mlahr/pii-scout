"""Address signal detection for gateway.

Multi-signal scoring to trigger NER when address indicators are present.
"""

import re
import logging
from pathlib import Path
from typing import Set, Tuple, List, Optional

logger = logging.getLogger(__name__)

# Module-level cache for singleton detector
_detector: Optional["AddressSignalDetector"] = None


class AddressSignalDetector:
    """Detects address signals in text using a weighted scoring system."""

    def __init__(
        self,
        suffixes: Set[str],
        states: Set[str],
        cities: Optional[Set[str]] = None,
        threshold: int = 4
    ):
        """
        Args:
            suffixes: Set of street suffixes (St, Ave, Rd, etc.)
            states: Set of 2-letter state/province codes
            cities: Optional set of city names (lowercase)
            threshold: Minimum score to trigger NER
        """
        self.suffixes = suffixes
        self.states = {s.upper() for s in states}
        self.cities = {c.lower() for c in cities} if cities else set()
        self.threshold = threshold
        self._compile()

    def _compile(self):
        """Compile regex patterns."""
        # Street suffix pattern
        suffix_alt = '|'.join(re.escape(s) for s in self.suffixes)
        self.re_suffix = re.compile(rf'\b({suffix_alt})\.?\b', re.IGNORECASE)

        # Zip code patterns
        self.re_zip_us = re.compile(r'\b\d{5}(-\d{4})?\b')
        self.re_zip_uk = re.compile(r'\b[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2}\b', re.IGNORECASE)
        self.re_zip_ca = re.compile(r'\b[A-Z]\d[A-Z]\s*\d[A-Z]\d\b', re.IGNORECASE)

        # Other patterns
        self.re_po_box = re.compile(r'\bP\.?O\.?\s*Box\b', re.IGNORECASE)
        self.re_unit = re.compile(r'\b(Apt|Suite|Ste|Unit|#)\s*[A-Z0-9-]+\b', re.IGNORECASE)
        self.re_number_word = re.compile(r'\b\d{1,5}\s+[a-zA-Z]')
        self.re_directional = re.compile(
            r'\b(N|S|E|W|North|South|East|West|NE|NW|SE|SW)\s+[A-Za-z]',
            re.IGNORECASE
        )

    def score(self, text: str) -> Tuple[int, List[str]]:
        """
        Calculate address signal score.

        Returns:
            Tuple of (score, list of matched signal names)
        """
        score = 0
        signals = []
        text_lower = text.lower()

        # Street suffix (+2)
        if self.re_suffix.search(text):
            score += 2
            signals.append('suffix')

        # US zip code (+3)
        if self.re_zip_us.search(text):
            score += 3
            signals.append('zip_us')

        # UK postcode (+3)
        if self.re_zip_uk.search(text):
            score += 3
            signals.append('zip_uk')

        # Canadian postal code (+3)
        if self.re_zip_ca.search(text):
            score += 3
            signals.append('zip_ca')

        # P.O. Box (+3)
        if self.re_po_box.search(text):
            score += 3
            signals.append('po_box')

        # Unit indicator (+2)
        if self.re_unit.search(text):
            score += 2
            signals.append('unit')

        # House number + word (+1)
        if self.re_number_word.search(text):
            score += 1
            signals.append('number_word')

        # Directional prefix (+1)
        if self.re_directional.search(text):
            score += 1
            signals.append('directional')

        # State abbreviation check (+1)
        words = {w.upper() for w in re.findall(r'\b[A-Za-z]{2}\b', text)}
        if words & self.states:
            score += 1
            signals.append('state')

        # City name check (+2)
        if self.cities:
            for city in self.cities:
                if city in text_lower:
                    score += 2
                    signals.append('city')
                    break

        return score, signals

    def should_trigger(self, text: str) -> Tuple[bool, str]:
        """
        Determine if address signals should trigger NER.

        Returns:
            Tuple of (should_trigger, match_description)
        """
        score, signals = self.score(text)
        if score >= self.threshold:
            return True, f"address_signals({score}): {','.join(signals)}"
        return False, ""


def load_file_set(path: Path) -> Set[str]:
    """Load a set of strings from a file (one per line, ignoring comments and blanks)."""
    if not path.exists():
        logger.debug(f"Address signals file not found: {path}")
        return set()

    result = set()
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                result.add(line)
    return result


def get_detector(config=None, data_dir: Optional[Path] = None) -> AddressSignalDetector:
    """
    Get or create a cached AddressSignalDetector.

    Args:
        config: Optional PIIConfig with gateway test threshold
        data_dir: Optional path to data directory (default: data/address/)

    Returns:
        Cached AddressSignalDetector instance
    """
    global _detector

    if _detector is not None:
        return _detector

    # Determine data directory
    if data_dir is None:
        data_dir = Path(__file__).parent.parent / "data" / "address"

    # Load data files
    suffixes = load_file_set(data_dir / "street_suffixes.txt")
    states = load_file_set(data_dir / "state_abbrevs.txt")
    cities = load_file_set(data_dir / "cities.txt")

    # Use defaults if files not found
    if not suffixes:
        suffixes = _default_suffixes()
    if not states:
        states = _default_states()

    # Get threshold from config if available
    threshold = 4
    if config and hasattr(config, 'gateway') and config.gateway.tests:
        for test in config.gateway.tests:
            if test.name == "address_signals" and test.threshold is not None:
                threshold = test.threshold
                break

    _detector = AddressSignalDetector(
        suffixes=suffixes,
        states=states,
        cities=cities,
        threshold=threshold
    )

    logger.debug(
        f"Initialized AddressSignalDetector: {len(suffixes)} suffixes, "
        f"{len(states)} states, {len(cities)} cities, threshold={threshold}"
    )

    return _detector


def reset_detector():
    """Reset the cached detector (useful for testing)."""
    global _detector
    _detector = None


def _default_suffixes() -> Set[str]:
    """Default street suffixes when file not found."""
    return {
        # Common US suffixes
        "St", "Street", "Ave", "Avenue", "Rd", "Road", "Blvd", "Boulevard",
        "Dr", "Drive", "Ln", "Lane", "Ct", "Court", "Pl", "Place",
        "Way", "Cir", "Circle", "Pkwy", "Parkway", "Hwy", "Highway",
        "Ter", "Terrace", "Trl", "Trail", "Loop", "Run", "Path",
        "Sq", "Square", "Pt", "Point", "Aly", "Alley",
    }


def _default_states() -> Set[str]:
    """Default US state abbreviations when file not found."""
    return {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC", "PR", "VI", "GU", "AS", "MP",
    }
