from datetime import date

import pytest

from src.validation import (
    calculate_age,
    duplicate_key,
    parse_blood_value,
    parse_date_of_birth,
    validate_email,
    validate_full_name,
    validate_patient,
)

TODAY = date(2026, 11, 9)


# ---- Email ------------------------------------------------------------------
@pytest.mark.parametrize(
    "email",
    ["robyn@gmail.com", "timd@smh.com.au", "Larry@hotmail.com", "a.b+c@sub.example.org"],
)
def test_valid_emails(email):
    assert validate_email(email) is None


@pytest.mark.parametrize(
    "email",
    ["hunter@gmail", "Kris.wu.gmail.com", "", "   ", "a@@b.com", "a b@c.com", "@x.com", ".a@x.com", "a..b@x.com", "a@x..com", "a@-x.com", "a@x.c"],
)
def test_invalid_emails(email):
    assert validate_email(email) is not None


# ---- Date of birth ----------------------------------------------------------
@pytest.mark.parametrize("raw", ["28.01.1960", "28/01/1960", " 28.01.1960 ", "9.2.2000"])
def test_valid_dates_both_separators(raw):
    parsed, error = parse_date_of_birth(raw, TODAY)
    assert error is None and parsed is not None


def test_date_dots_and_slashes_give_same_date():
    assert parse_date_of_birth("28.01.1960", TODAY)[0] == parse_date_of_birth("28/01/1960", TODAY)[0]


def test_impossible_date_31_nov():
    parsed, error = parse_date_of_birth("31.11.2001", TODAY)
    assert parsed is None
    assert "not a real calendar date" in error and "30 days" in error


def test_leap_day_handling():
    assert parse_date_of_birth("29/02/2000", TODAY)[1] is None
    assert parse_date_of_birth("29/02/2001", TODAY)[1] is not None


def test_future_date_rejected():
    parsed, error = parse_date_of_birth("19.10.2030", TODAY)
    assert parsed is None and "future" in error


def test_today_is_not_future():
    assert parse_date_of_birth("09/11/2026", TODAY)[1] is None


@pytest.mark.parametrize("raw", ["", "  ", "1990-12-10", "10-12-1990", "abc", "32/01/1990", "10/13/1990", "10/12/90", "01/01/1850"])
def test_bad_date_formats_rejected(raw):
    assert parse_date_of_birth(raw, TODAY)[1] is not None


# ---- Blood values -----------------------------------------------------------
@pytest.mark.parametrize("raw, expected", [("232", 232.0), ("13.5", 13.5), (" 15 ", 15.0), ("0", 0.0)])
def test_numeric_blood_values(raw, expected):
    assert parse_blood_value(raw, "Glucose") == (expected, None)


@pytest.mark.parametrize("raw", ["abc", "12abc", "1,5", "1e3", "1_0", "nan", "inf", ".5", "5."])
def test_non_numeric_blood_values(raw):
    value, error = parse_blood_value(raw, "Glucose")
    assert value is None and "must be a number" in error


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_empty_blood_values(raw):
    value, error = parse_blood_value(raw, "Glucose")
    assert value is None and "required" in error


def test_negative_blood_value():
    value, error = parse_blood_value("-5", "Cholesterol")
    assert value is None and "negative" in error


# ---- Required fields / whole record ----------------------------------------
def test_full_name_required():
    assert validate_full_name("") is not None
    assert validate_full_name("   ") is not None
    assert validate_full_name(None) is not None
    assert validate_full_name("Robyn Pears") is None


def test_missing_required_fields_reports_everything():
    result = validate_patient("", "", "", "", "", "", today=TODAY)
    assert not result.is_valid
    assert len(result.errors) == 6


def test_valid_record_preserves_date_separator():
    result = validate_patient("Robyn Pears", "28.01.1960", "robyn@gmail.com", "232", "13.5", "180", today=TODAY)
    assert result.is_valid
    assert result.values["date_of_birth"] == "28.01.1960"
    assert result.values["glucose"] == "232"
    assert result.values["email"] == "robyn@gmail.com"


def test_invalid_record_preserves_raw_values():
    result = validate_patient("Peter Larry", "31.11.2001", "Larry@hotmail.com", "88", "11.5", "165", today=TODAY)
    assert not result.is_valid
    assert result.values["date_of_birth"] == "31.11.2001"  # raw text kept


def test_kris_wu_has_two_errors():
    result = validate_patient("Kris Wu", "19.10.2030", "Kris.wu.gmail.com", "79", "16.5", "197", today=TODAY)
    assert len(result.errors) == 2
    assert any("future" in e for e in result.errors)
    assert any("Email" in e for e in result.errors)


def test_age_calculation():
    assert calculate_age(date(1960, 1, 28), TODAY) == 66
    assert calculate_age(date(2000, 11, 10), TODAY) == 25  # birthday not reached yet
    assert calculate_age(date(2000, 11, 9), TODAY) == 26


# ---- Duplicate detection ----------------------------------------------------
def _rec(**over):
    base = {"full_name": "Robyn Pears", "date_of_birth": "28/01/1960", "email": "robyn@gmail.com",
            "glucose": "232", "haemoglobin": "13.5", "cholesterol": "180"}
    return {**base, **over}


def test_duplicate_key_matches_identical_records():
    assert duplicate_key(_rec()) == duplicate_key(_rec())


def test_duplicate_key_ignores_case_spacing_and_trailing_zero():
    assert duplicate_key(_rec()) == duplicate_key(_rec(full_name="  robyn   PEARS ", email="ROBYN@gmail.com", haemoglobin="13.50"))


def test_duplicate_key_differs_when_values_differ():
    assert duplicate_key(_rec()) != duplicate_key(_rec(glucose="233"))
    assert duplicate_key(_rec()) != duplicate_key(_rec(email="other@gmail.com"))
