"""
CSV parsing and normalization utilities for robust handling of real-world files.

This module provides utilities for:
- Delimiter auto-detection (comma, semicolon, tab)
- Header normalization (BOM removal, whitespace trimming, duplicate handling)
- Email extraction from various formats (Name <email>, "email", etc.)
- Email normalization (lowercase domain, strip whitespace)
"""

import re
from typing import Any

# BOM characters to strip
BOM_CHARS = "\ufeff\ufffe"

# Common email column name patterns (lowercase, without spaces/dashes/underscores)
EMAIL_COLUMN_EXACT = {"email", "mail", "emailaddress", "emailaddr", "useremail", "contactemail"}
EMAIL_COLUMN_CONTAINS = {"email", "e-mail", "e_mail", "mail"}

# Regex for extracting email from "Name <email@domain.com>" format
ANGLE_BRACKET_EMAIL_RE = re.compile(r"<([^<>@\s]+@[^<>@\s]+)>")
# Regex for extracting email from "email@domain.com (Name)" format
PAREN_EMAIL_RE = re.compile(r"^([^@\s]+@[^@\s]+)\s*\(.*\)$")
# Basic email validation regex
BASIC_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def detect_delimiter(
    content: str,
    candidates: list[str] | None = None,
    sample_lines: int = 5,
) -> str:
    """
    Detect CSV delimiter by analyzing the first few lines.

    Strategy:
    1. Count occurrences of each candidate delimiter in each line
    2. Pick the delimiter with the most consistent count across lines
    3. Prefer comma if there's a tie

    Args:
        content: The CSV content as a string
        candidates: List of candidate delimiters (default: [',', ';', '\\t'])
        sample_lines: Number of lines to analyze (default: 5)

    Returns:
        The detected delimiter character
    """
    if candidates is None:
        candidates = [",", ";", "\t"]

    lines = content.strip().split("\n")[:sample_lines]
    if not lines:
        return ","  # Default to comma

    # Remove BOM from first line if present
    if lines[0] and lines[0][0] in BOM_CHARS:
        lines[0] = lines[0].lstrip(BOM_CHARS)

    # Count delimiter occurrences per line, ignoring content in quotes
    delimiter_scores: dict[str, tuple[float, int]] = {}

    for delim in candidates:
        counts: list[int] = []
        for line in lines:
            # Simple quote-aware counting: skip content between quotes
            count = _count_delimiter_outside_quotes(line, delim)
            counts.append(count)

        if not counts or all(c == 0 for c in counts):
            continue

        # Calculate consistency score: lower variance = more consistent
        avg = sum(counts) / len(counts)
        if avg == 0:
            continue

        variance = sum((c - avg) ** 2 for c in counts) / len(counts)
        # Score: higher average with lower variance is better
        # Normalize variance by average to make comparable
        consistency = avg / (1 + variance / avg) if avg > 0 else 0

        delimiter_scores[delim] = (consistency, int(avg))

    if not delimiter_scores:
        return ","  # Default to comma

    # Pick delimiter with highest consistency score
    # If tie, prefer comma > semicolon > tab
    best_delim = ","
    best_score = (0.0, 0)

    for delim in [",", ";", "\t"]:
        if delim in delimiter_scores:
            score = delimiter_scores[delim]
            if score > best_score:
                best_score = score
                best_delim = delim

    return best_delim


def _count_delimiter_outside_quotes(line: str, delim: str) -> int:
    """Count delimiter occurrences outside of quoted strings."""
    count = 0
    in_quotes = False
    quote_char = None

    for char in line:
        if char in ('"', "'") and not in_quotes:
            in_quotes = True
            quote_char = char
        elif char == quote_char and in_quotes:
            in_quotes = False
            quote_char = None
        elif char == delim and not in_quotes:
            count += 1

    return count


def normalize_headers(headers: list[str]) -> tuple[list[str], dict[str, Any]]:
    """
    Normalize CSV headers: trim whitespace, remove BOM, handle duplicates.

    Duplicate handling:
    - First occurrence keeps original name
    - Subsequent occurrences get "_2", "_3", etc. suffix

    Args:
        headers: List of header strings from CSV

    Returns:
        Tuple of (normalized_headers, mapping_info)
        mapping_info contains:
        - duplicates: dict mapping original name to list of renamed versions
        - original_to_normalized: dict mapping original index to normalized name
    """
    normalized: list[str] = []
    seen: dict[str, int] = {}
    duplicates: dict[str, list[str]] = {}
    original_to_normalized: dict[int, str] = {}

    for i, header in enumerate(headers):
        # Strip BOM and whitespace
        clean = header.strip().lstrip(BOM_CHARS).strip()

        # Handle empty headers
        if not clean:
            clean = f"column_{i + 1}"

        # Handle duplicates
        if clean in seen:
            # This is a duplicate
            seen[clean] += 1
            new_name = f"{clean}_{seen[clean]}"

            # Track duplicates for logging
            if clean not in duplicates:
                duplicates[clean] = [clean]  # Include original
            duplicates[clean].append(new_name)

            clean = new_name
        else:
            seen[clean] = 1

        normalized.append(clean)
        original_to_normalized[i] = clean

    mapping_info = {
        "duplicates": duplicates,
        "original_to_normalized": original_to_normalized,
        "had_duplicates": len(duplicates) > 0,
    }

    return normalized, mapping_info


