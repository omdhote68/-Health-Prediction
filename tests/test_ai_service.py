"""AI service tests. The real Gemini API is never called here."""

from types import SimpleNamespace

import pytest

from src import ai_service
from src.ai_service import analyze_patient, build_prompt, check_connection, friendly_error

PATIENT = {"age_years": 40, "glucose": "95", "haemoglobin": "14.2", "cholesterol": "180",
           "full_name": "Secret Name", "email": "secret@example.com"}


class FakeClient:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.models = SimpleNamespace(generate_content=self._generate)
        self._response, self._error = response, error

    def _generate(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._response


class ApiError(Exception):
    def __init__(self, code, message="boom"):
        super().__init__(message)
        self.code = code


def test_prompt_contains_values_and_safety_rules():
    prompt = build_prompt(PATIENT)
    for needle in ("95", "14.2", "180", "40 years", "units not provided",
                   "qualified healthcare professional", "Do NOT claim", "reference ranges"):
        assert needle in prompt
    assert "ask the user to provide or confirm" in prompt


def test_prompt_excludes_name_and_email():
    prompt = build_prompt(PATIENT)
    assert "Secret Name" not in prompt and "secret@example.com" not in prompt


def test_success_returns_response_text():
    client = FakeClient(response=SimpleNamespace(text="  Looks fine. See a doctor.  "))
    result = analyze_patient(PATIENT, client=client, model="m1")
    assert result.ok and result.text == "Looks fine. See a doctor." and result.model == "m1"
    assert client.calls[0]["model"] == "m1"
    assert "95" in client.calls[0]["contents"]


@pytest.mark.parametrize("text", [None, "", "   "])
def test_empty_response_is_an_error_not_fabricated(text):
    result = analyze_patient(PATIENT, client=FakeClient(response=SimpleNamespace(text=text)))
    assert not result.ok and result.text == "" and "empty" in result.error


def test_missing_api_key_is_reported():
    result = analyze_patient(PATIENT)  # conftest removes GEMINI_API_KEY
    assert not result.ok and "GEMINI_API_KEY is not set" in result.error


def test_placeholder_key_counts_as_missing(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "your_api_key_here")
    assert not ai_service.api_key_configured()


@pytest.mark.parametrize(
    "exc, expected",
    [
        (ApiError(401), "key was rejected"),
        (ApiError(403), "key was rejected"),
        (ApiError(400, "API key not valid. Please pass a valid API key."), "key was rejected"),
        (ApiError(429), "rate limit"),
        (ApiError(503), "temporarily unavailable"),
        (ApiError(500), "temporarily unavailable"),
        (TimeoutError("x"), "timeout"),
        (ConnectionError("x"), "network error"),
        (ValueError("weird"), "unexpected error (ValueError)"),
    ],
)
def test_errors_map_to_friendly_messages(exc, expected):
    result = analyze_patient(PATIENT, client=FakeClient(error=exc))
    assert not result.ok and expected in result.error


def test_error_message_does_not_leak_raw_exception_text():
    secret = "AIzaSySecretKeyValue"
    assert secret not in friendly_error(ValueError(f"bad request with key {secret}"))


def test_missing_sdk_reported(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "real-looking-key")

    def boom(_key):
        raise ImportError("no sdk")

    monkeypatch.setattr(ai_service, "_create_client", boom)
    result = analyze_patient(PATIENT)
    assert not result.ok and "google-genai" in result.error


def test_model_name_from_environment(monkeypatch):
    assert ai_service.get_model_name() == ai_service.DEFAULT_MODEL
    monkeypatch.setenv("GEMINI_MODEL", "custom-model")
    assert ai_service.get_model_name() == "custom-model"


def test_check_connection_with_fake_client():
    ok = check_connection(client=FakeClient(response=SimpleNamespace(text="ready")))
    assert ok.ok
    bad = check_connection(client=FakeClient(error=ApiError(429)))
    assert not bad.ok
    assert not check_connection().ok  # no key configured
