import unittest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pii_detect import merge_spans, merge_adjacent_entities
from pii.pipeline import _boost_multi_model_agreement


class TestMergeSpans(unittest.TestCase):
    def test_exact_duplicates(self):
        """Exact duplicates should be merged into one."""
        ents = [
            {'type': 'PERSON', 'start': 10, 'end': 15, 'score': 0.9, 'text': 'Alice'},
            {'type': 'PERSON', 'start': 10, 'end': 15, 'score': 0.9, 'text': 'Alice'}
        ]
        merged = merge_spans(ents)
        self.assertEqual(len(merged), 1)

    def test_overlapping_same_type_merged(self):
        """Overlapping spans of the same type should be merged."""
        # Example: NER detects email [213,229], regex detects [214,229]
        ents = [
            {'type': 'EMAIL', 'start': 213, 'end': 229, 'score': 0.85, 'source': 'ner'},
            {'type': 'EMAIL', 'start': 214, 'end': 229, 'score': 0.90, 'source': 'regex'}
        ]
        merged = merge_spans(ents)
        self.assertEqual(len(merged), 1)
        # Should keep earliest start and latest end
        self.assertEqual(merged[0]['start'], 213)
        self.assertEqual(merged[0]['end'], 229)
        # Should keep highest score
        self.assertEqual(merged[0]['score'], 0.90)
        # Should collect both sources
        self.assertEqual(merged[0]['sources'], ['ner', 'regex'])

    def test_overlapping_different_types_not_merged(self):
        """Overlapping spans of different types should NOT be merged."""
        ents = [
            {'type': 'PERSON', 'start': 10, 'end': 15, 'score': 0.9, 'text': 'Alice'},
            {'type': 'LOCATION', 'start': 12, 'end': 18, 'score': 0.8, 'text': 'ice L'}
        ]
        merged = merge_spans(ents)
        self.assertEqual(len(merged), 2)

    def test_same_span_different_type(self):
        """Same span with different types should NOT be merged."""
        ents = [
            {'type': 'PERSON', 'start': 10, 'end': 15, 'score': 0.9, 'text': 'Alice'},
            {'type': 'custom', 'start': 10, 'end': 15, 'score': 0.8, 'text': 'Alice'}
        ]
        merged = merge_spans(ents)
        self.assertEqual(len(merged), 2)

    def test_sorting(self):
        """Output should be sorted by start position."""
        ents = [
            {'type': 'B', 'start': 20, 'end': 30, 'score': 0.5},
            {'type': 'A', 'start': 10, 'end': 15, 'score': 0.5}
        ]
        merged = merge_spans(ents)
        self.assertEqual(merged[0]['start'], 10)
        self.assertEqual(merged[1]['start'], 20)

    def test_contained_span_merged(self):
        """A span fully contained in another of the same type should be merged."""
        ents = [
            {'type': 'PERSON', 'start': 10, 'end': 25, 'score': 0.80, 'source': 'ner'},
            {'type': 'PERSON', 'start': 12, 'end': 20, 'score': 0.85, 'source': 'regex'}
        ]
        merged = merge_spans(ents)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['start'], 10)
        self.assertEqual(merged[0]['end'], 25)
        self.assertEqual(merged[0]['score'], 0.85)

    def test_empty_input(self):
        """Empty input should return empty list."""
        self.assertEqual(merge_spans([]), [])


class TestMergeAdjacentEntities(unittest.TestCase):
    def test_adjacent_same_type_merged(self):
        """Adjacent entities of the same type should be merged."""
        text = "John Smith is here"
        ents = [
            {'type': 'PERSON', 'start': 0, 'end': 4, 'score': 0.85, 'source': 'ner'},  # "John"
            {'type': 'PERSON', 'start': 5, 'end': 10, 'score': 0.90, 'source': 'ner'}  # "Smith"
        ]
        merged = merge_adjacent_entities(ents, text, gap_threshold=2)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['start'], 0)
        self.assertEqual(merged[0]['end'], 10)
        self.assertEqual(merged[0]['score'], 0.90)

    def test_non_adjacent_not_merged(self):
        """Non-adjacent entities should NOT be merged."""
        text = "John lives in Smith Town"
        ents = [
            {'type': 'PERSON', 'start': 0, 'end': 4, 'score': 0.85, 'source': 'ner'},  # "John"
            {'type': 'PERSON', 'start': 14, 'end': 19, 'score': 0.90, 'source': 'ner'}  # "Smith"
        ]
        merged = merge_adjacent_entities(ents, text, gap_threshold=2)
        self.assertEqual(len(merged), 2)

    def test_different_types_not_merged(self):
        """Adjacent entities of different types should NOT be merged."""
        text = "John Boston is here"
        ents = [
            {'type': 'PERSON', 'start': 0, 'end': 4, 'score': 0.85, 'source': 'ner'},  # "John"
            {'type': 'LOCATION', 'start': 5, 'end': 11, 'score': 0.90, 'source': 'ner'}  # "Boston"
        ]
        merged = merge_adjacent_entities(ents, text, gap_threshold=2)
        self.assertEqual(len(merged), 2)

    def test_gap_with_non_whitespace_not_merged(self):
        """Adjacent entities with non-whitespace gap should NOT be merged."""
        text = "John-Smith is here"
        ents = [
            {'type': 'PERSON', 'start': 0, 'end': 4, 'score': 0.85, 'source': 'ner'},  # "John"
            {'type': 'PERSON', 'start': 5, 'end': 10, 'score': 0.90, 'source': 'ner'}  # "Smith"
        ]
        merged = merge_adjacent_entities(ents, text, gap_threshold=2)
        # Gap is "-" which is not whitespace, so should not merge
        self.assertEqual(len(merged), 2)

    def test_empty_input(self):
        """Empty input should return empty list."""
        self.assertEqual(merge_adjacent_entities([], "some text", gap_threshold=2), [])

    def test_touching_entities_merged(self):
        """Entities with gap=0 (touching) should be merged."""
        text = "JohnSmith is here"
        ents = [
            {'type': 'PERSON', 'start': 0, 'end': 4, 'score': 0.85, 'source': 'ner'},  # "John"
            {'type': 'PERSON', 'start': 4, 'end': 9, 'score': 0.90, 'source': 'ner'}  # "Smith"
        ]
        merged = merge_adjacent_entities(ents, text, gap_threshold=2)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['start'], 0)
        self.assertEqual(merged[0]['end'], 9)


