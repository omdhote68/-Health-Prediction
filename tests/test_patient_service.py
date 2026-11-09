import pytest

from src.assessment_data import TEST_RECORDS
from src.patient_service import PatientNotFoundError


# ---- Create -----------------------------------------------------------------
def test_create_valid_patient_calls_ai_and_stores_remarks(service, analyzer, valid_raw):
    outcome = service.create_patient(valid_raw)
    rec = outcome.record
    assert rec["validation_status"] == "valid"
    assert rec["remarks"] == "Mock AI summary."
    assert rec["ai_status"] == "success"
    assert len(analyzer.calls) == 1


def test_ai_receives_only_blood_values_and_age_not_name_or_email(service, analyzer, valid_raw):
    from src.ai_service import build_prompt

    service.create_patient(valid_raw)
    prompt = build_prompt(analyzer.calls[0])
    assert "Test Person" not in prompt and "test@example.com" not in prompt
    assert "95" in prompt and "14.2" in prompt and "180" in prompt
    assert "41 years" in prompt  # born 15/06/1985, "today" fixed at 09/11/2026


def test_invalid_record_is_saved_but_never_sent_to_ai(service, analyzer, valid_raw):
    valid_raw["email"] = "hunter@gmail"
    outcome = service.create_patient(valid_raw)
    assert outcome.record["validation_status"] == "invalid"
    assert outcome.record["ai_status"] == "skipped"
    assert outcome.record["email"] == "hunter@gmail"  # preserved, not corrected
    assert "Email" in outcome.record["validation_errors"][0]
    assert "not sent to the AI" in outcome.record["remarks"]
    assert analyzer.calls == []


def test_ai_failure_marks_unavailable_without_fabricating(db, valid_raw):
    from tests.conftest import FIXED_TODAY, FakeAnalyzer
    from src.patient_service import PatientService

    svc = PatientService(db, analyzer=FakeAnalyzer(ok=False), today=lambda: FIXED_TODAY)
    rec = svc.create_patient(valid_raw).record
    assert rec["validation_status"] == "valid"  # CRUD still works
    assert rec["ai_status"] == "unavailable"
    assert rec["remarks"].startswith("AI analysis unavailable:")
    assert "Mock service down." in rec["remarks"]


# ---- Read -------------------------------------------------------------------
def test_read_returns_all_including_invalid(service, valid_raw):
    service.create_patient(valid_raw)
    service.create_patient({**valid_raw, "full_name": ""})
    assert len(service.list_patients()) == 2
    assert len(service.list_patients(status="invalid")) == 1


def test_get_missing_patient_raises(service):
    with pytest.raises(PatientNotFoundError):
        service.get_patient(123)


# ---- Duplicates -------------------------------------------------------------
def test_exact_duplicate_is_kept_and_flagged(service, valid_raw):
    first = service.create_patient(valid_raw).record
    second = service.create_patient(valid_raw).record
    records = service.list_patients()
    assert len(records) == 2  # not silently removed
    assert records[0]["duplicate_of"] is None
    assert records[1]["duplicate_of"] == first["id"]
    assert second["id"] != first["id"]


def test_editing_original_clears_duplicate_flag(service, valid_raw):
    first = service.create_patient(valid_raw).record
    service.create_patient(valid_raw)
    service.update_patient(first["id"], {**valid_raw, "email": "changed@example.com"})
    assert all(r["duplicate_of"] is None for r in service.list_patients())


def test_deleting_original_clears_duplicate_flag(service, valid_raw):
    first = service.create_patient(valid_raw).record
    service.create_patient(valid_raw)
    service.delete_patient(first["id"])
    remaining = service.list_patients()
    assert len(remaining) == 1 and remaining[0]["duplicate_of"] is None


# ---- Update -----------------------------------------------------------------
def test_update_email_in_place_without_new_ai_call(service, analyzer, valid_raw):
    rec = service.create_patient(valid_raw).record
    outcome = service.update_patient(rec["id"], {**valid_raw, "email": "gokul@infocare.com"})
    assert len(service.list_patients()) == 1  # no new patient created
    assert outcome.record["id"] == rec["id"]
    assert outcome.record["email"] == "gokul@infocare.com"
    assert outcome.record["remarks"] == "Mock AI summary."
    assert len(analyzer.calls) == 1  # email change alone does not re-call the AI


