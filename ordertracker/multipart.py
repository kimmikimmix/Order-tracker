"""A small multipart/form-data parser.

The standard library's `cgi` module used to do this, but it is deprecated and
was removed in Python 3.13 — parsing it here keeps the app working on future
Python versions without adding a dependency.
"""

import re


class Part:
    __slots__ = ("name", "filename", "content_type", "data")

    def __init__(self, name, filename, content_type, data):
        self.name = name
        self.filename = filename
        self.content_type = content_type
        self.data = data

    @property
    def text(self) -> str:
        return self.data.decode("utf-8", "replace")

    def __repr__(self):
        return f"<Part {self.name!r} file={self.filename!r} {len(self.data)}B>"


def boundary_from(content_type: str) -> bytes | None:
    m = re.search(r'boundary="?([^";]+)"?', content_type or "", re.I)
    return m.group(1).encode("latin-1") if m else None


def _header_value(headers: str, name: str) -> str:
    for line in headers.split("\r\n"):
        key, _, value = line.partition(":")
        if key.strip().lower() == name:
            return value.strip()
    return ""


def _disposition_param(disposition: str, key: str) -> str | None:
    m = re.search(rf'{key}="((?:[^"\\]|\\.)*)"', disposition, re.I)
    if m:
        return m.group(1).replace('\\"', '"')
    m = re.search(rf"{key}=([^;]+)", disposition, re.I)
    return m.group(1).strip() if m else None


def parse(body: bytes, content_type: str) -> dict[str, list[Part]]:
    """Return {field name: [Part, ...]} for a multipart/form-data body."""
    boundary = boundary_from(content_type)
    if not boundary:
        return {}

    delimiter = b"--" + boundary
    fields: dict[str, list[Part]] = {}

    for chunk in body.split(delimiter):
        if chunk in (b"", b"--", b"--\r\n") or chunk.startswith(b"--"):
            continue
        chunk = chunk.lstrip(b"\r\n")
        head, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        data = data[:-2] if data.endswith(b"\r\n") else data

        headers = head.decode("utf-8", "replace")
        disposition = _header_value(headers, "content-disposition")
        name = _disposition_param(disposition, "name")
        if not name:
            continue
        filename = _disposition_param(disposition, "filename")
        part = Part(name, filename, _header_value(headers, "content-type"), data)
        fields.setdefault(name, []).append(part)

    return fields


def first(fields: dict, name: str) -> Part | None:
    parts = fields.get(name)
    return parts[0] if parts else None


def value(fields: dict, name: str, default: str = "") -> str:
    part = first(fields, name)
    return part.text if part is not None else default
