"""SQLite storage for patient records.

Only database work lives here: no Streamlit, no validation, no AI calls.
Every query is parameterised (the ? placeholders) so user text can never be
executed as SQL.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name         TEXT NOT NULL,
    date_of_birth     TEXT NOT NULL,
    email             TEXT NOT NULL,
    glucose           TEXT NOT NULL,
    haemoglobin       TEXT NOT NULL,
    cholesterol       TEXT NOT NULL,
    remarks           TEXT NOT NULL DEFAULT '',
    validation_status TEXT NOT NULL,
    validation_errors TEXT NOT NULL DEFAULT '[]',
    ai_status         TEXT NOT NULL DEFAULT 'skipped',
    duplicate_of      INTEGER,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
"""

# Columns the caller supplies on insert/update. Values are stored as the text
# the user entered so invalid test data (e.g. "31/11/2001") is preserved exactly.
WRITABLE_COLUMNS = (
    "full_name",
    "date_of_birth",
    "email",
    "glucose",
    "haemoglobin",
    "cholesterol",
    "remarks",
    "validation_status",
    "validation_errors",
    "ai_status",
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class PatientDatabase:
    """Small wrapper around one SQLite file."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        # CREATE TABLE IF NOT EXISTS: safe on every start, never wipes data.
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict:
        record = dict(row)
        record["validation_errors"] = json.loads(record["validation_errors"] or "[]")
        return record

    @staticmethod
    def _prepare(data: dict) -> dict:
        prepared = {col: data[col] for col in WRITABLE_COLUMNS if col in data}
        if isinstance(prepared.get("validation_errors"), (list, tuple)):
            prepared["validation_errors"] = json.dumps(list(prepared["validation_errors"]))
        return prepared

    # ---- Create -----------------------------------------------------------
    def insert_patient(self, data: dict) -> int:
        row = self._prepare(data)
        now = _now()
        row["created_at"] = now
        row["updated_at"] = now
        columns = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                f"INSERT INTO patients ({columns}) VALUES ({placeholders})",
                list(row.values()),
            )
            return int(cursor.lastrowid)

    # ---- Read -------------------------------------------------------------
    def get_patient(self, patient_id: int) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        return self._to_dict(row) if row else None

    def list_patients(self, search: str | None = None, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM patients"
        clauses: list[str] = []
        params: list[object] = []
        if search and search.strip():
            like = f"%{search.strip()}%"
            clauses.append("(full_name LIKE ? OR email LIKE ?)")
            params.extend([like, like])
        if status in ("valid", "invalid"):
            clauses.append("validation_status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._to_dict(r) for r in rows]

    # ---- Update -----------------------------------------------------------
    def update_patient(self, patient_id: int, data: dict) -> bool:
        row = self._prepare(data)
        row["updated_at"] = _now()
        assignments = ", ".join(f"{col} = ?" for col in row)
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                f"UPDATE patients SET {assignments} WHERE id = ?",
                [*row.values(), patient_id],
            )
            return cursor.rowcount > 0

    def set_duplicate_of(self, patient_id: int, duplicate_of: int | None) -> None:
        """Flag/unflag a duplicate without touching updated_at."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE patients SET duplicate_of = ? WHERE id = ?",
                (duplicate_of, patient_id),
            )

    # ---- Delete -----------------------------------------------------------
    def delete_patient(self, patient_id: int) -> bool:
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
            return cursor.rowcount > 0
