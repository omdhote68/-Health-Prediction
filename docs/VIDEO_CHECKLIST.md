# Video Demonstration Checklist

## Before recording
- [ ] Use a separate, git-ignored demo database (for example `data/assessment-demo.db`); do not delete or overwrite an existing database.
- [ ] Keep `GEMINI_API_KEY` unset while entering the supplied assessment records. The records may contain real health information; the application sends valid blood values to Gemini when a key is configured.
- [ ] `streamlit run app.py` running; browser zoom ~110%; close unrelated tabs.
- [ ] The connection test sends only a non-medical prompt. Run it only when you have configured a key and want to make a live request; otherwise explain the integration from code and mocked tests.
- [ ] Have VS Code open with `src/ai_service.py`, `src/database.py`, `src/validation.py`, `src/patient_service.py`.

## Part 1 - Create (all 10 records)
- [ ] Open **Add Patient** → expander *Assessment test data*.
- [ ] For tests 1-10 in order: pick the test → *Fill form with this record* → *Save patient*. Do not edit any value. The assessment values are saved without normalizing date separators.
- [ ] After each save, read out the result panel. Expected:

| Test | Expected result |
|---|---|
| 1 Robyn Pears | Valid; AI unavailable because the key is intentionally unset |
| 2 John Hunter | **Invalid** - email `hunter@gmail` has no top-level domain |
| 3 Darryl Tim | Valid; AI unavailable because the key is intentionally unset |
| 4 Peter Larry | **Invalid** - 31.11.2001 is not a real date (November has 30 days) |
| 5 Sam Kerr | Valid; AI unavailable because the key is intentionally unset |
| 6 Robyn Pears | Valid but **⚠️ Duplicate of #1** (kept, flagged) |
| 7 Madison XI | Valid; AI unavailable because the key is intentionally unset |
| 8 Kris Wu | **Invalid** - DOB 19.10.2030 is in the future **and** email has no `@` |
| 9 Tenille Singh | Valid; AI unavailable because the key is intentionally unset |
| 10 Prem Kumar | Valid; AI unavailable because the key is intentionally unset |

- [ ] Show the **Dashboard**: 10 total, 7 valid, 3 invalid, 1 duplicate, 7 AI unavailable (with no key), 3 deliberately skipped. This avoids sending supplied blood values to an external service.

## Part 2 - Read
- [ ] **Patient Records**: show all 10 including invalid and duplicate ones, the Validation Status, Duplicate and Remarks Source columns.
- [ ] Try the search box (e.g. `robyn`) and the *Invalid only* filter, then clear them.
- [ ] Pick a record under *Full remarks* to show the unavailable status and an invalid record's error list.

## Part 3 - Update
- [ ] **Update Patient** → choose **#10 Prem Kumar** (avoid #1: editing it would clear #6's duplicate flag - correct behaviour, but a distraction).
- [ ] Change email to `gokul@infocare.com` → *Save changes*.
- [ ] Show the "Record as now stored" row, then **Patient Records** to show the change (still 10 records; no new row).
- [ ] Mention: this no-key demo stores an honest unavailable status; changing only the email does not make another API call.

## Part 4 - Delete
- [ ] **Delete Patient** → select **#6 (duplicate Robyn Pears)** or any record → *Delete this record*.
- [ ] Show the confirmation warning → *Yes, delete it*.
- [ ] Show the remaining 9 records listed below and on **Patient Records**.

## Part 5 - Gemini integration (safe live demonstration)
- [ ] Do not retry analysis on the assessment records. That would send their valid blood values to Gemini.
- [ ] If demonstrating a live API request, use **API / AI Analysis → Send a tiny test request to Gemini**; it sends a non-medical prompt only. Do not show the key.
- [ ] To demonstrate Remarks saved from a live call, use a separate empty database and one clearly synthetic patient record, never the supplied assessment records. Stop the assessment demo first and do not reuse its database.
- [ ] If no key is available, show the key/model configuration, the real SDK call, error handling, and mocked integration tests instead. Do not claim a live request succeeded.

## Part 6 - Code walkthrough (see `CODE_WALKTHROUGH.md`)
- [ ] `ai_service.py`: prompt, key from environment, `generate_content` call, error mapping, "never fabricate".
- [ ] `database.py`: schema, parameterised queries, persistence (restart the app and show records remain).
- [ ] `validation.py`: date, email, number rules; why invalid data is preserved.
- [ ] `patient_service.py`: invalid → not sent to AI; duplicate refresh; update only re-calls AI when needed.
- [ ] Run `python -m pytest -v` and show all tests passing.
- [ ] Mention the limitations: no units in the data, educational prototype, not medical advice.

## If the API fails during an optional live demonstration
Remarks will read "AI analysis unavailable: …". That is the designed behaviour. Do not retry records in the assessment demo; use only the isolated synthetic-data demo if you need to retry.
