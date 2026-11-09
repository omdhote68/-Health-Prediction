# Code Walkthrough (interview preparation)

## Big picture
```
app.py (screens)  →  patient_service.py (rules/flow)  →  validation.py  (is the data OK?)
                                                      →  database.py    (SQLite)
                                                      →  ai_service.py  (Gemini API)
```
Each file has one job, so any part can be explained, tested or replaced alone. The UI never contains SQL or API code.

## validation.py - "is this data acceptable?"
- Pure Python functions, no database or UI. Returns **all** errors, not just the first.
- Date: a regex accepts `dd.mm.yyyy` / `dd/mm/yyyy`; `calendar.monthrange` knows how many days a month has (so 31.11.2001 fails with "November 2001 has only 30 days", and leap years work); then a future-date check.
- Email: exactly one `@`, a valid local part, a domain with at least one dot and an alphabetic ending. That is why `hunter@gmail` and `Kris.wu.gmail.com` fail.
- Numbers: plain decimals only (a regex), so `abc`, `1e3`, `nan` are rejected; negatives get their own message.
- Key idea: validation **reports** problems; it never silently "fixes" data. It parses supported dates for validation but saves their supplied text and separator.
- `duplicate_key` builds a fingerprint (name, DOB, email, three values) so "Robyn Pears" == "robyn pears" and `15` == `15.0`.

## database.py - "store and fetch"
- One table `patients` with the required columns plus `ai_status` and `duplicate_of`.
- `CREATE TABLE IF NOT EXISTS` runs at start → the file is created automatically and **never wipes data**.
- All SQL uses `?` placeholders (parameterised) → SQL injection safe (there is a test with `'); DROP TABLE`).
- Values are stored as text, so supplied date separators and invalid entries such as `31.11.2001` are kept exactly.
- `closing(conn), conn` = close the connection and commit/rollback automatically.

## ai_service.py - "talk to Gemini safely"
- `build_prompt`: asks for a short, cautious, non-diagnostic note; says units are unknown; asks the user to provide/confirm missing units and laboratory reference ranges; forbids diagnosis, treatment and invented numeric ranges; recommends a professional. Sends age + three values only (privacy: no name/email).
- Key comes from `GEMINI_API_KEY` (environment / `.env`), never in code.
- `client.models.generate_content(model, contents, config)` is the call; the model name is `GEMINI_MODEL` or the default.
- Returns an `AIResult(ok, text, error)` and **never raises**. `friendly_error` maps exceptions (bad key 401/403, rate limit 429, 5xx, timeout, network) to plain messages without leaking raw error text.
- If anything fails, there is **no fake answer** - the caller records "AI analysis unavailable".

## patient_service.py - "the workflow"
- `create_patient`: validate → if valid call AI → else store with `ai_status=skipped` → insert → refresh duplicate flags.
- `update_patient`: edits the same row; calls the AI again only if the record is valid and (no successful analysis yet **or** DOB/blood values changed).
- `_refresh_duplicates`: groups identical records; the earliest is the original, the rest get `duplicate_of=<id>`. Recomputed after every change so flags stay correct after edits/deletes.
- `analyzer` is injectable → tests pass a fake, so no real API is used.

## app.py - "the screens"
Streamlit pages: Dashboard, Add Patient (with test-data pre-fill), Patient Records (search/filter), Update, Delete (two-step confirmation), API / AI Analysis (connection test + retry), About (disclaimer). Uses `st.session_state` for messages that survive `st.rerun()`.

## Likely interview questions
- *Why store invalid records?* The assessment requires entering them; they are flagged and kept out of the AI.
- *Why not send name/email to Gemini?* Data minimisation - the AI only needs the values.
- *What if the API is down?* Records still save; Remarks say unavailable; retry later.
- *How do you prevent SQL injection?* Parameterised queries.
- *How do you test without the API?* Dependency injection and mocked clients.
- *What are the limits?* No units/sex in data, not a medical tool, no authentication.
