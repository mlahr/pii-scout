
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import fitz
from index_corpus import analyze_pdf, compute_size_bucket

class TestIndexer(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.pdf_path = os.path.join(self.test_dir.name, "test.pdf")

    def tearDown(self):
        self.test_dir.cleanup()

    def create_dummy_pdf(self, text=None, images=0, image_size=100):
        doc = fitz.open()
        page = doc.new_page()
        if text:
            page.insert_text((50, 50), text)
        for _ in range(images):
            # Insert a small blue rect as an image
            # fitz.insert_image is easier if we have bytes, but let's mock the image presence 
            # by drawing a shape? No, to test get_images() we need actual images.
            # Alternately, we can just rely on mocking analyze_pdf internals or try to insert minimal binary image.
            
            # Create a 1x1 image
            img_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
            page.insert_image(page.rect, stream=img_data)
            
        doc.save(self.pdf_path)
        doc.close()

    def test_size_bucket(self):
        self.assertEqual(compute_size_bucket(100), "tiny")
        self.assertEqual(compute_size_bucket(500 * 1024), "normal")
        self.assertEqual(compute_size_bucket(10 * 1024 * 1024), "huge")

    def test_analyze_pdf_basics(self):
        self.create_dummy_pdf(text="Hello World")
        result = analyze_pdf(self.pdf_path, max_pages_probe=3)
        
        self.assertEqual(result["path"], os.path.abspath(self.pdf_path))
        self.assertEqual(result["page_count"], 1)
        self.assertEqual(result["size_bucket"], "tiny")
        self.assertTrue(result["has_text_ops"])
        self.assertFalse(result["likely_scanned"])
        self.assertIn("producer", result)
        self.assertIn("pdf_id", result)

    def test_analyze_pdf_scanned_heuristic(self):
        # Create PDF with no text, one image
        self.create_dummy_pdf(text=None, images=1)
        result = analyze_pdf(self.pdf_path, max_pages_probe=3)
        
        self.assertFalse(result["has_text_ops"])
        self.assertGreater(result["image_xobject_count"], 0)
        # Should have a high scan score
        self.assertGreaterEqual(result["scan_score"], 0.6)
        # 0.6 + 0.3 (images no text) = 0.9 => likely scanned
        self.assertTrue(result["likely_scanned"])

    def test_analyze_pdf_mixed_content(self):
        # Text and image -> likely not scanned
        self.create_dummy_pdf(text="Some text", images=1)
        result = analyze_pdf(self.pdf_path, max_pages_probe=3)
        self.assertTrue(result["has_text_ops"])
        self.assertEqual(result["scan_score"], 0.0)
        self.assertFalse(result["likely_scanned"])

    def test_invalid_pdf(self):
        with open(self.pdf_path, "wb") as f:
            f.write(b"not a pdf")
        
        result = analyze_pdf(self.pdf_path, max_pages_probe=3)
        self.assertTrue(len(result["errors"]) > 0)
        self.assertIsNone(result["page_count"])

if __name__ == "__main__":
    unittest.main()
