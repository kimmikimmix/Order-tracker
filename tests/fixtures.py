"""Sample files used by the tests.

The PDF writer is the one that ships with the app (used by --demo), so the
tests exercise the same generator the product does.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ordertracker.sampledata import _pdf


def make_pdf(lines, path):
    """Write a one-page PDF containing the given lines of text."""
    path.write_bytes(_pdf(lines))
    return path


def make_xlsx(rows, path, date_columns=()):
    """Write a minimal .xlsx holding the given rows (lists of values)."""
    import zipfile
    from xml.sax.saxutils import escape

    def col_letter(i):
        s = ""
        i += 1
        while i:
            i, rem = divmod(i - 1, 26)
            s = chr(65 + rem) + s
        return s

    sheet_rows = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{col_letter(c)}{r}"
            if c in date_columns and r > 1:
                # Store as a styled serial number, the way Excel really does.
                import datetime
                d = datetime.datetime.strptime(str(value), "%Y-%m-%d")
                serial = (d - datetime.datetime(1899, 12, 30)).days
                cells.append(f'<c r="{ref}" s="1"><v>{serial}</v></c>')
            elif isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        sheet_rows.append(f'<row r="{r}">{"".join(cells)}</row>')

    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            "</Types>")
        z.writestr("_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>")
        z.writestr("xl/workbook.xml",
            f'<?xml version="1.0"?><workbook {ns} {rns}><sheets>'
            '<sheet name="Orders" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>")
        z.writestr("xl/styles.xml",
            f'<?xml version="1.0"?><styleSheet {ns}><cellXfs count="2">'
            '<xf numFmtId="0"/><xf numFmtId="14" applyNumberFormat="1"/>'
            "</cellXfs></styleSheet>")
        z.writestr("xl/worksheets/sheet1.xml",
            f'<?xml version="1.0"?><worksheet {ns}><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    return path


# --- Outlook .msg ----------------------------------------------------------
# A .msg is a compound file, so testing the reader means writing one. This
# builds a small but genuinely valid file: a root entry, one stream per
# property, small ones packed into the mini stream exactly as Outlook packs
# them, and attachments in their own storages.

import struct
from datetime import datetime, timezone

_END = 0xFFFFFFFE
_FREE = 0xFFFFFFFF
_FATSECT = 0xFFFFFFFD
_CUTOFF = 4096
_SECTOR = 512
_MINI = 64


def _dir_entry(name, kind, left=-1, right=-1, child=-1, start=_END, size=0):
    raw = bytearray(128)
    encoded = name.encode("utf-16-le")[:62]
    raw[0:len(encoded)] = encoded
    struct.pack_into("<H", raw, 64, len(encoded) + 2)
    raw[66] = kind
    raw[67] = 1                                   # colour: black
    struct.pack_into("<iii", raw, 68, left, right, child)
    struct.pack_into("<III", raw, 116, start, size & 0xFFFFFFFF, 0)
    return bytes(raw)


def _filetime(when):
    delta = when - datetime(1601, 1, 1, tzinfo=timezone.utc)
    return int(delta.total_seconds() * 10_000_000)


def make_msg(path, subject="", sender_name="", sender_email="", to="",
             body="", sent=None, attachments=(), headers=""):
    """Write a valid Outlook .msg holding these fields."""
    props = {}

    def text(number, value):
        if value:
            props[f"__substg1.0_{number}001F"] = value.encode("utf-16-le")

    text("0037", subject)
    text("0C1A", sender_name)
    text("5D01", sender_email)
    text("0E04", to)
    text("1000", body)
    text("007D", headers)

    # The fixed-length property table, holding the date the mail was sent.
    table = bytearray(32)
    if sent:
        table += struct.pack("<HHI", 0x0040, 0x0039, 6) + struct.pack(
            "<Q", _filetime(sent))
    props["__properties_version1.0"] = bytes(table)

    # name -> (kind, contents); storages carry their children with them.
    storages = []
    for index, attachment in enumerate(attachments):
        inner = {
            "__substg1.0_3707001F": attachment["filename"].encode("utf-16-le"),
            "__substg1.0_37010102": attachment["data"],
        }
        storages.append((f"__attach_version1.0_#{index:08X}", inner))

    entries = []          # built as a right-leaning chain, which is a valid tree

    def add_stream(name, data):
        entries.append({"name": name, "kind": 2, "child": -1, "data": data})
        return len(entries) - 1

    entries.append({"name": "Root Entry", "kind": 5, "child": -1, "data": b""})
    top = []
    for name, data in props.items():
        top.append(add_stream(name, data))
    for name, inner in storages:
        entries.append({"name": name, "kind": 1, "child": -1, "data": b""})
        storage_at = len(entries) - 1
        top.append(storage_at)
        inner_ids = [add_stream(inner_name, inner_data)
                     for inner_name, inner_data in inner.items()]
        entries[storage_at]["child"] = inner_ids[0]
        for a, b in zip(inner_ids, inner_ids[1:]):
            entries[a]["right"] = b

    entries[0]["child"] = top[0]
    for a, b in zip(top, top[1:]):
        entries[a]["right"] = b

    # Pack the small streams into the mini stream, the big ones into sectors.
    mini_blob, mini_fat = bytearray(), []
    sectors, fat = [], []

    def add_sectors(data):
        first = len(sectors)
        blocks = [data[i:i + _SECTOR].ljust(_SECTOR, b"\0")
                  for i in range(0, max(len(data), 1), _SECTOR)]
        for offset, block in enumerate(blocks):
            sectors.append(block)
            fat.append(first + offset + 1 if offset + 1 < len(blocks) else _END)
        return first

    for entry in entries:
        data = entry.get("data") or b""
        if entry["kind"] != 2 or not data:
            entry["start"], entry["size"] = _END, 0
            continue
        entry["size"] = len(data)
        if len(data) < _CUTOFF:
            first = len(mini_fat)
            blocks = [data[i:i + _MINI].ljust(_MINI, b"\0")
                      for i in range(0, len(data), _MINI)]
            for offset, block in enumerate(blocks):
                mini_blob += block
                mini_fat.append(first + offset + 1
                                if offset + 1 < len(blocks) else _END)
            entry["start"] = first
        else:
            entry["start"] = add_sectors(data)

    mini_start = add_sectors(bytes(mini_blob)) if mini_blob else _END
    entries[0]["start"], entries[0]["size"] = mini_start, len(mini_blob)

    mini_fat_raw = b"".join(struct.pack("<I", n) for n in mini_fat)
    mini_fat_raw += b"\xff" * ((-len(mini_fat_raw)) % _SECTOR)   # 0xFFFFFFFF: free
    mini_fat_raw = mini_fat_raw or b"\xff" * _SECTOR
    mini_fat_count = len(mini_fat_raw) // _SECTOR
    mini_fat_start = add_sectors(mini_fat_raw)

    directory = b"".join(
        _dir_entry(e["name"], e["kind"], e.get("left", -1), e.get("right", -1),
                   e["child"], e.get("start", _END), e.get("size", 0))
        for e in entries)
    dir_start = add_sectors(directory)

    # FAT sectors describe every sector including themselves, so the count
    # settles rather than being computed in one go.
    per_sector = _SECTOR // 4
    fat_count = 1
    while (len(sectors) + fat_count + per_sector - 1) // per_sector > fat_count:
        fat_count += 1
    fat_sector_numbers = [len(sectors) + i for i in range(fat_count)]
    fat = fat + [_FATSECT] * fat_count
    fat += [_FREE] * (fat_count * per_sector - len(fat))
    fat_raw = b"".join(struct.pack("<I", n) for n in fat)
    for i in range(fat_count):
        sectors.append(fat_raw[i * _SECTOR:(i + 1) * _SECTOR])

    header = bytearray(512)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HH", header, 24, 0x003E, 3)
    struct.pack_into("<H", header, 28, 0xFFFE)
    struct.pack_into("<HH", header, 30, 9, 6)      # 512-byte and 64-byte sectors
    struct.pack_into("<IIIIIIII", header, 44,
                     fat_count, dir_start, 0, _CUTOFF,
                     mini_fat_start, mini_fat_count, _END, 0)
    difat = [_FREE] * 109
    for i, number in enumerate(fat_sector_numbers[:109]):
        difat[i] = number
    struct.pack_into("<109I", header, 76, *difat)

    path.write_bytes(bytes(header) + b"".join(sectors))
    return path
