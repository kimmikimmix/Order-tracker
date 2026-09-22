#!/usr/bin/env python3
"""Generate assets/ordertracker.ico (and a preview PNG).

Written with the standard library alone — an .ico is a small container and a
PNG is a handful of CRC-checked chunks, so no image package is needed.

Run from the project root:  python3 tools/make_icon.py
"""

import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BACKGROUND = (0x10, 0x12, 0x16, 255)
BORDER = (0x2c, 0x2f, 0x38, 255)
AMBER = (0xff, 0xa0, 0x28, 255)
DIM = (0x8a, 0x57, 0x14, 255)
CLEAR = (0, 0, 0, 0)

# Rows of the "blotter": (top as a fraction of height, width as a fraction, colour)
ROWS = [
    (0.30, 0.62, AMBER),
    (0.47, 0.42, DIM),
    (0.64, 0.74, AMBER),
]


def draw(size: int) -> bytearray:
    """One RGBA image: a dark tile with an amber order list on it."""
    px = bytearray(size * size * 4)
    radius = max(2, round(size * 0.18))
    edge = max(1, round(size * 0.035))
    bar_height = max(1, round(size * 0.085))

    def put(x, y, colour):
        offset = (y * size + x) * 4
        px[offset:offset + 4] = bytes(colour)

    for y in range(size):
        for x in range(size):
            # Rounded-corner mask: only the corner squares get a radius test.
            cx = radius - x if x < radius else (x - (size - 1 - radius) if x > size - 1 - radius else 0)
            cy = radius - y if y < radius else (y - (size - 1 - radius) if y > size - 1 - radius else 0)
            if cx and cy and (cx * cx + cy * cy) > radius * radius:
                put(x, y, CLEAR)
                continue
            on_edge = (x < edge or y < edge or x >= size - edge or y >= size - edge)
            put(x, y, BORDER if on_edge else BACKGROUND)

    inset = max(2, round(size * 0.16))
    usable = size - inset * 2
    for top_fraction, width_fraction, colour in ROWS:
        top = round(size * top_fraction)
        width = max(2, round(usable * width_fraction))
        for y in range(top, min(top + bar_height, size - inset)):
            for x in range(inset, min(inset + width, size - inset)):
                put(x, y, colour)
    return px


def png(size: int, rgba: bytearray) -> bytes:
    """Encode RGBA pixels as a PNG."""
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)                      # filter: none
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def ico(images: list[tuple[int, bytes]]) -> bytes:
    """Wrap PNGs of several sizes in an .ico container."""
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + count * 16

    entries, payload = bytearray(), bytearray()
    for size, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,     # 0 means 256
            0 if size >= 256 else size,
            0, 0, 1, 32, len(data), offset,
        )
        payload += data
        offset += len(data)

    return bytes(header + entries + payload)


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [(size, png(size, draw(size))) for size in sizes]

    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)

    ico_path = assets / "ordertracker.ico"
    ico_path.write_bytes(ico(images))

    png_path = assets / "ordertracker.png"
    png_path.write_bytes(dict(images)[256])

    print(f"  {ico_path}  ({ico_path.stat().st_size:,} bytes, sizes {sizes})")
    print(f"  {png_path}  ({png_path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
