"""Best-effort auto-screenshot on test failure.

Inspects ``item.funcargs`` for fixtures that look like webdrivers or
browser pages and tries to capture a PNG. Used by the plugin to attach
a failure screenshot to tests that don't explicitly use the ``step``
fixture.

Detection rules (first match wins):

1. Any fixture with a callable ``get_screenshot_as_png()`` — Selenium
   and Appium drivers.
2. Any fixture with a callable ``screenshot()`` that returns bytes —
   Playwright pages and contexts.
3. The session-stored ``driver``/``page``/``browser`` fixture names.

Returns ``None`` silently if nothing usable is found — auto-screenshot
is purely a bonus, never a failure mode.
"""

from __future__ import annotations

from typing import Any

_PREFERRED_NAMES = ("page", "driver", "browser_page", "browser", "appium_driver")


def _try_method(obj: Any, name: str) -> bytes | None:
    method = getattr(obj, name, None)
    if not callable(method):
        return None
    try:
        result = method()
    except Exception:
        return None
    if isinstance(result, (bytes, bytearray)):
        return bytes(result)
    return None


def _try_extract(obj: Any) -> bytes | None:
    # Selenium / Appium API
    png = _try_method(obj, "get_screenshot_as_png")
    if png:
        return png
    # Playwright API
    png = _try_method(obj, "screenshot")
    if png:
        return png
    return None


def auto_screenshot_for(item) -> bytes | None:
    """Try to capture a screenshot from the test's available fixtures.

    Looks at ``item.funcargs`` (populated by pytest after fixtures
    resolve). Returns PNG bytes or ``None``.
    """
    funcargs = getattr(item, "funcargs", None) or {}
    if not funcargs:
        return None
    # Preferred-name pass: fast and most likely to be the right object
    for name in _PREFERRED_NAMES:
        if name in funcargs:
            png = _try_extract(funcargs[name])
            if png:
                return png
    # Fallback: scan everything else
    for name, val in funcargs.items():
        if name in _PREFERRED_NAMES:
            continue
        if isinstance(val, (str, bytes, int, float, bool, list, dict, tuple, type(None))):
            continue
        png = _try_extract(val)
        if png:
            return png
    return None