def test_update_blood_value_recalls_ai(service, analyzer, valid_raw):
    rec = service.create_patient(valid_raw).record
    service.update_patient(rec["id"], {**valid_raw, "glucose": "120"})
    assert len(analyzer.calls) == 2


def test_fixing_invalid_record_triggers_first_ai_call(service, analyzer, valid_raw):
    rec = service.create_patient({**valid_raw, "email": "bad"}).record
    assert analyzer.calls == []
    fixed = service.update_patient(rec["id"], valid_raw).record
    assert fixed["validation_status"] == "valid" and fixed["ai_status"] == "success"
    assert len(analyzer.calls) == 1


def test_update_to_invalid_value_flags_record(service, valid_raw):
    rec = service.create_patient(valid_raw).record
    updated = service.update_patient(rec["id"], {**valid_raw, "glucose": "abc"}).record
    assert updated["validation_status"] == "invalid"
    assert updated["ai_status"] == "skipped"


def test_update_missing_patient_raises(service, valid_raw):
    with pytest.raises(PatientNotFoundError):
        service.update_patient(42, valid_raw)


def test_retry_ai_after_failure(db, valid_raw):
    from tests.conftest import FIXED_TODAY, FakeAnalyzer
    from src.patient_service import PatientService

    failing = FakeAnalyzer(ok=False)
    svc = PatientService(db, analyzer=failing, today=lambda: FIXED_TODAY)
    rec = svc.create_patient(valid_raw).record
    assert rec["ai_status"] == "unavailable"

    svc.analyzer = FakeAnalyzer(ok=True)
    retried = svc.retry_ai(rec["id"]).record
    assert retried["ai_status"] == "success" and retried["remarks"] == "Mock AI summary."


# ---- Delete -----------------------------------------------------------------
def test_delete_removes_only_that_record(service, valid_raw):
    a = service.create_patient(valid_raw).record
    b = service.create_patient({**valid_raw, "full_name": "Other Person"}).record
    service.delete_patient(a["id"])
    assert [r["id"] for r in service.list_patients()] == [b["id"]]


def test_delete_missing_patient_raises(service):
    with pytest.raises(PatientNotFoundError):
        service.delete_patient(7)


# ---- Stats ------------------------------------------------------------------
def test_stats(service, valid_raw):
    service.create_patient(valid_raw)
    service.create_patient(valid_raw)  # duplicate
    service.create_patient({**valid_raw, "email": "bad"})
    stats = service.get_stats()
    assert stats == {"total": 3, "valid": 2, "invalid": 1, "duplicates": 1,
                     "ai_success": 2, "ai_unavailable": 0, "ai_skipped": 1}


# ---- The 10 supplied assessment records ------------------------------------
def test_assessment_data_end_to_end(service, analyzer):
    for raw in TEST_RECORDS:
        service.create_patient(raw)
    records = service.list_patients()
    assert len(records) == 10  # all 10 retained, including invalid + duplicate

    by_test = {i + 1: r for i, r in enumerate(records)}
    invalid = {n for n, r in by_test.items() if r["validation_status"] == "invalid"}
    assert invalid == {2, 4, 8}

    for raw, record in zip(TEST_RECORDS, records):
        for field, value in raw.items():
            assert record[field] == value

    assert any("Email" in e for e in by_test[2]["validation_errors"])
    assert any("not a real calendar date" in e for e in by_test[4]["validation_errors"])
    assert len(by_test[8]["validation_errors"]) == 2  # future DOB + malformed email

    assert by_test[6]["duplicate_of"] == by_test[1]["id"]
    assert [n for n, r in by_test.items() if r["duplicate_of"] is not None] == [6]

    # supplied values preserved exactly
    assert by_test[2]["email"] == "hunter@gmail"
    assert by_test[4]["date_of_birth"] == "31.11.2001"
    assert by_test[8]["date_of_birth"] == "19.10.2030"
    assert by_test[1]["date_of_birth"] == "28.01.1960"

    # only the 7 valid records reached the AI
    assert len(analyzer.calls) == 7

    # demo step 3: update an email
    prem = by_test[10]
    updated = service.update_patient(prem["id"], {**{k: prem[k] for k in TEST_RECORDS[0]}, "email": "gokul@infocare.com"})
    assert updated.record["email"] == "gokul@infocare.com" and len(service.list_patients()) == 10

    # demo step 4: delete one
    service.delete_patient(by_test[6]["id"])
    assert len(service.list_patients()) == 9
