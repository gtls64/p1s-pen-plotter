from __future__ import annotations

import base64
import socket
from pathlib import Path

from app import desktop, paths


def test_user_data_dir_per_platform() -> None:
    win = paths.user_data_dir("win32", {"APPDATA": r"C:\Users\a\AppData\Roaming"})
    assert win == Path(r"C:\Users\a\AppData\Roaming") / "P1S Plotter"
    mac = paths.user_data_dir("darwin", {"HOME": "/Users/a"})
    assert mac == Path("/Users/a/Library/Application Support/P1S Plotter")
    linux = paths.user_data_dir("linux", {"HOME": "/home/a"})
    assert linux == Path("/home/a/.config/P1S Plotter")


def test_data_dir_override(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "data"
    monkeypatch.setenv("P1S_PLOTTER_DATA", str(target))
    assert paths.data_dir() == target and target.is_dir()


def test_data_dir_is_project_in_development(monkeypatch) -> None:
    monkeypatch.delenv("P1S_PLOTTER_DATA", raising=False)
    assert paths.data_dir() == paths.PROJECT_ROOT


def test_free_port_skips_busy_port() -> None:
    with socket.socket() as busy:
        busy.bind((desktop.HOST, 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert desktop.free_port(port) != port


def test_wait_until_listening() -> None:
    with socket.socket() as s:
        s.bind((desktop.HOST, 0))
        s.listen()
        assert desktop.wait_until_listening(s.getsockname()[1], timeout_s=2)
    assert not desktop.wait_until_listening(desktop.free_port(), timeout_s=0.3)


def test_write_base64(tmp_path: Path) -> None:
    out = tmp_path / "job.gcode.3mf"
    desktop.write_base64(out, base64.b64encode(b"PK\x03\x04data").decode())
    assert out.read_bytes() == b"PK\x03\x04data"