def extract_email_from_field(value: str) -> str:
    """
    Extract email address from various field formats.

    Supported formats:
    - "Name <email@domain.com>" -> email@domain.com
    - "email@domain.com (Name)" -> email@domain.com
    - "<email@domain.com>" -> email@domain.com
    - '"email@domain.com"' -> email@domain.com
    - Plain email -> email@domain.com

    Args:
        value: The field value that may contain an email

    Returns:
        The extracted email address, or the original value if no pattern matched
    """
    if not value:
        return ""

    # Strip whitespace
    value = value.strip()

    # Remove surrounding quotes
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1].strip()

    # Try angle bracket format: "Name <email@domain.com>" or "<email@domain.com>"
    match = ANGLE_BRACKET_EMAIL_RE.search(value)
    if match:
        return match.group(1).strip()

    # Try parentheses format: "email@domain.com (Name)"
    match = PAREN_EMAIL_RE.match(value)
    if match:
        return match.group(1).strip()

    # Return cleaned value (might be a plain email already)
    return value


def normalize_email(email: str) -> str:
    """
    Normalize an email address for consistent processing.

    Normalization steps:
    1. Strip leading/trailing whitespace
    2. Remove surrounding quotes or angle brackets
    3. Lowercase the domain part (preserve local part case per RFC 5321)
    4. Remove common trailing punctuation

    Args:
        email: The email address to normalize

    Returns:
        The normalized email address, or empty string if invalid
    """
    if not email:
        return ""

    # Strip whitespace
    email = email.strip()

    # Remove surrounding quotes
    if (email.startswith('"') and email.endswith('"')) or (
        email.startswith("'") and email.endswith("'")
    ):
        email = email[1:-1].strip()

    # Remove surrounding angle brackets
    if email.startswith("<") and email.endswith(">"):
        email = email[1:-1].strip()

    # Remove trailing punctuation (but not valid email chars)
    email = email.rstrip(".,;:!?")

    # Split and normalize
    if "@" not in email:
        return ""

    parts = email.rsplit("@", 1)
    if len(parts) != 2:
        return ""

    local_part, domain = parts

    # Validate parts
    if not local_part or not domain:
        return ""

    # Lowercase domain only (local part is case-sensitive per RFC, though rarely enforced)
    domain = domain.lower()

    # Remove any whitespace that might have snuck in
    local_part = local_part.strip()
    domain = domain.strip()

    return f"{local_part}@{domain}"


def is_likely_email_column(header: str) -> bool:
    """
    Check if a header name is likely to contain email addresses.

    Args:
        header: The column header name

    Returns:
        True if the header looks like an email column
    """
    if not header:
        return False

    # Normalize for comparison
    header_lower = header.lower().strip()
    header_normalized = header_lower.replace(" ", "").replace("-", "").replace("_", "")

    # Exact matches
    if header_normalized in EMAIL_COLUMN_EXACT:
        return True

    # Contains email-related terms
    for pattern in EMAIL_COLUMN_CONTAINS:
        if pattern in header_lower:
            return True

    return False


def detect_email_columns(headers: list[str]) -> list[str]:
    """
    Detect which columns likely contain email addresses.

    Args:
        headers: List of column header names

    Returns:
        List of column names that appear to be email columns
    """
    candidates = []
    for header in headers:
        if is_likely_email_column(header):
            candidates.append(header)
    return candidates


def parse_csv_header(content: str, delimiter: str | None = None) -> list[str]:
    """
    Parse just the header row from CSV content.

    Args:
        content: The CSV content
        delimiter: The delimiter to use (auto-detected if None)

    Returns:
        List of header column names
    """
    if not content:
        return []

    # Get first line
    first_line = content.split("\n", 1)[0]

    # Strip BOM
    first_line = first_line.lstrip(BOM_CHARS).strip()

    if not first_line:
        return []

    # Detect delimiter if not provided
    if delimiter is None:
        delimiter = detect_delimiter(content)

    # Simple split - handles basic cases
    # For quoted fields, we do a quote-aware split
    headers = _split_csv_line(first_line, delimiter)

    return headers


def _split_csv_line(line: str, delimiter: str) -> list[str]:
    """Split a CSV line respecting quoted fields."""
    fields: list[str] = []
    current_field = ""
    in_quotes = False
    quote_char = None

    for char in line:
        if char in ('"', "'") and not in_quotes:
            in_quotes = True
            quote_char = char
            current_field += char
        elif char == quote_char and in_quotes:
            in_quotes = False
            quote_char = None
            current_field += char
        elif char == delimiter and not in_quotes:
            fields.append(current_field.strip())
            current_field = ""
        else:
            current_field += char

    # Don't forget the last field
    fields.append(current_field.strip())

    # Clean up quotes from field values
    cleaned_fields = []
    for field in fields:
        if (field.startswith('"') and field.endswith('"')) or (
            field.startswith("'") and field.endswith("'")
        ):
            field = field[1:-1]
        cleaned_fields.append(field)

    return cleaned_fields
