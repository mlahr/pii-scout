import unittest
import sys
import os
import tempfile
import json
import random
import shutil

# Add parent dir to path to import sample_pii
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sample_pii


class TestPageBuckets(unittest.TestCase):
    def test_parse_buckets_default(self):
        defs = sample_pii.parse_page_buckets("1,2-5,6-20,21+")
        self.assertEqual(len(defs), 4)
        self.assertEqual(defs[0][0], "1")
        self.assertEqual(defs[1][0], "2-5")
        self.assertEqual(defs[2][0], "6-20")
        self.assertEqual(defs[3][0], "21+")

    def test_compute_bucket_single(self):
        defs = sample_pii.parse_page_buckets("1,2-5,6-20,21+")
        self.assertEqual(sample_pii.compute_page_bucket(1, defs), "1")
        self.assertEqual(sample_pii.compute_page_bucket(2, defs), "2-5")
        self.assertEqual(sample_pii.compute_page_bucket(5, defs), "2-5")
        self.assertEqual(sample_pii.compute_page_bucket(6, defs), "6-20")
        self.assertEqual(sample_pii.compute_page_bucket(20, defs), "6-20")
        self.assertEqual(sample_pii.compute_page_bucket(21, defs), "21+")
        self.assertEqual(sample_pii.compute_page_bucket(100, defs), "21+")

    def test_compute_bucket_zero_pages(self):
        defs = sample_pii.parse_page_buckets("1,2-5,6-20,21+")
        # Zero or None should default to "1"
        self.assertEqual(sample_pii.compute_page_bucket(0, defs), "1")
        self.assertEqual(sample_pii.compute_page_bucket(None, defs), "1")


class TestStratifiedSample(unittest.TestCase):
    def test_sample_proportional(self):
        pool = {
            "1": [{"id": f"1_{i}"} for i in range(10)],
            "2-5": [{"id": f"2_{i}"} for i in range(30)],
            "6-20": [{"id": f"6_{i}"} for i in range(60)],
        }
        rng = random.Random(42)
        selected, stats = sample_pii.stratified_sample(pool, 10, rng)

        self.assertEqual(len(selected), 10)
        # Each bucket should have at least 1
        self.assertGreater(stats["1"]["selected"], 0)
        self.assertGreater(stats["2-5"]["selected"], 0)
        self.assertGreater(stats["6-20"]["selected"], 0)

    def test_sample_exceeds_available(self):
        pool = {"1": [{"id": "a"}, {"id": "b"}]}
        rng = random.Random(42)
        selected, stats = sample_pii.stratified_sample(pool, 10, rng)

        # Only 2 available, should return 2
        self.assertEqual(len(selected), 2)
        self.assertEqual(stats["1"]["selected"], 2)

    def test_sample_empty_pool(self):
        pool = {}
        rng = random.Random(42)
        selected, stats = sample_pii.stratified_sample(pool, 10, rng)

        self.assertEqual(len(selected), 0)
        self.assertEqual(stats, {})

    def test_sample_single_bucket(self):
        pool = {"1": [{"id": f"1_{i}"} for i in range(100)]}
        rng = random.Random(42)
        selected, stats = sample_pii.stratified_sample(pool, 10, rng)

        self.assertEqual(len(selected), 10)
        self.assertEqual(stats["1"]["selected"], 10)


