"""
Unit tests for the dictionary-based name detector.
"""

import os
import tempfile
import unittest

from detectors.name_dict_detector import normalize_name, tokenize_with_offsets, _source_checksum


class TestNormalizeName(unittest.TestCase):
    """Test the normalize_name function."""

    def test_basic_lowercase(self):
        self.assertEqual(normalize_name("JOHN"), "john")
        self.assertEqual(normalize_name("John"), "john")
        self.assertEqual(normalize_name("jOhN"), "john")

    def test_unicode_nfkc_normalization(self):
        # Composed character (e + combining acute) should normalize
        self.assertEqual(normalize_name("Jose\u0301"), "jos\u00e9")

    def test_casefold_german_sharp_s(self):
        # German sharp s (ß) casefolds to "ss"
        self.assertEqual(normalize_name("STRASSE"), "strasse")
        self.assertEqual(normalize_name("Straße"), "strasse")

    def test_whitespace_collapse(self):
        self.assertEqual(normalize_name("mary  jane"), "mary jane")
        self.assertEqual(normalize_name("mary   jane"), "mary jane")
        self.assertEqual(normalize_name("  john  "), "john")
        self.assertEqual(normalize_name("a\t\nb"), "a b")

    def test_preserve_internal_hyphen(self):
        self.assertEqual(normalize_name("Mary-Jane"), "mary-jane")
        self.assertEqual(normalize_name("MARY-JANE"), "mary-jane")

    def test_preserve_internal_apostrophe(self):
        self.assertEqual(normalize_name("O'Brien"), "o'brien")
        self.assertEqual(normalize_name("O'BRIEN"), "o'brien")

    def test_strip_edge_punctuation(self):
        self.assertEqual(normalize_name("'john"), "john")
        self.assertEqual(normalize_name("john,"), "john")
        self.assertEqual(normalize_name("\"mary\""), "mary")
        self.assertEqual(normalize_name("(bob)"), "bob")

    def test_empty_string(self):
        self.assertEqual(normalize_name(""), "")
        self.assertEqual(normalize_name("   "), "")


class TestTokenization(unittest.TestCase):
    """Test tokenize_with_offsets function."""

    def test_simple_tokens(self):
        tokens = tokenize_with_offsets("Hello World")
        self.assertEqual(len(tokens), 2)
        self.assertEqual(tokens[0], ("Hello", 0, 5))
        self.assertEqual(tokens[1], ("World", 6, 11))

    def test_hyphenated_name(self):
        tokens = tokenize_with_offsets("Mary-Jane Smith")
        self.assertEqual(len(tokens), 2)
        self.assertEqual(tokens[0], ("Mary-Jane", 0, 9))
        self.assertEqual(tokens[1], ("Smith", 10, 15))

    def test_apostrophe_name(self):
        tokens = tokenize_with_offsets("O'Brien said hello")
        self.assertEqual(len(tokens), 3)
        self.assertEqual(tokens[0], ("O'Brien", 0, 7))
        self.assertEqual(tokens[1], ("said", 8, 12))
        self.assertEqual(tokens[2], ("hello", 13, 18))

    def test_punctuation_splitting(self):
        tokens = tokenize_with_offsets("Hello, World!")
        self.assertEqual(len(tokens), 2)
        self.assertEqual(tokens[0][0], "Hello")
        self.assertEqual(tokens[1][0], "World")

    def test_multiple_spaces(self):
        tokens = tokenize_with_offsets("Hello   World")
        self.assertEqual(len(tokens), 2)
        self.assertEqual(tokens[0], ("Hello", 0, 5))
        self.assertEqual(tokens[1], ("World", 8, 13))

    def test_leading_trailing_spaces(self):
        tokens = tokenize_with_offsets("  Hello  ")
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0], ("Hello", 2, 7))

    def test_empty_string(self):
        tokens = tokenize_with_offsets("")
        self.assertEqual(tokens, [])

    def test_only_punctuation(self):
        tokens = tokenize_with_offsets("!@#$%^&*()")
        self.assertEqual(tokens, [])


