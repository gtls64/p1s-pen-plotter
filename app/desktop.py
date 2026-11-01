"""Desktop app: runs the web app on a private local port and shows it in a native window (pywebview).

The web app itself is unchanged, so the same code can still be served to a browser or from a Raspberry Pi.
"""
from __future__ import annotations

import base64
import os
import socket
import sys
import threading
import time
from pathlib import Path

HOST = "127.0.0.1"
PREFERRED_PORT = 8765
STARTUP_TIMEOUT_S = 20.0


def free_port(preferred: int = PREFERRED_PORT, host: str = HOST) -> int:
    """preferred if it is free, otherwise any free port chosen by the OS."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise RuntimeError("No free local port.")


def wait_until_listening(port: int, host: str = HOST, timeout_s: float = STARTUP_TIMEOUT_S) -> bool:
    """Poll until something accepts connections on host:port, or timeout_s seconds pass."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def write_base64(path: Path, data_b64: str) -> None:
    """Decode base64 data and write it to path."""
    path.write_bytes(base64.b64decode(data_b64))


class JsApi:
    """Functions the page can call as window.pywebview.api.<name>(...)."""

    def __init__(self) -> None:
        self._window = None  # leading underscore: pywebview does not expose it to JavaScript

    def save_file(self, filename: str, data_b64: str) -> str | None:
        """Ask where to save a download, write it, and return the chosen path (None if cancelled)."""
        import webview

        chosen = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename)
        if not chosen:
            return None
        path = Path(chosen if isinstance(chosen, str) else chosen[0])
        write_base64(path, data_b64)
        return str(path)


def main() -> None:
    """Start the server in a background thread, then open the window; quitting the window stops everything."""
    # A windowed PyInstaller build has no console, so stdout/stderr are None; uvicorn needs real streams.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    import uvicorn
    import webview

    from app.main import app

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_config=None))
    threading.Thread(target=server.run, daemon=True).start()
    if not wait_until_listening(port):
        raise RuntimeError("The plotter server did not start.")

    api = JsApi()
    api._window = webview.create_window(
        "P1S Pen Plotter", f"http://{HOST}:{port}/", js_api=api, width=1200, height=860, min_size=(380, 600)
    )
    webview.start()
    server.should_exit = True


if __name__ == "__main__":
    main()
