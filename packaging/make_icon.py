"""Draw the app icon (a plotted wave and a pen dot) and write packaging/icon.png and packaging/icon.ico.

Uses only numpy and the standard library. Run: python packaging/make_icon.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

OUT_DIR = Path(__file__).resolve().parent
SUPER = 4  # supersampling factor for smooth edges
SIZE = 256
ICO_SIZES = (256, 64, 48, 32, 16)
BLUE = np.array([31, 111, 235], dtype=float)
WHITE = np.array([255, 255, 255], dtype=float)


def _png_rgba(img: np.ndarray) -> bytes:
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[row].tobytes() for row in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _coverage(mask: np.ndarray, size: int) -> np.ndarray:
    """Average a supersampled boolean mask down to size x size coverage in 0..1."""
    f = mask.shape[0] // size
    return mask.reshape(size, f, size, f).mean(axis=(1, 3))


def render(size: int = SIZE) -> np.ndarray:
    """RGBA uint8 icon of the given size."""
    n = size * SUPER
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n  # 0..1, y down
    # Rounded square.
    r, m = 0.2, 0.04
    dx = np.maximum(np.abs(x - 0.5) - (0.5 - m - r), 0)
    dy = np.maximum(np.abs(y - 0.5) - (0.5 - m - r), 0)
    tile = np.hypot(dx, dy) <= r
    # Plotted wave from left to right, ending at a pen dot.
    t = np.linspace(0, 1, 160)
    wx, wy = 0.18 + 0.56 * t, 0.58 - 0.16 * np.sin(t * 2.6 * np.pi) * (1 - 0.4 * t)
    dist = np.full(x.shape, np.inf)
    for px, py in zip(wx, wy):
        np.minimum(dist, np.hypot(x - px, y - py), out=dist)
    line = dist <= 0.035
    dot = np.hypot(x - wx[-1], y - wy[-1]) <= 0.075
    a_tile = _coverage(tile, size)
    a_ink = _coverage((line | dot) & tile, size)
    rgb = BLUE * (1 - a_ink[..., None]) + WHITE * a_ink[..., None]
    img = np.dstack([rgb, a_tile * 255]).round().astype(np.uint8)
    return img


def ico_bytes(pngs: list[tuple[int, bytes]]) -> bytes:
    """Windows .ico holding PNG-compressed images."""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for size, data in pngs:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return header + entries + blobs


def main() -> None:
    pngs = [(s, _png_rgba(render(s))) for s in ICO_SIZES]
    (OUT_DIR / "icon.png").write_bytes(pngs[0][1])
    (OUT_DIR / "icon.ico").write_bytes(ico_bytes(pngs))
    print("Wrote icon.png and icon.ico")


if __name__ == "__main__":
    main()
