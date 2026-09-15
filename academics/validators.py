import re
from django.core.exceptions import ValidationError


def validate_academic_year(value: str) -> str:
    """
    Validates academic year format: YYYY-YYYY (e.g. '2025-2026').
    Enforces that the second year is exactly 1 year after the first year.
    """
    if not value or not isinstance(value, str):
        raise ValidationError("Academic year is required.")

    cleaned = value.strip()
    match = re.fullmatch(r"^(\d{4})-(\d{4})$", cleaned)
    if not match:
        raise ValidationError(
            "Academic year must be in 'YYYY-YYYY' format (e.g., '2025-2026')."
        )

    year1, year2 = int(match.group(1)), int(match.group(2))
    if year2 != year1 + 1:
        raise ValidationError(
            f"Invalid academic year range '{cleaned}'. Second year must be {year1 + 1}."
        )

    if year1 < 1990 or year1 > 2100:
        raise ValidationError("Academic year must be between 1990 and 2100.")

    return cleaned


def normalize_code(value: str) -> str:
    """
    Normalizes code string: trims whitespace and converts to uppercase.
    """
    if not value or not isinstance(value, str):
        return ""
    return value.strip().upper()


def validate_code_format(value: str) -> str:
    """
    Validates code format for Department, Program, and Subject:
    - 2 to 30 characters
    - Letters, numbers, hyphens, underscores, and dots only
    - No spaces
    """
    if not value or not isinstance(value, str) or not value.strip():
        raise ValidationError("Code is required.")

    cleaned = normalize_code(value)

    if len(cleaned) < 2:
        raise ValidationError("Code must be at least 2 characters long.")

    if len(cleaned) > 30:
        raise ValidationError("Code cannot exceed 30 characters.")

    if not re.fullmatch(r"^[A-Z0-9\-_.]+$", cleaned):
        raise ValidationError(
            "Code can only contain uppercase letters, numbers, hyphens (-), underscores (_), and dots (.)."
        )

    return cleaned


def normalize_string(value: str) -> str:
    """
    Trims leading/trailing whitespace and collapses multiple consecutive spaces.
    """
    if not value or not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def validate_non_empty_name(value: str, field_label: str = "Name") -> str:
    """
    Validates that a name field is not empty or whitespace-only.
    """
    if not value or not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_label} is required and cannot be empty.")

    cleaned = normalize_string(value)
    if len(cleaned) < 2:
        raise ValidationError(f"{field_label} must be at least 2 characters long.")

    return cleaned


def validate_positive_integer(value: int, field_label: str = "Capacity") -> int:
    """
    Validates that an integer value is strictly positive (> 0).
    """
    if value is None or value <= 0:
        raise ValidationError(f"{field_label} must be a positive integer greater than 0.")
    return value


def validate_non_negative(value, field_label: str = "Value"):
    """
    Validates that a numeric value is non-negative (>= 0).
    """
    if value is None or value < 0:
        raise ValidationError(f"{field_label} cannot be negative.")
    return value
