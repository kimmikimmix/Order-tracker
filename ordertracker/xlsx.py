"""A small read-only .xlsx reader built on the standard library.

An .xlsx file is a zip of XML parts, so no third-party package is needed to
read one. This handles what a sales export actually contains: shared strings,
inline strings, numbers, booleans, formula results and date-formatted cells.
"""

import datetime
import re
import zipfile
from xml.etree import ElementTree as ET

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}

# Number formats Excel ships with that mean "this is a date".
_BUILTIN_DATE_FORMATS = set(range(14, 23)) | set(range(45, 48)) | {27, 30, 36, 50, 57}

_COL_RE = re.compile(r"([A-Z]+)(\d+)")


def _col_index(ref: str) -> int:
    """'C7' -> 2 (zero-based column)."""
    m = _COL_RE.match(ref or "")
    if not m:
        return 0
    letters = m.group(1)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _serial_to_date(value: float) -> str:
    """Excel's day-serial to an ISO date string."""
    # Excel treats 1900 as a leap year; the 1899-12-30 epoch absorbs that.
    try:
        dt = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=float(value))
    except (OverflowError, ValueError):
        return str(value)
    if dt.hour or dt.minute:
        return dt.strftime("%Y-%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d")


def _looks_like_date_format(code: str) -> bool:
    stripped = re.sub(r"\[[^\]]*\]", "", code or "")
    stripped = re.sub(r'"[^"]*"', "", stripped)
    return bool(re.search(r"[ymdYMD]", stripped)) and "0.00" not in stripped


class Workbook:
    """Sheet names and rows, read lazily from the zip."""

    def __init__(self, path):
        self.zf = zipfile.ZipFile(path)
        self._shared = self._read_shared_strings()
        self._date_styles = self._read_date_styles()
        self.sheets = self._read_sheet_index()

    def close(self):
        self.zf.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- parts ---------------------------------------------------------------

    def _maybe(self, name):
        try:
            return self.zf.read(name)
        except KeyError:
            return None

    def _read_shared_strings(self):
        raw = self._maybe("xl/sharedStrings.xml")
        if not raw:
            return []
        root = ET.fromstring(raw)
        out = []
        for si in root.findall("m:si", _NS):
            out.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        return out

    def _read_date_styles(self):
        """Indexes into cellXfs whose number format renders a date."""
        raw = self._maybe("xl/styles.xml")
        if not raw:
            return set()
        root = ET.fromstring(raw)
        custom = {}
        for fmt in root.iter(f"{{{_NS['m']}}}numFmt"):
            try:
                custom[int(fmt.get("numFmtId"))] = fmt.get("formatCode", "")
            except (TypeError, ValueError):
                continue
        date_styles = set()
        cell_xfs = root.find("m:cellXfs", _NS)
        if cell_xfs is None:
            return date_styles
        for idx, xf in enumerate(cell_xfs.findall("m:xf", _NS)):
            try:
                fmt_id = int(xf.get("numFmtId", "0"))
            except ValueError:
                continue
            if fmt_id in _BUILTIN_DATE_FORMATS or _looks_like_date_format(custom.get(fmt_id, "")):
                date_styles.add(idx)
        return date_styles

    def _read_sheet_index(self):
        """Ordered [(name, zip part path)] for the workbook's sheets."""
        raw = self._maybe("xl/workbook.xml")
        if not raw:
            return []
        rels_raw = self._maybe("xl/_rels/workbook.xml.rels") or b"<x/>"
        rels = {}
        for rel in ET.fromstring(rels_raw):
            rid, target = rel.get("Id"), rel.get("Target", "")
            if target.startswith("/"):
                target = target[1:]
            elif not target.startswith("xl/"):
                target = "xl/" + target
            rels[rid] = target

        sheets = []
        root = ET.fromstring(raw)
        for sheet in root.iter(f"{{{_NS['m']}}}sheet"):
            rid = sheet.get(f"{{{_NS['r']}}}id")
            part = rels.get(rid)
            if part and part in self.zf.namelist():
                sheets.append((sheet.get("name", "Sheet"), part))
        return sheets

    # -- rows ----------------------------------------------------------------

    def rows(self, sheet_index: int = 0):
        """Yield each row of a sheet as a list of strings."""
        if not self.sheets:
            return
        try:
            _, part = self.sheets[sheet_index]
        except IndexError:
            return
        root = ET.fromstring(self.zf.read(part))
        for row_el in root.iter(f"{{{_NS['m']}}}row"):
            cells = {}
            for c in row_el.findall("m:c", _NS):
                cells[_col_index(c.get("r", ""))] = self._cell_value(c)
            if not cells:
                yield []
                continue
            yield [cells.get(i, "") for i in range(max(cells) + 1)]

    def _cell_value(self, c) -> str:
        ctype = c.get("t", "n")
        if ctype == "inlineStr":
            is_el = c.find("m:is", _NS)
            if is_el is None:
                return ""
            return "".join(t.text or "" for t in is_el.iter(f"{{{_NS['m']}}}t"))

        v = c.find("m:v", _NS)
        if v is None or v.text is None:
            return ""
        raw = v.text

        if ctype == "s":
            try:
                return self._shared[int(raw)]
            except (ValueError, IndexError):
                return ""
        if ctype == "b":
            return "TRUE" if raw == "1" else "FALSE"
        if ctype in ("str", "e"):
            return raw

        # Numeric — check whether its style makes it a date.
        try:
            style = int(c.get("s", "-1"))
        except ValueError:
            style = -1
        if style in self._date_styles:
            return _serial_to_date(raw)
        if raw.endswith(".0"):
            return raw[:-2]
        return raw


def read_rows(path, sheet_index: int = 0):
    """Convenience: every row of one sheet as a list of lists."""
    with Workbook(path) as wb:
        return list(wb.rows(sheet_index))


def sheet_names(path):
    with Workbook(path) as wb:
        return [name for name, _ in wb.sheets]
