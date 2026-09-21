"""Text out of Office files, again using only the standard library.

.docx and .xlsx are both zipped XML, so their text is reachable without any
third-party package. Legacy .doc / .xls (the old binary formats) are not
readable this way; those files are stored and stay findable by filename.
"""

import zipfile
from xml.etree import ElementTree as ET

from .html import strip_tags

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx(path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as z:
        try:
            root = ET.fromstring(z.read("word/document.xml"))
        except KeyError:
            return "", "no document body found in .docx"
    paragraphs = []
    for para in root.iter(f"{_W}p"):
        text = "".join(node.text or "" for node in para.iter(f"{_W}t"))
        if text.strip():
            paragraphs.append(text)
    return "\n".join(paragraphs), ""


def _xlsx(path) -> tuple[str, str]:
    from ..xlsx import Workbook

    lines = []
    with Workbook(path) as wb:
        for index, (name, _) in enumerate(wb.sheets):
            lines.append(f"[sheet: {name}]")
            for row in wb.rows(index):
                cells = [str(c) for c in row if str(c).strip()]
                if cells:
                    lines.append("\t".join(cells))
    return "\n".join(lines), ""


def extract(path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            return _docx(path)
        if suffix in (".xlsx", ".xlsm"):
            return _xlsx(path)
        if suffix in (".doc", ".xls", ".ppt"):
            return "", "legacy binary Office format — searchable by filename only"
    except (zipfile.BadZipFile, ET.ParseError) as exc:
        return "", f"file is not readable as Office XML: {exc}"
    except Exception as exc:
        return "", f"extraction failed: {exc}"
    return "", ""
