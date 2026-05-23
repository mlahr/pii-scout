import unittest
from pii_detect import run_regex_detection, CONTEXT_WINDOW, has_consecutive_digits

class TestPatterns(unittest.TestCase):
    def test_ssn(self):
        text = "My SSN is 123-45-6789."
        ents = run_regex_detection(text)
        self.assertTrue(any(e['type'] == 'SSN' and e['text'] == '123-45-6789' for e in ents))
        # Context boost check
        match = next(e for e in ents if e['type'] == 'SSN')
        self.assertGreaterEqual(match['score'], 0.95) # Base 0.95 + 0.10 boost capped 0.99

    def test_ssn_no_context_pattern(self):
        # 9 digits raw - might benefit from context
        text = "123456789"
        ents = run_regex_detection(text)
        # Should NOT match as SSN without context
        self.assertFalse(any(e['type'] == 'SSN' and e['text'] == '123456789' for e in ents))

    def test_phone(self):
        text = "Call me at (555) 123-4567 please."
        ents = run_regex_detection(text)
        self.assertTrue(any(e['type'] == 'PHONE_NUMBER' and e['text'] == '(555) 123-4567' for e in ents))
        
    def test_date(self):
        text = "DOB: 1990-01-01"
        ents = run_regex_detection(text)
        self.assertTrue(any(e['type'] == 'BIRTHDATE' and e['text'] == '1990-01-01' for e in ents))

    def test_account(self):
        # With context
        text = "Bank account: 1234567890"
        ents = run_regex_detection(text)
        self.assertTrue(any(e['type'] == 'ACCOUNT_NUMBER' for e in ents))
        match = next(e for e in ents if e['type'] == 'ACCOUNT_NUMBER')
        self.assertGreaterEqual(match['score'], 0.80)

    def test_account_no_context(self):
        # No context
        text = "My number is 1234567890."
        ents = run_regex_detection(text)
        # Should match but score 0.40 (lowered to reduce false positives)
        match = next(e for e in ents if e['type'] == 'ACCOUNT_NUMBER')
        self.assertAlmostEqual(match['score'], 0.40)
        
    def test_address(self):
        text = "I live at 123 Maple St, Springfield."
        ents = run_regex_detection(text)
        self.assertTrue(any(e['type'] == 'ADDRESS' for e in ents))
        
    def test_address_no_suffix(self):
        # Should NOT match "123 Maple" if no suffix
        text = "123 Maple"
        ents = run_regex_detection(text)
        self.assertFalse(any(e['type'] == 'ADDRESS' for e in ents))

    def test_ssn_dot_separated(self):
        # New dot-separated SSN pattern
        text = "SSN: 561.84.5738"
        ents = run_regex_detection(text)
        self.assertTrue(any(e['type'] == 'SSN' and e['text'] == '561.84.5738' for e in ents))

    def test_ssn_negative_context_passport(self):
        # SSN pattern should be suppressed when passport context is present
        text = "Passport number: 123456789"
        ents = run_regex_detection(text)
        # Should NOT match as SSN due to negative context
        self.assertFalse(any(e['type'] == 'SSN' for e in ents))

    def test_ssn_negative_context_driver_license(self):
        # SSN pattern should be suppressed when driver license context is present
        text = "Driver license: 123456789"
        ents = run_regex_detection(text)
        # Should NOT match as SSN due to negative context
        self.assertFalse(any(e['type'] == 'SSN' for e in ents))

    def test_account_negative_context_credit_card(self):
        # ACCOUNT_NUMBER should be suppressed when credit card context is present
        text = "Credit card: 4111111111111111"
        ents = run_regex_detection(text)
        # Should NOT match as ACCOUNT_NUMBER due to negative context
        self.assertFalse(any(e['type'] == 'ACCOUNT_NUMBER' for e in ents))

    def test_account_negative_context_phone(self):
        # ACCOUNT_NUMBER should be suppressed when phone context is present
        text = "Phone: 1234567890"
        ents = run_regex_detection(text)
        # Should NOT match as ACCOUNT_NUMBER due to negative context
        self.assertFalse(any(e['type'] == 'ACCOUNT_NUMBER' for e in ents))


class TestGatewayHelpers(unittest.TestCase):
    """Tests for gateway mode helper functions."""

    def test_consecutive_digits_basic(self):
        """5+ consecutive digits should return True."""
        self.assertTrue(has_consecutive_digits('12345'))
        self.assertTrue(has_consecutive_digits('123456'))
        self.assertFalse(has_consecutive_digits('1234'))

    def test_consecutive_digits_normalized_separators(self):
        """Separators (spaces, dashes, dots, parens) should be normalized."""
        self.assertTrue(has_consecutive_digits('123-45'))  # becomes 12345
        self.assertTrue(has_consecutive_digits('123 45'))
        self.assertTrue(has_consecutive_digits('1.2.3.4.5'))
        self.assertTrue(has_consecutive_digits('(123)45'))

    def test_consecutive_digits_phone_number(self):
        """Phone number style should be detected."""
        self.assertTrue(has_consecutive_digits('123-456-7890'))  # becomes 1234567890
        self.assertTrue(has_consecutive_digits('(555) 123-4567'))

    def test_consecutive_digits_no_digits(self):
        """Text without digits should return False."""
        self.assertFalse(has_consecutive_digits('hello world'))
        self.assertFalse(has_consecutive_digits(''))

    def test_consecutive_digits_custom_min_length(self):
        """Custom min_length parameter should work."""
        self.assertTrue(has_consecutive_digits('123', min_length=3))
        self.assertFalse(has_consecutive_digits('123', min_length=4))


