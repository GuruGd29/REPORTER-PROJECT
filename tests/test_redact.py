"""Unit tests for qa_dashboard._redact."""

from __future__ import annotations

import pytest

from qa_dashboard._redact import (
    DEFAULT_REDACTED_HEADERS,
    REDACTED_PLACEHOLDER,
    Redactor,
    load_default_redactor,
    redact_json_text,
)


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("QA_DASHBOARD_REDACT", raising=False)
    return monkeypatch


def test_default_patterns_include_common_credentials():
    expected = {"authorization", "cookie", "set-cookie", "x-api-key"}
    assert expected.issubset(set(DEFAULT_REDACTED_HEADERS))


def test_no_patterns_means_no_redaction():
    r = Redactor()
    headers = {"Authorization": "Bearer abc", "X-Other": "ok"}
    assert r.redact_headers(headers) == headers
    assert r.redact_body({"password": "p"}) == {"password": "p"}


def test_redact_headers_case_insensitive():
    r = Redactor(("authorization",))
    headers = {"Authorization": "Bearer abc123", "X-Trace-Id": "t"}
    redacted = r.redact_headers(headers)
    assert redacted["Authorization"] == REDACTED_PLACEHOLDER
    assert redacted["X-Trace-Id"] == "t"


def test_redact_headers_substring_match():
    r = Redactor(("api-key",))
    headers = {"X-API-Key": "secret", "Other": "ok"}
    assert r.redact_headers(headers)["X-API-Key"] == REDACTED_PLACEHOLDER


def test_redact_body_walks_nested_dicts():
    r = Redactor(("password", "token"))
    body = {
        "username": "alice",
        "password": "p4ssw0rd",
        "auth": {"token": "abc", "expires": 1234},
        "history": [{"token": "x"}, {"ok": True}],
    }
    redacted = r.redact_body(body)
    assert redacted["username"] == "alice"
    assert redacted["password"] == REDACTED_PLACEHOLDER
    assert redacted["auth"]["token"] == REDACTED_PLACEHOLDER
    assert redacted["auth"]["expires"] == 1234
    assert redacted["history"][0]["token"] == REDACTED_PLACEHOLDER
    assert redacted["history"][1]["ok"] is True


def test_redact_body_leaves_non_dict_payloads_alone():
    r = Redactor(("password",))
    assert r.redact_body("password") == "password"
    assert r.redact_body(42) == 42
    assert r.redact_body(None) is None
    assert r.redact_body([1, 2, 3]) == [1, 2, 3]


def test_load_default_redactor_uses_defaults_when_env_unset(clean_env):
    r = load_default_redactor()
    assert "authorization" in r.patterns


def test_load_default_redactor_appends_env_patterns(monkeypatch):
    monkeypatch.setenv("QA_DASHBOARD_REDACT", "x-internal,password")
    r = load_default_redactor()
    assert "authorization" in r.patterns  # defaults still there
    assert "x-internal" in r.patterns
    assert "password" in r.patterns


def test_load_default_redactor_empty_string_disables(monkeypatch):
    monkeypatch.setenv("QA_DASHBOARD_REDACT", "")
    r = load_default_redactor()
    assert r.patterns == ()


def test_load_default_redactor_dash_keeps_defaults_only(monkeypatch):
    monkeypatch.setenv("QA_DASHBOARD_REDACT", "-")
    r = load_default_redactor()
    assert set(r.patterns) == set(DEFAULT_REDACTED_HEADERS)


def test_redact_json_text_roundtrip():
    r = Redactor(("password",))
    txt = '{"password": "p", "user": "alice"}'
    out = redact_json_text(txt, r)
    assert '"password": "***"' in out
    assert '"user": "alice"' in out


def test_redact_json_text_passes_through_invalid_json():
    r = Redactor(("password",))
    assert redact_json_text("not json", r) == "not json"


def test_redact_json_text_handles_none():
    assert redact_json_text(None, Redactor()) is None
