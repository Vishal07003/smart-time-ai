import re
from accounts.models import TeacherProfile


def generate_next_employee_code() -> str:
    """
    Generates the next sequential teacher code for faculty profiles:
    T-001, T-002, T-003, ...
    Duplicate-safe and preserves existing sequence across the database.
    Does not trust client input.
    """
    existing_codes = TeacherProfile.objects.values_list("employee_code", flat=True)
    numeric_values = []
    for code in existing_codes:
        if not code:
            continue
        match = re.search(r"^T-(\d+)$", code.strip(), re.IGNORECASE)
        if match:
            try:
                numeric_values.append(int(match.group(1)))
            except ValueError:
                pass

    next_seq = (max(numeric_values) + 1) if numeric_values else 1
    candidate = f"T-{next_seq:03d}"

    # Ensure candidate never collides with any pre-existing code
    while TeacherProfile.objects.filter(employee_code__iexact=candidate).exists():
        next_seq += 1
        candidate = f"T-{next_seq:03d}"

    return candidate
