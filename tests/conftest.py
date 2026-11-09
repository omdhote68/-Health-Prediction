"""Shared test setup.

Safety guarantees for every test:
* No real API key is visible (so no test can ever call the real Gemini API).
* The real assessment database (data/patients.db) is never used: tests build
  their own database inside pytest's temporary folder.
"""

from datetime import date

import pytest

from src.ai_service import AIResult
from src.database import PatientDatabase
from src.patient_service import PatientService

FIXED_TODAY = date(2026, 11, 9)


@pytest.fixture(autouse=True)
def no_real_api_or_db(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("HEALTH_DB_PATH", str(tmp_path / "should_not_be_used.db"))


@pytest.fixture
def db(tmp_path):
    return PatientDatabase(tmp_path / "test_patients.db")


class FakeAnalyzer:
    """Stands in for the Gemini call and records how often it was used."""

    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def __call__(self, patient):
        self.calls.append(patient)
        if self.ok:
            return AIResult(ok=True, text="Mock AI summary.", model="mock")
        return AIResult(ok=False, error="Mock service down.", model="mock")


@pytest.fixture
def analyzer():
    return FakeAnalyzer()


@pytest.fixture
def service(db, analyzer):
    return PatientService(db, analyzer=analyzer, today=lambda: FIXED_TODAY)


@pytest.fixture
def valid_raw():
    return {
        "full_name": "Test Person",
        "date_of_birth": "15/06/1985",
        "email": "test@example.com",
        "glucose": "95",
        "haemoglobin": "14.2",
        "cholesterol": "180",
    }
