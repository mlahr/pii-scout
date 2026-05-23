import unittest
from pii_detect import normalize_text

class TestNormalization(unittest.TestCase):
    def test_basic_mapping(self):
        # Raw: "A B" -> Norm: "A B"
        # 012 -> 012
        text = "A B"
        norm, mapping = normalize_text(text)
        self.assertEqual(norm, "A B")
        self.assertEqual(mapping, [0, 1, 2])
        
    def test_hyphen_removal(self):
        # "ab-\ncd" -> "abcd" (hyphen+newline removed)
        # indices:
        # 0123 45
        # a:0->0
        # b:1->1
        # -:2 (skip)
        # \n:3 (skip)
        # c:4->2
        # d:5->3
        text = "ab-\ncd"
        norm, mapping = normalize_text(text)
        self.assertEqual(norm, "abcd")
        self.assertEqual(len(mapping), 4)
        self.assertEqual(mapping[0], 0) # a
        self.assertEqual(mapping[1], 1) # b
        self.assertEqual(mapping[2], 4) # c (was index 4)
        self.assertEqual(mapping[3], 5) # d (was index 5)
        
    def test_newline_to_space(self):
        # "a\nb" -> "a b"
        # 012 -> 012
        text = "a\nb"
        norm, mapping = normalize_text(text)
        self.assertEqual(norm, "a b")
        self.assertEqual(mapping, [0, 1, 2])
        
    def test_collapse_spaces(self):
        # "a  b" -> "a b"
        # 0123 -> 012
        # a:0->0
        #  :1->1
        #  :2 (skip)
        # b:3->2
        text = "a  b"
        norm, mapping = normalize_text(text)
        self.assertEqual(norm, "a b")
        self.assertEqual(mapping, [0, 1, 3])

if __name__ == '__main__':
    unittest.main()
