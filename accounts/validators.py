import re
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator


def normalize_email(value: str) -> str:
    """
    Normalizes email address by trimming whitespace and converting to lowercase.
    """
    if not value or not isinstance(value, str):
        return ""
    return value.strip().lower()


def validate_email_custom(value: str) -> str:
    """
    Validates email format, length, and disallows spaces or invalid characters.
    """
    if not value or not isinstance(value, str) or not value.strip():
        raise ValidationError("Email is required.")

    cleaned = normalize_email(value)

    if len(cleaned) > 254:
        raise ValidationError("Email cannot exceed 254 characters.")

    if " " in cleaned:
        raise ValidationError("Email cannot contain spaces.")

    # Validate standard email structure
    validator = EmailValidator(message="Enter a valid email address.")
    validator(cleaned)

    parts = cleaned.split("@")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValidationError("Enter a valid email address.")

    domain = parts[1]
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValidationError("Enter a valid email address with a valid domain.")

    return cleaned


def normalize_indian_phone(value: str) -> str:
    """
    Normalizes an Indian phone number to a standard 10-digit string.
    Strips country code (+91, 91), leading zeros, spaces, hyphens, and parentheses.
    """
    if not value:
        return ""
    if not isinstance(value, str):
        value = str(value)

    cleaned = value.strip()
    if not cleaned:
        return ""

    # Remove formatting characters
    cleaned = re.sub(r"[\s\-\(\)\.]", "", cleaned)

    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    elif cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]

    return cleaned


def validate_indian_phone(value: str) -> str:
    """
    Validates that a phone number is a valid 10-digit Indian mobile number.
    - First digit must be 6, 7, 8, or 9
    - Exactly 10 digits
    - No letters or disallowed characters
    - Rejects invalid repeated dummy numbers
    """
    if not value:
        return ""
    if not isinstance(value, str):
        value = str(value)

    raw = value.strip()
    if not raw:
        return ""

    if re.search(r"[a-zA-Z]", raw):
        raise ValidationError("Phone number cannot contain letters.")

    cleaned = normalize_indian_phone(raw)

    if not re.fullmatch(r"^[6-9]\d{9}$", cleaned):
        raise ValidationError(
            "Enter a valid 10-digit Indian mobile number starting with 6, 7, 8, or 9."
        )

    # Reject identical repeated digits e.g., 9999999999, 8888888888, 7777777777, 6666666666
    if len(set(cleaned)) == 1:
        raise ValidationError("Phone number cannot consist of identical repeated digits.")

    return cleaned


def normalize_username(value: str) -> str:
    """
    Trims leading and trailing whitespace from username.
    """
    if not value or not isinstance(value, str):
        return ""
    return value.strip()


def validate_username_custom(value: str) -> str:
    """
    Validates username rules:
    - Required
    - 3 to 30 characters
    - Only letters, numbers, underscores (_), and periods (.)
    - No spaces
    - No disallowed special characters
    """
    if not value or not isinstance(value, str) or not value.strip():
        raise ValidationError("Username is required.")

    cleaned = normalize_username(value)

    if len(cleaned) < 3:
        raise ValidationError("Username must be at least 3 characters long.")

    if len(cleaned) > 30:
        raise ValidationError("Username cannot exceed 30 characters.")

    if " " in value:
        raise ValidationError("Username cannot contain spaces.")

    if not re.fullmatch(r"^[a-zA-Z0-9_.]+$", cleaned):
        raise ValidationError(
            "Username can only contain letters, numbers, underscores (_), and periods (.)."
        )

    return cleaned

def normalize_name(value: str) -> str:
    """
    Trims excess whitespace and collapses multiple consecutive spaces.
    """
    if not value or not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def validate_name_custom(value: str) -> str:
    """
    Validates first_name and last_name:
    - Optional (empty string is permitted)
    - Max 50 characters
    - Alphabetic characters, spaces, hyphens, and apostrophes only
    - No numbers or special characters
    - Rejects whitespace-only inputs
    """
    if not value:
        return ""
    if not isinstance(value, str):
        value = str(value)

    raw = value.strip()
    if not raw:
        return ""

    cleaned = normalize_name(raw)

    if len(cleaned) > 50:
        raise ValidationError("Name cannot exceed 50 characters.")

    if re.search(r"\d", cleaned):
        raise ValidationError("Name cannot contain numbers.")

    if not re.fullmatch(r"^[a-zA-Z\s'-]+$", cleaned):
        raise ValidationError(
            "Name can only contain alphabetic letters, spaces, hyphens, and apostrophes."
        )

    return cleaned


def validate_role_custom(value: str) -> str:
    """
    Validates that the role is one of the allowed SMART-TIME AI roles.
    """
    allowed_roles = {"STAFF", "TEACHER", "STUDENT"}
    if not value or not isinstance(value, str):
        raise ValidationError("Role is required.")

    cleaned = value.strip().upper()
    if cleaned not in allowed_roles:
        raise ValidationError(
            f"Invalid role '{value}'. Allowed roles are: STAFF, TEACHER, STUDENT."
        )

    return cleaned
