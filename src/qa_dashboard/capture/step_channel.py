from __future__ import annotations

import os
from pathlib import Path


class StepChannel:
    """Cross-process side-channel: writes current (test_id, step_id) atomically.

    Read by the mitmproxy addon subprocess on every captured flow.
    """

    def __init__(self, run_dir: Path) -> None:
        self._path = Path(run_dir) / "current.txt"

    @property
    def path(self) -> Path:
        return self._path

    def set(self, test_id: str | None, step_id: int = 0) -> None:
        if test_id is None:
            content = ""
        else:
            content = f"{test_id}\t{step_id}"
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, self._path)

    def clear(self) -> None:
        self.set(None)

    def read(self) -> tuple[str | None, int | None]:
        try:
            line = self._path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None, None
        if not line:
            return None, None
        try:
            test_id, step_id_s = line.split("\t", 1)
        except ValueError:
            return None, None
        try:
            step_id = int(step_id_s)
        except ValueError:
            return None, None
        return test_id, (step_id if step_id > 0 else None)