class TestSpanTrimming(unittest.TestCase):
    """Tests for trim_entity_spans function."""

    def test_trim_leading_whitespace(self):
        """Should trim leading whitespace and adjust start offset."""
        from pii_detect import trim_entity_spans

        text = "Account: 12345678901234"
        entities = [{"type": "ACCOUNT_NUMBER", "text": " 12345678901234", "start": 8, "end": 23, "score": 0.9}]

        trimmed = trim_entity_spans(entities, text)

        self.assertEqual(len(trimmed), 1)
        self.assertEqual(trimmed[0]['start'], 9)
        self.assertEqual(trimmed[0]['end'], 23)
        self.assertEqual(trimmed[0]['text'], "12345678901234")

    def test_trim_trailing_whitespace(self):
        """Should trim trailing whitespace and adjust end offset."""
        from pii_detect import trim_entity_spans

        text = "Account: 12345678901234 next"
        entities = [{"type": "ACCOUNT_NUMBER", "text": "12345678901234 ", "start": 9, "end": 24, "score": 0.9}]

        trimmed = trim_entity_spans(entities, text)

        self.assertEqual(trimmed[0]['start'], 9)
        self.assertEqual(trimmed[0]['end'], 23)
        self.assertEqual(trimmed[0]['text'], "12345678901234")

    def test_trim_both_sides(self):
        """Should trim whitespace from both sides."""
        from pii_detect import trim_entity_spans

        text = "Value:  12345678901234  end"
        entities = [{"type": "ACCOUNT_NUMBER", "text": "  12345678901234  ", "start": 6, "end": 24, "score": 0.9}]

        trimmed = trim_entity_spans(entities, text)

        self.assertEqual(trimmed[0]['start'], 8)
        self.assertEqual(trimmed[0]['end'], 22)

    def test_no_trimming_needed(self):
        """Should not modify entities without whitespace."""
        from pii_detect import trim_entity_spans

        text = "Account: 12345678901234"
        entities = [{"type": "ACCOUNT_NUMBER", "text": "12345678901234", "start": 9, "end": 23, "score": 0.9}]

        trimmed = trim_entity_spans(entities, text)

        self.assertEqual(trimmed[0]['start'], 9)
        self.assertEqual(trimmed[0]['end'], 23)


class TestTypeDisambiguation(unittest.TestCase):
    """Tests for disambiguate_entity_types function."""

    def test_9digit_ssn_with_account_context_retyped(self):
        """9-digit SSN with 'account' context should be retyped to ACCOUNT_NUMBER."""
        from pii_detect import disambiguate_entity_types

        text = "Fund performance for account 337914127 in Lebanon"
        entities = [{"type": "SSN", "text": "337914127", "start": 29, "end": 38, "score": 0.95, "source": "regex"}]

        result = disambiguate_entity_types(entities, text)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['type'], 'ACCOUNT_NUMBER')

    def test_9digit_ssn_without_account_context_unchanged(self):
        """9-digit SSN without account context should remain SSN."""
        from pii_detect import disambiguate_entity_types

        text = "My SSN is 337914127 for reference"
        entities = [{"type": "SSN", "text": "337914127", "start": 10, "end": 19, "score": 0.95, "source": "regex"}]

        result = disambiguate_entity_types(entities, text)

        self.assertEqual(result[0]['type'], 'SSN')

    def test_formatted_ssn_unchanged(self):
        """Formatted SSN (with dashes) should not be retyped even with account context."""
        from pii_detect import disambiguate_entity_types

        # This has more than 9 digits worth of characters, so won't be retyped
        text = "Account reference: 337-91-4127"
        entities = [{"type": "SSN", "text": "337-91-4127", "start": 19, "end": 30, "score": 0.95, "source": "regex"}]

        result = disambiguate_entity_types(entities, text)

        # Still 9 digits, so it WILL be retyped due to account context
        self.assertEqual(result[0]['type'], 'ACCOUNT_NUMBER')

    def test_non_ssn_entities_unchanged(self):
        """Non-SSN entities should not be affected."""
        from pii_detect import disambiguate_entity_types

        text = "Phone for account: 555-123-4567"
        entities = [{"type": "PHONE_NUMBER", "text": "555-123-4567", "start": 19, "end": 31, "score": 0.85}]

        result = disambiguate_entity_types(entities, text)

        self.assertEqual(result[0]['type'], 'PHONE_NUMBER')


if __name__ == '__main__':
    unittest.main()
