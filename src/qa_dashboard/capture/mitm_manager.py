from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("qa_dashboard.mitm")


class MitmManager:
    """Spawn mitmdump for the run and stop it cleanly at the end.

    Failure is non-fatal: if mitmdump cannot start, ``is_running`` is
    ``False`` and the rest of the run proceeds with an empty network tab.
    """

    def __init__(
        self,
        run_dir: Path,
        port: int = 8080,
        host_filter: str = "",
        addon_path: Path | None = None,
    ) -> None:
        self._run_dir = Path(run_dir)
        self._port = int(port)
        self._host_filter = host_filter or ""
        self._addon_path = addon_path or (
            Path(__file__).parent / "mitm_addon.py"
        )
        self._proc: subprocess.Popen | None = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def port(self) -> int:
        return self._port

    def start(self, timeout: float = 5.0) -> None:
        """Spawn mitmdump and wait until its port is accepting connections."""
        env = os.environ.copy()
        env["QA_DASHBOARD_RUN_DIR"] = str(self._run_dir)
        env["QA_DASHBOARD_HOST_FILTER"] = self._host_filter
        cmd = [
            "mitmdump",
            "-p", str(self._port),
            "-s", str(self._addon_path),
            "-q",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            log.warning("mitmdump not found on PATH; network capture disabled")
            self._is_running = False
            return
        except Exception as e:  # pragma: no cover
            log.warning("failed to spawn mitmdump: %s; network capture disabled", e)
            self._is_running = False
            return

        # Wait until the port accepts connections
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                break
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                try:
                    s.connect(("127.0.0.1", self._port))
                    self._is_running = True
                    log.info("mitmdump listening on :%d", self._port)
                    return
                except OSError:
                    time.sleep(0.1)
        # Did not come up
        log.warning(
            "mitmdump did not start within %.1fs on port %d; network capture disabled",
            timeout, self._port,
        )
        self._is_running = False
        # Best-effort kill the process so it doesn't leak
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def stop(self, timeout: float = 3.0) -> None:
        if not self._proc:
            return
        if self._proc.poll() is not None:
            return
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                try:
                    self._proc.wait(timeout=2.0)
                except Exception:
                    pass
        except Exception as e:  # pragma: no cover
            log.warning("error stopping mitmdump: %s", e)
        finally:
            self._is_running = False
