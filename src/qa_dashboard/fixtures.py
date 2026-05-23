from __future__ import annotations

import time
import traceback
from collections import defaultdict
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ._paths import iso_from_epoch, ms_between_iso, now_iso
from .capture.step_channel import StepChannel


class StepTracker:
    """Tracks per-test steps, substeps, and screenshots.

    Yielded by the `step` fixture. The plugin reads its accumulated
    data at teardown via ``finalize()``.
    """

    def __init__(
        self,
        test_id: str,
        run_dir: Path,
        channel: StepChannel,
        max_width: int | None = None,
    ) -> None:
        self._test_id = test_id
        self._run_dir = Path(run_dir)
        self._channel = channel
        self._max_width = max_width
        self._steps: list[dict] = []
        self._screenshots: list[dict] = []
        self._current: dict | None = None
        self._screenshot_seq: dict[int, int] = defaultdict(int)
        # Optional callback the host project can set so the plugin can
        # take a screenshot automatically on failure
        self._screenshot_callback: Callable[[], bytes] | None = None

    # -- Public API --------------------------------------------------

    def __call__(self, name: str):
        """Allow ``with step("name"):`` — the canonical form per the spec."""
        return self.step(name)

    @contextmanager
    def step(self, name: str):
        step_id = len(self._steps) + 1
        started_at = now_iso()
        record: dict[str, Any] = {
            "id": step_id,
            "name": str(name),
            "status": "pass",
            "started_at": started_at,
            "ended_at": None,
            "duration_ms": 0,
            "substeps": [],
            "screenshot_ids": [],
            "flow_ids": [],
            "error": None,
            "skip_reason": None,
        }
        self._steps.append(record)
        prev = self._current
        self._current = record
        self._channel.set(self._test_id, step_id)
        try:
            yield self
        except BaseException as exc:
            record["status"] = "fail"
            record["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ),
            }
            raise
        finally:
            record["ended_at"] = now_iso()
            record["duration_ms"] = ms_between_iso(
                record["started_at"], record["ended_at"]
            )
            self._current = prev
            # Back to test-active-no-step
            self._channel.set(self._test_id, 0)

    def screenshot(self, png_bytes: bytes, label: str = "") -> str:
        """Save a screenshot for the current step (or step 0 if none)."""
        step_id = self._current["id"] if self._current else 0
        self._screenshot_seq[step_id] += 1
        seq = self._screenshot_seq[step_id]
        shot_id = f"{self._test_id}_step_{step_id}_{seq:03d}"
        filename = f"{shot_id}.png"
        path = self._run_dir / "assets" / "screenshots" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._max_width:
            png_bytes = _maybe_downscale(png_bytes, self._max_width)
        path.write_bytes(png_bytes)
        if label:
            (path.parent / f"{shot_id}.label").write_text(label, encoding="utf-8")
        width, height = _png_dimensions(png_bytes)
        record = {
            "id": shot_id,
            "step_id": step_id if step_id > 0 else None,
            "captured_at": now_iso(),
            "filename": filename,
            "asset_path": f"assets/screenshots/{filename}",
            "width": width,
            "height": height,
            "size_bytes": len(png_bytes),
            "label": label or "",
        }
        if self._current is not None:
            self._current["screenshot_ids"].append(shot_id)
        self._screenshots.append(record)
        return shot_id

    def substep(self, name: str, fn: Callable[[], Any] | None = None) -> Any:
        """Run ``fn()`` as a substep and record duration + pass/fail.

        Returns ``fn()``'s return value. If ``fn`` is None, records a
        zero-duration passing substep (useful when the caller wants to
        record a noted step without executing anything).
        """
        if self._current is None:
            raise RuntimeError("substep() called outside a `with step():` block")
        started = time.perf_counter()
        status = "pass"
        result: Any = None
        try:
            if fn is not None:
                result = fn()
        except BaseException:
            status = "fail"
            raise
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            self._current["substeps"].append({
                "name": str(name),
                "status": status,
                "duration_ms": duration_ms,
            })
        return result

    def skip(self, name: str, reason: str) -> None:
        """Append a skipped step (no execution)."""
        step_id = len(self._steps) + 1
        record = {
            "id": step_id,
            "name": str(name),
            "status": "skip",
            "started_at": now_iso(),
            "ended_at": now_iso(),
            "duration_ms": 0,
            "substeps": [],
            "screenshot_ids": [],
            "flow_ids": [],
            "error": None,
            "skip_reason": str(reason),
        }
        self._steps.append(record)

    def set_screenshot_callback(self, cb: Callable[[], bytes] | None) -> None:
        """Register a no-arg callable that returns PNG bytes.

        Used by ``--qa-dashboard-screenshot-on-fail`` so the plugin can
        snap one automatically when a test fails.
        """
        self._screenshot_callback = cb

    # -- Plugin-internal API ----------------------------------------

    @property
    def screenshot_callback(self) -> Callable[[], bytes] | None:
        return self._screenshot_callback

    @property
    def current_step(self) -> dict | None:
        return self._current

    def finalize(self) -> dict:
        return {"steps": self._steps, "screenshots": self._screenshots}


def _maybe_downscale(png_bytes: bytes, max_width: int) -> bytes:
    """Downscale a PNG if it's wider than ``max_width``.

    Requires Pillow. If Pillow isn't installed, raises ImportError with a
    clear message. The plugin checks for Pillow at session start when the
    option is set, so this is a defensive backstop.
    """
    if not max_width or max_width <= 0:
        return png_bytes
    w, h = _png_dimensions(png_bytes)
    if w is None or w <= max_width:
        return png_bytes
    try:
        from PIL import Image  # type: ignore
        import io
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "Pillow is required for --qa-dashboard-screenshot-max-width. "
            "Install with: pip install qa-dashboard[imaging]"
        ) from e
    try:
        img = Image.open(io.BytesIO(png_bytes))
        ratio = max_width / w
        new_h = max(1, int(h * ratio))
        img = img.resize((max_width, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        # If anything goes wrong, keep the original
        return png_bytes


def _png_dimensions(b: bytes) -> tuple[int | None, int | None]:
    if len(b) < 24 or b[:8] != b"\x89PNG\r\n\x1a\n":
        return None, None
    try:
        width = int.from_bytes(b[16:20], "big")
        height = int.from_bytes(b[20:24], "big")
        return width, height
    except Exception:
        return None, None