class TestSourceChecksum(unittest.TestCase):
    """Test the _source_checksum helper."""

    def test_deterministic(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("hello\n")
            path = f.name
        try:
            self.assertEqual(_source_checksum(path), _source_checksum(path))
        finally:
            os.unlink(path)

    def test_changes_when_content_changes(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("hello\n")
            path = f.name
        try:
            checksum1 = _source_checksum(path)
            with open(path, 'w') as f:
                f.write("world\n")
            checksum2 = _source_checksum(path)
            self.assertNotEqual(checksum1, checksum2)
        finally:
            os.unlink(path)

    def test_multiple_files(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f1:
            f1.write("aaa\n")
            p1 = f1.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f2:
            f2.write("bbb\n")
            p2 = f2.name
        try:
            cs = _source_checksum(p1, p2)
            self.assertEqual(len(cs), 64)  # SHA-256 hex digest length
        finally:
            os.unlink(p1)
            os.unlink(p2)


class TestDictDetection(unittest.TestCase):
    """Test the main detection function with real dictionary."""

    @classmethod
    def setUpClass(cls):
        """Initialize detector once for all tests."""
        from detectors.name_dict_detector import (
            initialize_detector, is_initialized,
            DEFAULT_FIRST_NAMES_PATH, DEFAULT_LAST_NAMES_PATH
        )
        if not os.path.exists(DEFAULT_FIRST_NAMES_PATH) or not os.path.exists(DEFAULT_LAST_NAMES_PATH):
            raise unittest.SkipTest("Dictionary files not available")
        if not is_initialized():
            initialize_detector()

    def test_single_word_name(self):
        from detectors.name_dict_detector import run_dict_name_detection
        # "john" should be in the dictionary
        ents = run_dict_name_detection("Contact John for details.")
        names = [e['text'] for e in ents if e['type'] == 'PERSON']
        self.assertIn('John', names)

    def test_case_insensitive(self):
        from detectors.name_dict_detector import run_dict_name_detection
        ents1 = run_dict_name_detection("john")
        ents2 = run_dict_name_detection("JOHN")
        ents3 = run_dict_name_detection("John")
        # All should find the same name
        self.assertEqual(len(ents1), len(ents2))
        self.assertEqual(len(ents1), len(ents3))

    def test_offset_correctness(self):
        from detectors.name_dict_detector import run_dict_name_detection
        text = "Hello John Smith"
        ents = run_dict_name_detection(text)
        for e in ents:
            # Verify text matches slice
            self.assertEqual(text[e['start']:e['end']], e['text'])

    def test_entity_format(self):
        from detectors.name_dict_detector import run_dict_name_detection
        ents = run_dict_name_detection("John called.")
        if ents:
            e = ents[0]
            self.assertIn('type', e)
            self.assertIn('text', e)
            self.assertIn('start', e)
            self.assertIn('end', e)
            self.assertIn('score', e)
            self.assertIn('source', e)
            self.assertEqual(e['type'], 'PERSON')
            self.assertEqual(e['score'], 0.85)
            self.assertEqual(e['source'], 'dictionary')

    def test_no_match_gibberish(self):
        from detectors.name_dict_detector import run_dict_name_detection
        # Random gibberish should not match
        ents = run_dict_name_detection("xyzabc qrstuv blahblah")
        self.assertEqual(len(ents), 0)

    def test_no_overlapping_matches(self):
        from detectors.name_dict_detector import run_dict_name_detection
        text = "met John yesterday"
        ents = run_dict_name_detection(text)
        # Should not have overlapping matches
        starts = [e['start'] for e in ents]
        self.assertEqual(len(starts), len(set(starts)))

    def test_multiple_names_in_text(self):
        from detectors.name_dict_detector import run_dict_name_detection
        text = "John met Mary at the park"
        ents = run_dict_name_detection(text)
        names = [e['text'] for e in ents]
        self.assertIn('John', names)
        self.assertIn('Mary', names)


class TestOffsetMappingIntegration(unittest.TestCase):
    """Test that offsets work correctly through normalization pipeline."""

    @classmethod
    def setUpClass(cls):
        from detectors.name_dict_detector import (
            initialize_detector, is_initialized,
            DEFAULT_FIRST_NAMES_PATH, DEFAULT_LAST_NAMES_PATH
        )
        if not os.path.exists(DEFAULT_FIRST_NAMES_PATH) or not os.path.exists(DEFAULT_LAST_NAMES_PATH):
            raise unittest.SkipTest("Dictionary files not available")
        if not is_initialized():
            initialize_detector()

    def test_normalized_text_detection(self):
        """Test detection on text that would be normalized differently."""
        from detectors.name_dict_detector import run_dict_name_detection

        # Text with extra spaces
        text = "Hello   John   Smith"
        ents = run_dict_name_detection(text)
        for e in ents:
            # Offsets should still point to correct text
            self.assertEqual(text[e['start']:e['end']], e['text'])


if __name__ == '__main__':
    unittest.main()
