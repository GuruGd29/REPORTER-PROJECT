from __future__ import annotations

import json
import logging
from pathlib import Path

from ._paths import iso_from_epoch


class JsonlLogHandler(logging.Handler):
    """Append structured log lines to a per-test JSONL file."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = Path(path)
        self._fp = self._path.open("a", encoding="utf-8")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            obj = {
                "ts": iso_from_epoch(record.created),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            self._fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self._fp.flush()
        except Exception:
            # logging handlers must never raise
            self.handleError(record)

    def close(self) -> None:
        try:
            self._fp.close()
        except Exception:
            pass
        super().close()
