from src.database import PatientDatabase


def _row(**over):
    base = {
        "full_name": "A B",
        "date_of_birth": "01/01/1990",
        "email": "a@b.com",
        "glucose": "90",
        "haemoglobin": "14",
        "cholesterol": "170",
        "remarks": "r",
        "validation_status": "valid",
        "validation_errors": [],
        "ai_status": "success",
    }
    return {**base, **over}


def test_database_file_and_table_created_automatically(tmp_path):
    path = tmp_path / "sub" / "new.db"
    assert not path.exists()
    PatientDatabase(path)
    assert path.exists()


def test_insert_and_get(db):
    pid = db.insert_patient(_row())
    rec = db.get_patient(pid)
    assert rec["full_name"] == "A B"
    assert rec["validation_errors"] == []
    assert rec["created_at"] and rec["updated_at"]


def test_validation_errors_round_trip_as_list(db):
    pid = db.insert_patient(_row(validation_errors=["bad email", "bad date"], validation_status="invalid"))
    assert db.get_patient(pid)["validation_errors"] == ["bad email", "bad date"]


def test_list_returns_all_in_id_order(db):
    ids = [db.insert_patient(_row(full_name=f"P{i}")) for i in range(3)]
    assert [r["id"] for r in db.list_patients()] == ids


def test_search_and_status_filter(db):
    db.insert_patient(_row(full_name="Robyn Pears", email="robyn@gmail.com"))
    db.insert_patient(_row(full_name="Kris Wu", email="bad", validation_status="invalid"))
    assert [r["full_name"] for r in db.list_patients(search="rob")] == ["Robyn Pears"]
    assert [r["full_name"] for r in db.list_patients(search="gmail")] == ["Robyn Pears"]
    assert [r["full_name"] for r in db.list_patients(status="invalid")] == ["Kris Wu"]


def test_update_changes_same_row_without_creating_new(db):
    pid = db.insert_patient(_row())
    assert db.update_patient(pid, {"email": "gokul@infocare.com"}) is True
    assert len(db.list_patients()) == 1
    assert db.get_patient(pid)["email"] == "gokul@infocare.com"


def test_update_missing_id_returns_false(db):
    assert db.update_patient(999, {"email": "x@y.com"}) is False


def test_delete(db):
    pid = db.insert_patient(_row())
    assert db.delete_patient(pid) is True
    assert db.get_patient(pid) is None
    assert db.delete_patient(pid) is False


def test_persistence_across_restart(tmp_path):
    path = tmp_path / "persist.db"
    first = PatientDatabase(path)
    pid = first.insert_patient(_row(full_name="Persistent Person"))
    del first
    second = PatientDatabase(path)  # simulates restarting the app
    assert second.get_patient(pid)["full_name"] == "Persistent Person"


def test_sql_injection_text_is_stored_literally(db):
    nasty = "Robert'); DROP TABLE patients;--"
    pid = db.insert_patient(_row(full_name=nasty))
    assert db.get_patient(pid)["full_name"] == nasty
    assert len(db.list_patients(search="'); DROP")) == 1
    assert len(db.list_patients()) == 1  # table still exists


def test_set_duplicate_of_does_not_touch_updated_at(db):
    pid = db.insert_patient(_row())
    before = db.get_patient(pid)["updated_at"]
    db.set_duplicate_of(pid, 5)
    after = db.get_patient(pid)
    assert after["duplicate_of"] == 5 and after["updated_at"] == before