class TestLoadAndPartition(unittest.TestCase):
    def test_load_basic(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            f.write(json.dumps({"pdf": "a.pdf", "status": "ok", "contains_pii": True, "stats": {"total_pages": 1}}) + "\n")
            f.write(json.dumps({"pdf": "b.pdf", "status": "ok", "contains_pii": False, "stats": {"total_pages": 5}}) + "\n")
            f.write(json.dumps({"pdf": "c.pdf", "status": "extract_error", "contains_pii": None}) + "\n")
            temp_path = f.name

        try:
            defs = sample_pii.parse_page_buckets("1,2-5,6-20,21+")
            pii_pool, non_pii_pool, stats = sample_pii.load_and_partition(temp_path, defs)

            self.assertEqual(stats["total_read"], 3)
            self.assertEqual(stats["status_ok"], 2)
            self.assertEqual(stats["status_error"], 1)
            self.assertEqual(stats["with_pii"], 1)
            self.assertEqual(stats["without_pii"], 1)

            # Check bucketing
            self.assertEqual(len(pii_pool["1"]), 1)  # 1 page -> bucket "1"
            self.assertEqual(len(non_pii_pool["2-5"]), 1)  # 5 pages -> bucket "2-5"
        finally:
            os.unlink(temp_path)

    def test_load_missing_stats(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            # Record without stats field
            f.write(json.dumps({"pdf": "a.pdf", "status": "ok", "contains_pii": True}) + "\n")
            temp_path = f.name

        try:
            defs = sample_pii.parse_page_buckets("1,2-5,6-20,21+")
            pii_pool, non_pii_pool, stats = sample_pii.load_and_partition(temp_path, defs)

            self.assertEqual(stats["missing_stats"], 1)
            # Should default to bucket "1"
            self.assertEqual(len(pii_pool["1"]), 1)
        finally:
            os.unlink(temp_path)

    def test_load_zero_pages(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            f.write(json.dumps({"pdf": "a.pdf", "status": "ok", "contains_pii": False, "stats": {"total_pages": 0}}) + "\n")
            temp_path = f.name

        try:
            defs = sample_pii.parse_page_buckets("1,2-5,6-20,21+")
            pii_pool, non_pii_pool, stats = sample_pii.load_and_partition(temp_path, defs)

            self.assertEqual(stats["missing_stats"], 1)
            # Zero pages -> defaults to bucket "1"
            self.assertEqual(len(non_pii_pool["1"]), 1)
        finally:
            os.unlink(temp_path)


class TestWriteOutput(unittest.TestCase):
    def test_write_jsonl(self):
        records = [
            {"pdf": "a.pdf", "contains_pii": True},
            {"pdf": "b.pdf", "contains_pii": False}
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            temp_path = f.name

        try:
            sample_pii.write_output(temp_path, records)

            with open(temp_path, 'r') as f:
                lines = f.readlines()

            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["pdf"], "a.pdf")
            self.assertEqual(json.loads(lines[1])["pdf"], "b.pdf")
        finally:
            os.unlink(temp_path)


class TestFindParagraphsDir(unittest.TestCase):
    def test_find_exact_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a subdirectory matching PDF name
            os.makedirs(os.path.join(tmpdir, "test_doc"))

            result = sample_pii.find_paragraphs_dir("/path/to/test_doc.pdf", tmpdir)
            self.assertEqual(result, os.path.join(tmpdir, "test_doc"))

    def test_find_prefix_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a subdirectory with prefix matching PDF name
            os.makedirs(os.path.join(tmpdir, "test_doc_extracted"))

            result = sample_pii.find_paragraphs_dir("/path/to/test_doc.pdf", tmpdir)
            self.assertEqual(result, os.path.join(tmpdir, "test_doc_extracted"))

    def test_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = sample_pii.find_paragraphs_dir("/path/to/test_doc.pdf", tmpdir)
            self.assertIsNone(result)


class TestCopyToAnnotationDir(unittest.TestCase):
    def test_format_conversion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create source structure: PAGE=0001/PAR=0001.txt
            src_dir = os.path.join(tmpdir, "source")
            page_dir = os.path.join(src_dir, "PAGE=0001")
            os.makedirs(page_dir)

            # Create paragraph files
            with open(os.path.join(page_dir, "PAR=0001.txt"), 'w') as f:
                f.write("First paragraph")
            with open(os.path.join(page_dir, "PAR=0002.txt"), 'w') as f:
                f.write("Second paragraph")

            # Create second page
            page_dir2 = os.path.join(src_dir, "PAGE=0002")
            os.makedirs(page_dir2)
            with open(os.path.join(page_dir2, "PAR=0001.txt"), 'w') as f:
                f.write("Page 2 paragraph")

            # Copy to annotation dir
            annotation_dir = os.path.join(tmpdir, "annotation")
            stats = sample_pii.copy_to_annotation_dir(
                "/path/to/test_doc.pdf",
                src_dir,
                annotation_dir,
                copy_pdf=False
            )

            # Verify conversion
            self.assertEqual(stats["pages"], 2)
            self.assertEqual(stats["paragraphs"], 3)

            # Check output structure: {pdf_name}/page1/p0.txt
            self.assertTrue(os.path.exists(os.path.join(annotation_dir, "test_doc", "page1", "p0.txt")))
            self.assertTrue(os.path.exists(os.path.join(annotation_dir, "test_doc", "page1", "p1.txt")))
            self.assertTrue(os.path.exists(os.path.join(annotation_dir, "test_doc", "page2", "p0.txt")))

            # Verify content preserved
            with open(os.path.join(annotation_dir, "test_doc", "page1", "p0.txt")) as f:
                self.assertEqual(f.read(), "First paragraph")

    def test_copy_with_pdf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake PDF
            pdf_path = os.path.join(tmpdir, "test_doc.pdf")
            with open(pdf_path, 'w') as f:
                f.write("fake pdf content")

            # Create source structure
            src_dir = os.path.join(tmpdir, "source")
            page_dir = os.path.join(src_dir, "PAGE=0001")
            os.makedirs(page_dir)
            with open(os.path.join(page_dir, "PAR=0001.txt"), 'w') as f:
                f.write("Paragraph content")

            # Copy with PDF
            annotation_dir = os.path.join(tmpdir, "annotation")
            stats = sample_pii.copy_to_annotation_dir(
                pdf_path,
                src_dir,
                annotation_dir,
                copy_pdf=True
            )

            self.assertTrue(stats["pdf_copied"])
            self.assertTrue(os.path.exists(os.path.join(annotation_dir, "pdfs", "test_doc.pdf")))


class TestSetupAnnotationDir(unittest.TestCase):
    def test_setup_with_existing_paragraphs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create paragraphs directory with extracted content
            paragraphs_dir = os.path.join(tmpdir, "paragraphs")
            doc_dir = os.path.join(paragraphs_dir, "doc1")
            page_dir = os.path.join(doc_dir, "PAGE=0001")
            os.makedirs(page_dir)
            with open(os.path.join(page_dir, "PAR=0001.txt"), 'w') as f:
                f.write("Test content")

            # Create selected records
            selected = [{"pdf": "/some/path/doc1.pdf"}]

            # Set up annotation directory
            annotation_dir = os.path.join(tmpdir, "annotation")
            stats = sample_pii.setup_annotation_dir(
                selected,
                paragraphs_dir,
                annotation_dir,
                extract_cmd=None,
                copy_pdfs=False
            )

            self.assertEqual(stats["copied"], 1)
            self.assertEqual(stats["skipped"], 0)
            self.assertTrue(os.path.exists(os.path.join(annotation_dir, "doc1", "page1", "p0.txt")))

    def test_setup_skips_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Empty paragraphs directory
            paragraphs_dir = os.path.join(tmpdir, "paragraphs")
            os.makedirs(paragraphs_dir)

            # Create selected records with no matching paragraphs
            selected = [{"pdf": "/some/path/nonexistent.pdf"}]

            # Set up annotation directory
            annotation_dir = os.path.join(tmpdir, "annotation")
            stats = sample_pii.setup_annotation_dir(
                selected,
                paragraphs_dir,
                annotation_dir,
                extract_cmd=None,
                copy_pdfs=False
            )

            self.assertEqual(stats["copied"], 0)
            self.assertEqual(stats["skipped"], 1)


if __name__ == '__main__':
    unittest.main()