class TestMultiModelBoost(unittest.TestCase):
    def test_overlapping_same_type_different_model_boosted(self):
        """Two models finding the same entity should boost both scores."""
        ents = [
            {'type': 'PERSON', 'start': 0, 'end': 10, 'score': 0.85, 'source': 'ner', '_model': 'spacy'},
            {'type': 'PERSON', 'start': 0, 'end': 10, 'score': 0.80, 'source': 'ner', '_model': 'piiranha'},
        ]
        result = _boost_multi_model_agreement(ents, boost=0.10, max_score=0.99)
        self.assertAlmostEqual(result[0]['score'], 0.95)
        self.assertAlmostEqual(result[1]['score'], 0.90)

    def test_same_model_not_boosted(self):
        """Two entities from the same model should not boost."""
        ents = [
            {'type': 'PERSON', 'start': 0, 'end': 10, 'score': 0.85, 'source': 'ner', '_model': 'spacy'},
            {'type': 'PERSON', 'start': 0, 'end': 10, 'score': 0.80, 'source': 'ner', '_model': 'spacy'},
        ]
        result = _boost_multi_model_agreement(ents, boost=0.10, max_score=0.99)
        self.assertAlmostEqual(result[0]['score'], 0.85)
        self.assertAlmostEqual(result[1]['score'], 0.80)

    def test_different_type_not_boosted(self):
        """Overlapping entities of different types should not boost."""
        ents = [
            {'type': 'PERSON', 'start': 0, 'end': 10, 'score': 0.85, 'source': 'ner', '_model': 'spacy'},
            {'type': 'LOCATION', 'start': 0, 'end': 10, 'score': 0.80, 'source': 'ner', '_model': 'piiranha'},
        ]
        result = _boost_multi_model_agreement(ents, boost=0.10, max_score=0.99)
        self.assertAlmostEqual(result[0]['score'], 0.85)
        self.assertAlmostEqual(result[1]['score'], 0.80)

    def test_non_overlapping_not_boosted(self):
        """Non-overlapping entities should not boost."""
        ents = [
            {'type': 'PERSON', 'start': 0, 'end': 5, 'score': 0.85, 'source': 'ner', '_model': 'spacy'},
            {'type': 'PERSON', 'start': 10, 'end': 15, 'score': 0.80, 'source': 'ner', '_model': 'piiranha'},
        ]
        result = _boost_multi_model_agreement(ents, boost=0.10, max_score=0.99)
        self.assertAlmostEqual(result[0]['score'], 0.85)
        self.assertAlmostEqual(result[1]['score'], 0.80)

    def test_boost_capped_at_max_score(self):
        """Boost should not exceed max_score."""
        ents = [
            {'type': 'PERSON', 'start': 0, 'end': 10, 'score': 0.95, 'source': 'ner', '_model': 'spacy'},
            {'type': 'PERSON', 'start': 0, 'end': 10, 'score': 0.92, 'source': 'ner', '_model': 'piiranha'},
        ]
        result = _boost_multi_model_agreement(ents, boost=0.10, max_score=0.99)
        self.assertAlmostEqual(result[0]['score'], 0.99)
        self.assertAlmostEqual(result[1]['score'], 0.99)

    def test_partial_overlap_boosted(self):
        """Partially overlapping same-type entities from different models should boost."""
        ents = [
            {'type': 'PERSON', 'start': 0, 'end': 10, 'score': 0.85, 'source': 'ner', '_model': 'spacy'},
            {'type': 'PERSON', 'start': 5, 'end': 14, 'score': 0.78, 'source': 'ner', '_model': 'piiranha'},
        ]
        result = _boost_multi_model_agreement(ents, boost=0.10, max_score=0.99)
        self.assertAlmostEqual(result[0]['score'], 0.95)
        self.assertAlmostEqual(result[1]['score'], 0.88)

    def test_empty_input(self):
        """Empty input should return empty list."""
        result = _boost_multi_model_agreement([], boost=0.10, max_score=0.99)
        self.assertEqual(result, [])

    def test_single_entity_no_boost(self):
        """Single entity should not be boosted."""
        ents = [
            {'type': 'PERSON', 'start': 0, 'end': 10, 'score': 0.85, 'source': 'ner', '_model': 'spacy'},
        ]
        result = _boost_multi_model_agreement(ents, boost=0.10, max_score=0.99)
        self.assertAlmostEqual(result[0]['score'], 0.85)


if __name__ == '__main__':
    unittest.main()
