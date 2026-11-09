"""Business logic: ties validation, the database and the AI service together.

The Streamlit UI only calls PatientService; it never touches SQL or the API
directly. Rules implemented here:

* Invalid records are STORED (with their errors) but NEVER sent to the AI.
* Valid records are sent to the AI; the response (or an honest
  "AI analysis unavailable" note) becomes the Remarks.
* Exact duplicates are kept and flagged, never silently removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from .ai_service import AIResult, analyze_patient
from .database import PatientDatabase
from .validation import ValidationResult, calculate_age, duplicate_key, validate_patient

RAW_FIELDS = ("full_name", "date_of_birth", "email", "glucose", "haemoglobin", "cholesterol")

# ai_status values stored in the database
AI_SUCCESS = "success"          # remarks really came from the external API
AI_UNAVAILABLE = "unavailable"  # valid record, but the API call failed
AI_SKIPPED = "skipped"          # invalid record, deliberately not sent


class PatientNotFoundError(LookupError):
    """Raised when an id does not exist."""


@dataclass
class SaveOutcome:
    record: dict
    validation: ValidationResult
    ai: AIResult | None  # None when the AI was not called


class PatientService:
    def __init__(
        self,
        db: PatientDatabase,
        analyzer: Callable[[dict], AIResult] | None = None,
        today: Callable[[], date] = date.today,
    ):
        self.db = db
        self.analyzer = analyzer or analyze_patient
        self._today = today

    # ---- helpers ----------------------------------------------------------
    def _validate(self, raw: dict) -> ValidationResult:
        return validate_patient(**{f: raw.get(f) for f in RAW_FIELDS}, today=self._today())

    @staticmethod
    def _invalid_remarks(validation: ValidationResult) -> str:
        return "Not analysed - record failed validation and was not sent to the AI. " + " ".join(
            validation.errors
        )

    def _run_ai(self, validation: ValidationResult) -> tuple[str, str, AIResult]:
        patient = {
            **validation.values,
            "age_years": calculate_age(validation.dob, self._today()) if validation.dob else None,
        }
        result = self.analyzer(patient)
        if result.ok:
            return result.text, AI_SUCCESS, result
        return f"AI analysis unavailable: {result.error}", AI_UNAVAILABLE, result

    def _refresh_duplicates(self) -> None:
        """Re-compute duplicate flags for all records.

        For every group of identical records, the earliest id is the original
        and the rest are flagged as duplicates of it. Re-computing after each
        change keeps flags correct after edits and deletions.
        """
        first_seen: dict[tuple, int] = {}
        for record in self.db.list_patients():
            key = duplicate_key(record)
            original = first_seen.setdefault(key, record["id"])
            wanted = None if original == record["id"] else original
            if record["duplicate_of"] != wanted:
                self.db.set_duplicate_of(record["id"], wanted)

    # ---- Create -----------------------------------------------------------
    def create_patient(self, raw: dict) -> SaveOutcome:
        validation = self._validate(raw)
        ai_result: AIResult | None = None
        if validation.is_valid:
            remarks, ai_status, ai_result = self._run_ai(validation)
        else:
            remarks, ai_status = self._invalid_remarks(validation), AI_SKIPPED

        patient_id = self.db.insert_patient(
            {
                **validation.values,
                "remarks": remarks,
                "validation_status": validation.status,
                "validation_errors": validation.errors,
                "ai_status": ai_status,
            }
        )
        self._refresh_duplicates()
        return SaveOutcome(self.db.get_patient(patient_id), validation, ai_result)

    # ---- Read -------------------------------------------------------------
    def list_patients(self, search: str | None = None, status: str | None = None) -> list[dict]:
        return self.db.list_patients(search, status)

    def get_patient(self, patient_id: int) -> dict:
        record = self.db.get_patient(patient_id)
        if record is None:
            raise PatientNotFoundError(f"Patient {patient_id} does not exist.")
        return record

    # ---- Update -----------------------------------------------------------
    def update_patient(self, patient_id: int, raw: dict) -> SaveOutcome:
        """Edit an existing record in place (never creates a new one).

        The AI is only called again when needed: the record is valid AND either
        it has no successful analysis yet or the values the AI sees changed.
        So changing just the email keeps the existing remarks and uses no API quota.
        """
        existing = self.get_patient(patient_id)
        validation = self._validate(raw)
        ai_result: AIResult | None = None

        if not validation.is_valid:
            remarks, ai_status = self._invalid_remarks(validation), AI_SKIPPED
        else:
            watched = ("date_of_birth", "glucose", "haemoglobin", "cholesterol")
            inputs_changed = any(existing[f].strip() != validation.values[f] for f in watched)
            if existing["ai_status"] == AI_SUCCESS and not inputs_changed:
                remarks, ai_status = existing["remarks"], AI_SUCCESS
            else:
                remarks, ai_status, ai_result = self._run_ai(validation)

        self.db.update_patient(
            patient_id,
            {
                **validation.values,
                "remarks": remarks,
                "validation_status": validation.status,
                "validation_errors": validation.errors,
                "ai_status": ai_status,
            },
        )
        self._refresh_duplicates()
        return SaveOutcome(self.db.get_patient(patient_id), validation, ai_result)

    def retry_ai(self, patient_id: int) -> SaveOutcome:
        """Re-run the AI for a valid record whose analysis was unavailable."""
        existing = self.get_patient(patient_id)
        raw = {f: existing[f] for f in RAW_FIELDS}
        validation = self._validate(raw)
        if not validation.is_valid:
            return SaveOutcome(existing, validation, None)
        remarks, ai_status, ai_result = self._run_ai(validation)
        self.db.update_patient(patient_id, {"remarks": remarks, "ai_status": ai_status})
        return SaveOutcome(self.db.get_patient(patient_id), validation, ai_result)

    # ---- Delete -----------------------------------------------------------
    def delete_patient(self, patient_id: int) -> None:
        if not self.db.delete_patient(patient_id):
            raise PatientNotFoundError(f"Patient {patient_id} does not exist.")
        self._refresh_duplicates()

    # ---- Dashboard --------------------------------------------------------
    def get_stats(self) -> dict[str, int]:
        records = self.db.list_patients()
        return {
            "total": len(records),
            "valid": sum(r["validation_status"] == "valid" for r in records),
            "invalid": sum(r["validation_status"] == "invalid" for r in records),
            "duplicates": sum(r["duplicate_of"] is not None for r in records),
            "ai_success": sum(r["ai_status"] == AI_SUCCESS for r in records),
            "ai_unavailable": sum(r["ai_status"] == AI_UNAVAILABLE for r in records),
            "ai_skipped": sum(r["ai_status"] == AI_SKIPPED for r in records),
        }
