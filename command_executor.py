"""Generic helper for running external commands without freezing the UI.

Every subprocess is launched on a background thread. Output is streamed back
line by line through simple callbacks so callers never need to poll or block
the Tkinter main loop.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Callable, List, Optional


class CommandExecutor:
    """Runs a single subprocess command on a background thread.

    Callbacks are invoked from the background thread. Callers that need to
    touch Tkinter widgets must marshal the call back onto the main thread
    (for example via a thread-safe queue that the UI polls with `after`).
    """

    def __init__(
        self,
        command: List[str],
        on_line: Optional[Callable[[str], None]] = None,
        on_finished: Optional[Callable[[int], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        self._command = command
        self._on_line = on_line
        self._on_finished = on_finished
        self._on_error = on_error
        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._cancel_requested = False

    def start(self) -> None:
        """Start the command on a background thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Terminate the running process, if any."""
        self._cancel_requested = True
        if self._process is not None and self._process.poll() is None:
            try:
                self._process.terminate()
            except OSError:
                pass

    def _run(self) -> None:
        try:
            self._process = subprocess.Popen(
                self._command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
        except (OSError, FileNotFoundError) as exc:
            if self._on_error is not None:
                self._on_error(exc)
            return

        assert self._process.stdout is not None
        try:
            for raw_line in self._process.stdout:
                if self._cancel_requested:
                    break
                line = raw_line.rstrip("\n").rstrip("\r")
                if line and self._on_line is not None:
                    self._on_line(line)
        finally:
            self._process.stdout.close()

        return_code = self._process.wait()
        if self._on_finished is not None:
            self._on_finished(return_code)


def run_command_capture_output(command: List[str]) -> str:
    """Run a command synchronously and return its combined stdout output.

    Intended for short-lived commands (e.g. `--dump-single-json`) that are
    already being called from a background thread, never from the UI thread.
    """
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    return result.stdout
