"""Dispatch a stored file to whichever extractor understands it.

Every extractor returns (text, note). An empty text is not an error: the file
is still stored and still findable by filename, company and order — the note
records why its contents could not be read.
"""

from pathlib import Path

PLAIN_SUFFIXES = {".txt", ".csv", ".md", ".log", ".json", ".xml", ".tsv"}


def extract_text(path) -> tuple[str, str]:
    path = Path(path)
    suffix = path.suffix.lower()

    try:
        if suffix == ".pdf":
            from .pdf import extract
            return extract(path)
        if suffix in (".eml", ".msg"):
            from .eml import extract
            return extract(path)
        if suffix in (".docx", ".xlsx", ".xlsm", ".doc", ".xls", ".ppt"):
            from .office import extract
            return extract(path)
        if suffix in (".html", ".htm"):
            from .html import extract
            return extract(path)
        if suffix in PLAIN_SUFFIXES:
            return path.read_text("utf-8", "replace"), ""
        if suffix in (".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".webp"):
            return "", "image file — searchable by filename only"
    except Exception as exc:
        return "", f"extraction failed: {exc}"

    return "", f"no text extractor for {suffix or 'this file type'}"
