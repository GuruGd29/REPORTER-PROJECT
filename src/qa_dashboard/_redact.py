"""Redaction of sensitive headers and JSON body keys.

Used by the mitm addon (subprocess) and the Selenium / Playwright
adapters (in-process) so the redaction rule is identical everywhere.

This module is dependency-free (stdlib only) so it can be imported from
the mitmproxy subprocess without pulling in the rest of the package.
"""

from __future__ import annotations

import json
import os
from typing import Any

__all__ = [
    "DEFAULT_REDACTED_HEADERS",
    "REDACTED_PLACEHOLDER",
    "Redactor",
    "load_default_redactor",
]


# Lower-cased, matched as case-insensitive substrings.
DEFAULT_REDACTED_HEADERS: tuple[str, ...] = (
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "proxy-authorization",
)

REDACTED_PLACEHOLDER = "***"


def _parse_patterns(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(p.strip().lower() for p in raw.replace(";", ",").split(",") if p.strip())


class Redactor:
    """Case-insensitive substring redactor for header names and JSON keys.

    Patterns match against the lower-cased header name **and** any
    top-level (or nested) JSON object key. Matching values become
    ``REDACTED_PLACEHOLDER``.
    """

    def __init__(self, patterns: tuple[str, ...] | list[str] | None = None) -> None:
        self._patterns: tuple[str, ...] = tuple(
            (p.lower() if isinstance(p, str) else "") for p in (patterns or ()) if p
        )

    @property
    def patterns(self) -> tuple[str, ...]:
        return self._patterns

    def matches(self, name: str | None) -> bool:
        if not self._patterns or not name:
            return False
        lname = str(name).lower()
        return any(p in lname for p in self._patterns)

    def redact_headers(self, headers: dict[str, str] | None) -> dict[str, str]:
        if not headers:
            return {}
        if not self._patterns:
            return dict(headers)
        return {k: (REDACTED_PLACEHOLDER if self.matches(k) else v) for k, v in headers.items()}

    def redact_body(self, body: Any) -> Any:
        """Walk a parsed JSON body and redact matching keys.

        Non-dict / non-list bodies pass through untouched. Lists are
        descended into but never themselves redacted by-key.
        """
        if not self._patterns:
            return body
        return self._walk(body)

    def _walk(self, node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: (REDACTED_PLACEHOLDER if self.matches(k) else self._walk(v))
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [self._walk(x) for x in node]
        return node


def load_default_redactor() -> Redactor:
    """Build the runtime redactor from `QA_DASHBOARD_REDACT` + defaults.

    The env var, if set, **adds to** the defaults rather than
    replacing them. Pass an empty value to disable defaults entirely.
    Recognized override-form: ``QA_DASHBOARD_REDACT=""`` (empty
    string) means "no patterns at all"; ``QA_DASHBOARD_REDACT="-"``
    means "use defaults only".
    """
    raw = os.environ.get("QA_DASHBOARD_REDACT")
    if raw is None:
        return Redactor(DEFAULT_REDACTED_HEADERS)
    if raw == "":
        return Redactor(())
    extra = _parse_patterns(raw)
    if extra == ("-",):
        return Redactor(DEFAULT_REDACTED_HEADERS)
    return Redactor(tuple(DEFAULT_REDACTED_HEADERS) + extra)


def redact_json_text(text: str | None, redactor: Redactor) -> str | None:
    """Parse, redact, re-serialize a JSON-looking text body.

    Returns ``None`` if input is None; passes the original text through
    unchanged if parsing fails (e.g. partial body, non-JSON content).
    """
    if text is None:
        return None
    if not redactor.patterns:
        return text
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return text
    return json.dumps(redactor.redact_body(parsed), ensure_ascii=False)
