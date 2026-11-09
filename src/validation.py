"""Backend validation rules for patient records.

Everything here is plain Python (no Streamlit, no database), so the same rules
protect the app no matter which screen the data comes from.

Design note: validation never *changes* what the user typed. It only reports
problems. Invalid records are still stored (with their errors) so the
assessment's deliberately-bad test data can be demonstrated.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date

# Accepts dd.mm.yyyy and dd/mm/yyyy (the supplied test data uses dots).
DATE_PATTERN = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$")

# Plain decimal numbers only: "15", "13.5". Optional leading minus so we can
# give a specific "must not be negative" message instead of "not a number".
NUMBER_PATTERN = re.compile(r"^-?\d+(\.\d+)?$")

MIN_BIRTH_YEAR = 1900

BLOOD_FIELDS = {
    "glucose": "Glucose",
    "haemoglobin": "Haemoglobin",
    "cholesterol": "Cholesterol",
}


@dataclass
class ValidationResult:
    """Outcome of validating one patient submission."""

    errors: list[str] = field(default_factory=list)
    # Cleaned (whitespace-stripped) values ready to store. Validation parses
    # dates but keeps the user's original supported date format.
    values: dict[str, str] = field(default_factory=dict)
    dob: date | None = None

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def status(self) -> str:
        return "valid" if self.is_valid else "invalid"


def _as_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def validate_full_name(raw: object) -> str | None:
    if not _as_text(raw):
        return "Full Name is required (it cannot be empty or only spaces)."
    return None


def parse_date_of_birth(raw: object, today: date | None = None) -> tuple[date | None, str | None]:
    """Return (date, None) when valid, otherwise (None, error message)."""
    today = today or date.today()
    text = _as_text(raw)
    if not text:
        return None, "Date of Birth is required."

    match = DATE_PATTERN.match(text)
    if not match:
        return None, (
            f"Date of Birth '{text}' is not in a supported format "
            "(use dd/mm/yyyy or dd.mm.yyyy)."
        )

    day, month, year = (int(g) for g in match.groups())
    if not 1 <= month <= 12:
        return None, f"Date of Birth '{text}' has an invalid month ({month}); months run from 1 to 12."
    if year < MIN_BIRTH_YEAR:
        return None, f"Date of Birth '{text}' has an unrealistic year ({year}); the earliest accepted year is {MIN_BIRTH_YEAR}."

    days_in_month = calendar.monthrange(year, month)[1]
    if not 1 <= day <= days_in_month:
        return None, (
            f"Date of Birth '{text}' is not a real calendar date: "
            f"{calendar.month_name[month]} {year} has only {days_in_month} days."
        )

    parsed = date(year, month, day)
    if parsed > today:
        return None, f"Date of Birth '{text}' is in the future."
    return parsed, None


def validate_email(raw: object) -> str | None:
    text = _as_text(raw)
    if not text:
        return "Email Address is required."
    if " " in text or text.count("@") != 1:
        return f"Email '{text}' is not a valid address (it needs exactly one '@' and no spaces)."

    local, domain = text.split("@")
    labels = domain.split(".")
    problem = (
        not local
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or not re.fullmatch(r"[A-Za-z0-9._%+\-]+", local)
        or len(labels) < 2  # e.g. "hunter@gmail" has no top-level domain
        or any(not lab or lab.startswith("-") or lab.endswith("-") for lab in labels)
        or not all(re.fullmatch(r"[A-Za-z0-9\-]+", lab) for lab in labels)
        or not re.fullmatch(r"[A-Za-z]{2,}", labels[-1])
    )
    if problem:
        return f"Email '{text}' is not a valid address (expected something like name@example.com)."
    return None


def parse_blood_value(raw: object, label: str) -> tuple[float | None, str | None]:
    """Return (number, None) when valid, otherwise (None, error message)."""
    text = _as_text(raw)
    if not text:
        return None, f"{label} is required."
    if not NUMBER_PATTERN.match(text):
        return None, f"{label} '{text}' must be a number."
    number = float(text)
    if number < 0:
        return None, f"{label} '{text}' must not be negative."
    return number, None


def validate_patient(
    full_name: object,
    date_of_birth: object,
    email: object,
    glucose: object,
    haemoglobin: object,
    cholesterol: object,
    today: date | None = None,
) -> ValidationResult:
    """Validate every field and collect ALL problems (not just the first)."""
    result = ValidationResult()

    name_error = validate_full_name(full_name)
    if name_error:
        result.errors.append(name_error)

    dob, dob_error = parse_date_of_birth(date_of_birth, today)
    if dob_error:
        result.errors.append(dob_error)
    result.dob = dob

    email_error = validate_email(email)
    if email_error:
        result.errors.append(email_error)

    blood_inputs = {"glucose": glucose, "haemoglobin": haemoglobin, "cholesterol": cholesterol}
    for key, raw in blood_inputs.items():
        _, error = parse_blood_value(raw, BLOOD_FIELDS[key])
        if error:
            result.errors.append(error)

    result.values = {
        "full_name": _as_text(full_name),
        "date_of_birth": _as_text(date_of_birth),
        "email": _as_text(email),
        "glucose": _as_text(glucose),
        "haemoglobin": _as_text(haemoglobin),
        "cholesterol": _as_text(cholesterol),
    }
    return result


def calculate_age(dob: date, today: date | None = None) -> int:
    today = today or date.today()
    years = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return years


def _normalise_number(text: str) -> tuple[str, object]:
    text = text.strip()
    if NUMBER_PATTERN.match(text):
        return ("number", float(text))
    return ("text", text.casefold())


def duplicate_key(record: dict) -> tuple:
    """Fingerprint used to spot exact duplicate submissions.

    Two records are duplicates when name, date of birth, email and all three
    blood values match (ignoring case, extra spaces, and 15 vs 15.0).
    """
    return (
        " ".join(_as_text(record.get("full_name")).split()).casefold(),
        _as_text(record.get("date_of_birth")).replace(".", "/"),
        _as_text(record.get("email")).casefold(),
        _normalise_number(_as_text(record.get("glucose"))),
        _normalise_number(_as_text(record.get("haemoglobin"))),
        _normalise_number(_as_text(record.get("cholesterol"))),
    )
