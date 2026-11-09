"""External AI integration (Google Gemini API).

This module is the ONLY place that talks to the internet. It:
  1. builds a cautious, structured prompt from validated values,
  2. sends it to Gemini,
  3. returns an AIResult - never raises, and never invents a result on failure.

The API key is read from the GEMINI_API_KEY environment variable and is never
logged, shown in the UI, or stored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from streamlit.errors import StreamlitSecretNotFoundError

DEFAULT_MODEL = "gemini-3.6-flash"
REQUEST_TIMEOUT_MS = 30_000  # the SDK's http timeout is in milliseconds
MAX_REMARK_CHARS = 2000

SYSTEM_INSTRUCTION = (
    "You are a careful health-information assistant inside an educational "
    "assessment prototype. You are NOT a doctor and must never diagnose. "
    "Follow every rule in the user's message exactly."
)


@dataclass(frozen=True)
class AIResult:
    """Result of one AI call. ok=True means `text` came from the real API."""

    ok: bool
    text: str = ""
    error: str = ""
    model: str = ""


def get_model_name() -> str:
    return os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL


def _get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key and key != "your_api_key_here":
        return key

    import streamlit as st

    try:
        key = str(st.secrets.get("GEMINI_API_KEY", "")).strip()
    except StreamlitSecretNotFoundError:
        return ""
    return "" if key == "your_api_key_here" else key


def api_key_configured() -> bool:
    return bool(_get_api_key())


def build_prompt(patient: dict) -> str:
    """Build the prompt from blood values and age only.

    Name and email are deliberately NOT sent: the AI does not need them, so
    they never leave the application (data minimisation).
    """
    age = patient.get("age_years")
    age_text = f"{age} years" if age is not None else "not provided"
    return f"""Provide a short, educational interpretation of the blood test values below.

Patient context (de-identified):
- Age: {age_text}
- Sex, medical history, medications, fasting status: not provided
- Glucose: {patient.get('glucose')} (units not provided)
- Haemoglobin: {patient.get('haemoglobin')} (units not provided)
- Cholesterol: {patient.get('cholesterol')} (type of cholesterol and units not provided)

Rules:
1. Write 90-130 words of plain prose, no headings, no bullet points.
2. Start by stating that units were not supplied, so this is a general, non-diagnostic observation.
3. Say which values may deserve attention or follow-up, or which look unremarkable, and why. If you say a value looks high or low, state the units you are assuming and say it is an assumption. Do not quote specific numeric reference ranges.
4. State that interpretation depends on the laboratory's reference ranges, units, age, sex, medical history and clinical context. If units or laboratory reference ranges were not provided, explicitly ask the user to provide or confirm them before any meaningful interpretation.
5. Do NOT claim the person has or does not have any disease. Do NOT suggest medication, supplements or treatment.
6. End by recommending review of these results with a qualified healthcare professional.
"""


def _create_client(api_key: str):
    # Imported lazily so the rest of the app (and the tests) work even if the
    # SDK is not installed.
    from google import genai

    return genai.Client(api_key=api_key, http_options={"timeout": REQUEST_TIMEOUT_MS})


def friendly_error(exc: Exception) -> str:
    """Translate any SDK/network exception into a short, safe message.

    The raw exception text is not shown because it may contain request details.
    """
    code = getattr(exc, "code", None)
    name = type(exc).__name__.lower()
    text = str(exc).lower()

    if isinstance(exc, TimeoutError) or "timeout" in name or "timed out" in text:
        return "The AI service took too long to respond (timeout). Please try again."
    if code in (401, 403) or "api key not valid" in text or "api_key_invalid" in text:
        return "The Gemini API key was rejected. Check GEMINI_API_KEY in your .env file."
    if code == 429 or "resource_exhausted" in text or "quota" in text:
        return "The Gemini API rate limit or quota was reached. Wait a moment and retry."
    if code in (500, 502, 503, 504) or "unavailable" in text:
        return "The Gemini service is temporarily unavailable. Please retry later."
    if isinstance(exc, ConnectionError) or "connect" in name or "network" in text or "connection" in text:
        return "A network error prevented contact with the Gemini API. Check your internet connection."
    return f"The AI service returned an unexpected error ({type(exc).__name__})."


def _generate(client, prompt: str, model: str) -> AIResult:
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={"system_instruction": SYSTEM_INSTRUCTION, "temperature": 0.2},
        )
    except Exception as exc:  # noqa: BLE001 - every failure becomes a friendly message
        return AIResult(ok=False, error=friendly_error(exc), model=model)

    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        return AIResult(
            ok=False,
            error="The AI service returned an empty or blocked response.",
            model=model,
        )
    return AIResult(ok=True, text=text.strip()[:MAX_REMARK_CHARS], model=model)


def analyze_patient(patient: dict, client=None, model: str | None = None) -> AIResult:
    """Ask Gemini for a cautious interpretation of one valid patient's values.

    `client` can be injected (tests pass a fake). Otherwise a real client is
    built from GEMINI_API_KEY.
    """
    model = model or get_model_name()
    if client is None:
        api_key = _get_api_key()
        if not api_key:
            return AIResult(
                ok=False,
                error="GEMINI_API_KEY is not set. Add it to your .env file (see .env.example).",
                model=model,
            )
        try:
            client = _create_client(api_key)
        except ImportError:
            return AIResult(
                ok=False,
                error="The google-genai package is not installed. Run: pip install -r requirements.txt",
                model=model,
            )
        except Exception as exc:  # noqa: BLE001
            return AIResult(ok=False, error=friendly_error(exc), model=model)
    return _generate(client, build_prompt(patient), model)


def check_connection(client=None, model: str | None = None) -> AIResult:
    """Send a tiny non-medical request to confirm the key and model work."""
    model = model or get_model_name()
    if client is None:
        api_key = _get_api_key()
        if not api_key:
            return AIResult(ok=False, error="GEMINI_API_KEY is not set.", model=model)
        try:
            client = _create_client(api_key)
        except ImportError:
            return AIResult(ok=False, error="The google-genai package is not installed.", model=model)
        except Exception as exc:  # noqa: BLE001
            return AIResult(ok=False, error=friendly_error(exc), model=model)
    return _generate(client, "Reply with the single word: ready", model)
