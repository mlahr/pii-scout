from __future__ import annotations

import re
from typing import List, Tuple


def normalize_text(text: str) -> Tuple[str, List[int]]:
    """
    Normalize text and return (normalized_str, offset_map).
    offset_map[i] = original_index_of_char_at_i_in_normalized
    """
    normalized = []
    mapping = []

    i = 0
    n = len(text)

    while i < n:
        # Check for de-hyphenation: "-\n"
        if i < n - 2 and text[i] == '-' and text[i + 1] == '\n':
            # Skip both char and newline
            i += 2
            continue

        char = text[i]

        # Replace newlines with space
        if char == '\n':
            char = ' '

        # Collapse whitespace
        if char.isspace():
            # If we just added a space, skip this one
            if normalized and normalized[-1] == ' ':
                i += 1
                continue
            char = ' '

        normalized.append(char)
        mapping.append(i)
        i += 1

    return "".join(normalized), mapping


def is_zip_like(text: str) -> bool:
    return bool(re.fullmatch(r'\d{5}(?:-\d{4})?', text))


def is_postal_4(text: str) -> bool:
    return bool(re.fullmatch(r'\d{4}', text))


def is_ssn_format(text: str) -> bool:
    return bool(re.fullmatch(r'\d{3}-\d{2}-\d{4}|\d{3} \d{2} \d{4}|\d{3}\.\d{2}\.\d{4}', text))


def has_consecutive_digits(text: str, min_length: int = 5) -> bool:
    """Check if text contains min_length consecutive digits after normalizing separators."""
    # Remove common separators: spaces, dashes, dots, parentheses
    normalized = re.sub(r'[\s\-\.\(\)]', '', text)
    return bool(re.search(r'\d{' + str(min_length) + r',}', normalized))


def find_consecutive_digits(text: str, min_length: int = 5) -> List[str]:
    """Find all sequences of min_length consecutive digits after normalizing separators."""
    normalized = re.sub(r'[\s\-\.\(\)]', '', text)
    return re.findall(r'\d{' + str(min_length) + r',}', normalized)


def is_luhn_valid(text: str, min_len: int = 13, max_len: int = 19) -> bool:
    """Return True if the digit string passes Luhn check (typical for card numbers)."""
    digits = re.sub(r'\D', '', text)
    if not digits.isdigit():
        return False
    # Typical card length range
    if len(digits) < min_len or len(digits) > max_len:
        return False
    total = 0
    reverse_digits = digits[::-1]
    for i, ch in enumerate(reverse_digits):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0
