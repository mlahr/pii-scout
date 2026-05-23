import unittest
import sys
import os
import shutil
import tempfile
import json
import re

# Add parent dir to path to import select_pii
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import select_pii

class TestPIIDetector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Load model once
        cls.detector = select_pii.PIIDetector()

    def test_regex_ssn(self):
        text = "My SSN is 123-45-6789."
        match = self.detector.detect(text, threshold=0.0)
        self.assertIsNotNone(match)
        self.assertEqual(match['type'], 'SSN')
        self.assertEqual(match['text'], '123-45-6789')

    def test_regex_phone(self):
        text = "Call me at (555) 123-4567."
        match = self.detector.detect(text, threshold=0.0)
        self.assertIsNotNone(match)
        self.assertEqual(match['type'], 'PHONE')
        
    def test_regex_email(self):
        text = "My email is test@example.com"
        match = self.detector.detect(text, threshold=0.0)
        self.assertIsNotNone(match)
        self.assertEqual(match['type'], 'EMAIL')
        self.assertEqual(match['text'], 'test@example.com')

    def test_context_name(self):
        # "Name: John Doe"
        text = "Employee Name: John Doe verified."
        match = self.detector.detect(text, threshold=0.0)
        self.assertIsNotNone(match)
        self.assertEqual(match['type'], 'PERSON_CTX')
        self.assertEqual(match['text'], 'John Doe')

    def test_context_address(self):
        # "Address: 123 Main St"
        # The regex catches "123 Main St"
        text = "Address: 123 Main St, Springfield"
        match = self.detector.detect(text, threshold=0.0)
        self.assertIsNotNone(match)
        self.assertEqual(match['type'], 'ADDRESS_CTX')
        self.assertIn("123 Main St", match['text'])

    def test_context_negative(self):
        # "Name: generic lower case" -> Should not match
        text = "Name: generic thing"
        match = self.detector.detect(text, threshold=0.0)
        self.assertIsNone(match)

    def test_date_no_single_year(self):
        """Single years should NOT match as dates."""
        text = "The year 2024 was good."
        match = self.detector.detect(text, threshold=0.0)
        # Should be None or at least not a DATE match
        if match is not None:
            self.assertNotEqual(match['type'], 'DATE')

    def test_address_requires_street_suffix(self):
        """City/continent names after 'Address:' should NOT match."""
        text = "Address: 1 Europe Building"
        match = self.detector.detect(text, threshold=0.0)
        self.assertIsNone(match)

    def test_address_city_no_match(self):
        """Just city name after 'Address:' should NOT match."""
        text = "Address: 123 London UK"
        match = self.detector.detect(text, threshold=0.0)
        self.assertIsNone(match)

    def test_address_with_street_suffix(self):
        """Addresses with street suffix should match."""
        text = "Address: 456 Oak Avenue, Springfield"
        match = self.detector.detect(text, threshold=0.0)
        self.assertIsNotNone(match)
        self.assertEqual(match['type'], 'ADDRESS_CTX')

    def test_address_with_zipcode(self):
        """Addresses with zipcode should match."""
        text = "Address: 123 Some Place, City 90210"
        match = self.detector.detect(text, threshold=0.0)
        self.assertIsNotNone(match)
        self.assertEqual(match['type'], 'ADDRESS_CTX')

if __name__ == '__main__':
    unittest.main()
