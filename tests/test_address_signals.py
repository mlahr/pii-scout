"""Tests for address_signals gateway detector."""

import unittest
from pathlib import Path

from detectors.address_signals import (
    AddressSignalDetector,
    get_detector,
    reset_detector,
    load_file_set,
    _default_suffixes,
    _default_states,
)


class TestAddressSignalDetector(unittest.TestCase):
    """Test AddressSignalDetector scoring."""

    def setUp(self):
        """Create detector with default data."""
        self.detector = AddressSignalDetector(
            suffixes=_default_suffixes(),
            states=_default_states(),
            cities={"springfield", "boston", "chicago"},
            threshold=4
        )

    def test_full_address_high_score(self):
        """Full address should score high."""
        text = "123 Main St, Springfield, IL 62701"
        score, signals = self.detector.score(text)
        # suffix(+2) + city(+2) + state(+1) + zip_us(+3) + number_word(+1) = 9
        self.assertGreaterEqual(score, 8)
        self.assertIn('suffix', signals)
        self.assertIn('zip_us', signals)

    def test_po_box(self):
        """P.O. Box should trigger."""
        text = "P.O. Box 123"
        score, signals = self.detector.score(text)
        self.assertGreaterEqual(score, 3)
        self.assertIn('po_box', signals)

    def test_po_box_alt_format(self):
        """PO Box (no periods) should trigger."""
        text = "PO Box 456"
        score, signals = self.detector.score(text)
        self.assertIn('po_box', signals)

    def test_street_suffix_only(self):
        """Just a street suffix should give limited score."""
        text = "Maple Street"
        score, signals = self.detector.score(text)
        self.assertEqual(score, 2)
        self.assertIn('suffix', signals)

    def test_number_word_only(self):
        """House number + word gives +1."""
        text = "123 Maple"
        score, signals = self.detector.score(text)
        self.assertEqual(score, 1)
        self.assertIn('number_word', signals)

    def test_partial_address_no_trigger(self):
        """123 Main St alone = +1 +2 = 3, below threshold."""
        text = "123 Main St"
        trigger, _ = self.detector.should_trigger(text)
        self.assertFalse(trigger)

    def test_address_with_zip_triggers(self):
        """Address with zip should trigger."""
        text = "123 Oak Ave 02101"
        trigger, desc = self.detector.should_trigger(text)
        # suffix(+2) + zip(+3) + number_word(+1) = 6
        self.assertTrue(trigger)
        self.assertIn('address_signals', desc)

    def test_no_address_signals(self):
        """Regular text should not trigger."""
        text = "I bought 5 apples today"
        score, signals = self.detector.score(text)
        self.assertLessEqual(score, 1)

    def test_meeting_text_no_trigger(self):
        """Non-address text should not trigger."""
        text = "The meeting is at 3pm tomorrow"
        trigger, _ = self.detector.should_trigger(text)
        self.assertFalse(trigger)

    def test_unit_indicator(self):
        """Apt/Suite/Unit should add score."""
        text = "Apt 5B"
        score, signals = self.detector.score(text)
        self.assertIn('unit', signals)
        self.assertEqual(score, 2)

    def test_suite_indicator(self):
        """Suite should add score."""
        text = "Suite 100"
        score, signals = self.detector.score(text)
        self.assertIn('unit', signals)

    def test_directional(self):
        """Directional prefix should add score."""
        text = "North Main"
        score, signals = self.detector.score(text)
        self.assertIn('directional', signals)
        self.assertEqual(score, 1)

    def test_state_code(self):
        """State abbreviation should add score."""
        text = "Something in CA today"
        score, signals = self.detector.score(text)
        self.assertIn('state', signals)

    def test_city_name(self):
        """City name should add score."""
        text = "I live at Boston"
        score, signals = self.detector.score(text)
        self.assertIn('city', signals)
        # "at" is not a state code, so only city score (+2)
        self.assertEqual(score, 2)

    def test_uk_postcode(self):
        """UK postcode should add score."""
        text = "London SW1A 1AA"
        score, signals = self.detector.score(text)
        self.assertIn('zip_uk', signals)
        self.assertGreaterEqual(score, 3)

    def test_canadian_postal(self):
        """Canadian postal code should add score."""
        text = "Toronto M5V 3L9"
        score, signals = self.detector.score(text)
        self.assertIn('zip_ca', signals)
        self.assertGreaterEqual(score, 3)

    def test_threshold_customization(self):
        """Custom threshold should work."""
        detector = AddressSignalDetector(
            suffixes=_default_suffixes(),
            states=_default_states(),
            threshold=2
        )
        # Just "Main Street" with +2 should now trigger
        trigger, _ = detector.should_trigger("Maple Street")
        self.assertTrue(trigger)

    def test_suffix_abbreviation_case_insensitive(self):
        """Suffix matching should be case-insensitive."""
        text = "123 maple ST"
        score, signals = self.detector.score(text)
        self.assertIn('suffix', signals)


class TestGetDetector(unittest.TestCase):
    """Test detector factory function."""

    def setUp(self):
        reset_detector()

    def tearDown(self):
        reset_detector()

    def test_get_detector_returns_instance(self):
        """get_detector should return AddressSignalDetector."""
        detector = get_detector()
        self.assertIsInstance(detector, AddressSignalDetector)

    def test_get_detector_cached(self):
        """get_detector should return same instance."""
        d1 = get_detector()
        d2 = get_detector()
        self.assertIs(d1, d2)

    def test_reset_clears_cache(self):
        """reset_detector should clear cache."""
        d1 = get_detector()
        reset_detector()
        d2 = get_detector()
        self.assertIsNot(d1, d2)


class TestLoadFileSet(unittest.TestCase):
    """Test file loading utility."""

    def test_nonexistent_file(self):
        """Non-existent file should return empty set."""
        result = load_file_set(Path("/nonexistent/file.txt"))
        self.assertEqual(result, set())

    def test_load_actual_suffixes(self):
        """Should load actual suffix file if it exists."""
        data_dir = Path(__file__).parent.parent / "data" / "address"
        path = data_dir / "street_suffixes.txt"
        if path.exists():
            result = load_file_set(path)
            self.assertIn("Street", result)
            self.assertIn("Ave", result)


if __name__ == '__main__':
    unittest.main()
