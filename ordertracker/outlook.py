"""Read an Outlook .msg file, with nothing installed.

Saving an email out of Outlook gives a .msg, and a .msg is not an email
file: it is a little Microsoft database — the same compound-file container
Word used before .docx — holding one stream per property. Everything every
other program reaches for a library to read, so here is the reader.

Two layers. `Compound` understands the container: sectors, the table that
chains them, and the directory of named streams inside. `read` knows which
of those streams Outlook puts the subject, the sender, the date, the body
and the attachments in.

Nothing here writes; a .msg is only ever taken apart.
"""

import re
import struct
from datetime import datetime, timedelta, timezone

SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF

# Directory entry kinds.
STORAGE, STREAM, ROOT = 1, 2, 5


class NotAnOutlookFile(Exception):
    """The bytes are not a compound file, so not a .msg either."""


class Compound:
    """The container an Outlook .msg is packed into (OLE2 / CFBF).

    A file is cut into fixed-size sectors. One table (the FAT) says which
    sector follows which, so a stream is read by walking its chain. Streams
    smaller than the cutoff live packed together inside one big stream of
    the root entry, chained by a second, smaller table (the mini FAT).
    """

    def __init__(self, data: bytes):
        if len(data) < 512 or data[:8] != SIGNATURE:
            raise NotAnOutlookFile("not an Outlook .msg file")
        self.data = data

        shift, mini_shift = struct.unpack_from("<HH", data, 30)
        self.sector_size = 1 << shift
        self.mini_size = 1 << mini_shift
        if self.sector_size not in (512, 4096) or self.mini_size != 64:
            raise NotAnOutlookFile("unexpected sector size")

        (fat_count, first_dir, _, self.cutoff, first_mini,
         mini_count, first_difat, difat_count) = struct.unpack_from(
            "<IIIIIIII", data, 44)

        self.fat = self._read_fat(fat_count, first_difat, difat_count)
        self.entries = self._read_directory(first_dir)
        root = self.entries[0]
        self.mini_fat = self._numbers(self._chain_bytes(first_mini, mini_count))
        self.mini_stream = self._read_chain(root["start"], root["size"])

    # --- sectors ----------------------------------------------------------

    def _sector(self, number: int) -> bytes:
        start = (number + 1) * self.sector_size
        chunk = self.data[start:start + self.sector_size]
        if len(chunk) < self.sector_size:
            # A truncated file: pad rather than fail, so as much of a
            # damaged mail as possible still comes back.
            chunk = chunk.ljust(self.sector_size, b"\0")
        return chunk

    @staticmethod
    def _numbers(raw: bytes) -> list[int]:
        return list(struct.unpack(f"<{len(raw) // 4}I", raw[:len(raw) // 4 * 4]))

    def _chain_bytes(self, start: int, count: int) -> bytes:
        """Read `count` sectors following each other from `start`."""
        out, sector, seen = [], start, 0
        while sector not in (ENDOFCHAIN, FREESECT) and seen < count:
            out.append(self._sector(sector))
            sector = self.fat[sector] if sector < len(self.fat) else ENDOFCHAIN
            seen += 1
        return b"".join(out)

    def _read_fat(self, fat_count, first_difat, difat_count) -> list[int]:
        """The sector-chaining table, gathered from the header and beyond.

        The header carries the first 109 FAT sector numbers itself; a file
        big enough to need more keeps the rest in its own chain of sectors,
        each ending with a pointer to the next.
        """
        numbers = self._numbers(self.data[76:512])[:109]
        sector, guard = first_difat, 0
        while sector not in (ENDOFCHAIN, FREESECT) and guard < difat_count + 8:
            block = self._numbers(self._sector(sector))
            numbers.extend(block[:-1])
            sector = block[-1]
            guard += 1

        fat = []
        for number in numbers[:max(fat_count, 0) or len(numbers)]:
            if number in (ENDOFCHAIN, FREESECT):
                continue
            fat.extend(self._numbers(self._sector(number)))
        return fat

    def _read_chain(self, start: int, size: int) -> bytes:
        """Every sector of one stream, trimmed to its real length."""
        out, sector, guard = [], start, 0
        limit = len(self.fat) + 2
        while sector not in (ENDOFCHAIN, FREESECT) and guard < limit:
            out.append(self._sector(sector))
            sector = self.fat[sector] if sector < len(self.fat) else ENDOFCHAIN
            guard += 1
        return b"".join(out)[:size]

    def _read_mini(self, start: int, size: int) -> bytes:
        out, sector, guard = [], start, 0
        limit = len(self.mini_fat) + 2
        while sector not in (ENDOFCHAIN, FREESECT) and guard < limit:
            at = sector * self.mini_size
            out.append(self.mini_stream[at:at + self.mini_size])
            sector = (self.mini_fat[sector] if sector < len(self.mini_fat)
                      else ENDOFCHAIN)
            guard += 1
        return b"".join(out)[:size]

    # --- directory --------------------------------------------------------

    def _read_directory(self, first_dir: int) -> list[dict]:
        raw = self._read_chain(first_dir, 1 << 30)
        entries = []
        for at in range(0, len(raw) - 127, 128):
            block = raw[at:at + 128]
            name_len = struct.unpack_from("<H", block, 64)[0]
            name = ""
            if 2 <= name_len <= 64:
                name = block[:name_len - 2].decode("utf-16-le", "replace")
            kind = block[66]
            left, right, child = struct.unpack_from("<iii", block, 68)
            start, low, high = struct.unpack_from("<III", block, 116)
            size = low | (high << 32) if self.sector_size > 512 else low
            entries.append({
                "index": len(entries), "name": name, "kind": kind,
                "left": left, "right": right, "child": child,
                "start": start, "size": size,
            })
        if not entries:
            raise NotAnOutlookFile("the file has no directory")
        return entries

    def children(self, index: int = 0) -> list[dict]:
        """The entries stored directly inside one storage.

        They are held as a balanced tree, so this walks it rather than
        reading them in file order.
        """
        entry = self.entries[index]
        found, stack, seen = [], [entry["child"]], set()
        while stack:
            at = stack.pop()
            if at < 0 or at >= len(self.entries) or at in seen:
                continue
            seen.add(at)
            node = self.entries[at]
            found.append(node)
            stack.extend((node["left"], node["right"]))
        return found

    def read(self, entry: dict) -> bytes:
        """The contents of one stream."""
        if entry["kind"] != STREAM or not entry["size"]:
            return b""
        if entry["size"] < self.cutoff:
            return self._read_mini(entry["start"], entry["size"])
        return self._read_chain(entry["start"], entry["size"])


# --- the mail inside -------------------------------------------------------

# Stream names are __substg1.0_ then four hex digits of property number and
# four of type. These are the ones worth reading.
SUBJECT = "0037"
NORMALISED_SUBJECT = "0E1D"
SENDER_NAME = "0C1A"
SENDER_ADDRESS = "0C1F"
SENDER_SMTP = "5D01"
REPRESENTING_ADDRESS = "0065"
REPRESENTING_SMTP = "5D02"
DISPLAY_TO = "0E04"
DISPLAY_CC = "0E03"
BODY = "1000"
HTML_BODY = "1013"
HEADERS = "007D"
SUBMIT_TIME = "0039"
DELIVERY_TIME = "0E06"

ATTACH_DATA = "3701"
ATTACH_LONG_NAME = "3707"
ATTACH_NAME = "3704"
ATTACH_EXTENSION = "3703"

_SUBSTG = re.compile(r"^__substg1\.0_([0-9A-Fa-f]{4})([0-9A-Fa-f]{4})$")
_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def _decode(raw: bytes, kind: str) -> str:
    """Turn one property stream into text according to its type."""
    if kind.upper() == "001F":                      # unicode
        return raw.decode("utf-16-le", "replace").rstrip("\x00")
    if kind.upper() == "001E":                      # 8-bit, codepage unknown
        for encoding in ("utf-8", "cp1252", "latin-1"):
            try:
                return raw.decode(encoding).rstrip("\x00")
            except UnicodeDecodeError:
                continue
    return ""


def _properties(cf: Compound, index: int = 0) -> dict:
    """Every text property of one storage, keyed by property number."""
    out = {}
    for entry in cf.children(index):
        match = _SUBSTG.match(entry["name"])
        if not match or entry["kind"] != STREAM:
            continue
        number, kind = match.group(1).upper(), match.group(2)
        if kind.upper() == "0102":                  # binary: keep as bytes
            out.setdefault(number + ":bytes", cf.read(entry))
            continue
        text = _decode(cf.read(entry), kind)
        if text:
            out[number] = text
    return out


def _fixed_times(cf: Compound, index: int = 0) -> dict:
    """Dates out of the fixed-length property stream.

    Dates are eight bytes rather than text, so they are not kept as their
    own streams but packed into one table of sixteen-byte rows.
    """
    stream = None
    for entry in cf.children(index):
        if entry["name"] == "__properties_version1.0":
            stream = cf.read(entry)
            break
    if not stream:
        return {}

    # The top-level message reserves 32 bytes of header; attachments and
    # recipients only 8.
    start = 32 if index == 0 else 8
    found = {}
    for at in range(start, len(stream) - 15, 16):
        kind, number = struct.unpack_from("<HH", stream, at)
        if kind != 0x0040:                          # PT_SYSTIME
            continue
        ticks = struct.unpack_from("<Q", stream, at + 8)[0]
        if not ticks:
            continue
        try:
            when = _FILETIME_EPOCH + timedelta(microseconds=ticks // 10)
        except (OverflowError, OSError, ValueError):
            continue
        found[f"{number:04X}"] = when
    return found


def _attachments(cf: Compound) -> list[dict]:
    """Every file attached to the mail, with its bytes."""
    out = []
    for entry in cf.children(0):
        if entry["kind"] != STORAGE:
            continue
        if not entry["name"].startswith("__attach_version1.0"):
            continue
        props = _properties(cf, entry["index"])
        data = props.get(ATTACH_DATA + ":bytes")
        if data is None:
            # An attached email is stored as a nested message rather than
            # as bytes. Note it by name; there is no file to keep.
            name = props.get(ATTACH_LONG_NAME) or props.get(ATTACH_NAME) or ""
            if name:
                out.append({"filename": name, "data": b"", "embedded": True})
            continue
        name = (props.get(ATTACH_LONG_NAME) or props.get(ATTACH_NAME)
                or "attachment")
        extension = props.get(ATTACH_EXTENSION) or ""
        if extension and not name.lower().endswith(extension.lower()):
            name += extension
        out.append({"filename": name, "data": data, "embedded": False})
    return out


def read(data: bytes) -> dict:
    """Pull one Outlook .msg apart into the pieces an email is made of."""
    cf = Compound(data)
    props = _properties(cf)
    times = _fixed_times(cf)

    sent = times.get(SUBMIT_TIME) or times.get(DELIVERY_TIME)

    body = props.get(BODY) or ""
    if not body and props.get(HTML_BODY):
        from .extract.html import strip_tags
        body = strip_tags(props[HTML_BODY])
    if not body:
        raw_html = props.get(HTML_BODY + ":bytes")
        if raw_html:
            from .extract.html import strip_tags
            body = strip_tags(raw_html.decode("utf-8", "replace"))

    # PR_SENDER_EMAIL_ADDRESS holds an internal directory name inside a
    # company, which is no use for matching a customer. The SMTP property
    # is the real address, so it is preferred where Outlook saved one.
    sender = (props.get(SENDER_SMTP) or props.get(REPRESENTING_SMTP) or "")
    if "@" not in sender:
        for key in (SENDER_ADDRESS, REPRESENTING_ADDRESS):
            candidate = props.get(key) or ""
            if "@" in candidate:
                sender = candidate
                break

    return {
        "subject": props.get(SUBJECT) or props.get(NORMALISED_SUBJECT) or "",
        "from_name": props.get(SENDER_NAME) or "",
        "from_email": sender,
        "to": props.get(DISPLAY_TO) or "",
        "cc": props.get(DISPLAY_CC) or "",
        "sent_at": sent.strftime("%Y-%m-%d %H:%M:%S") if sent else "",
        "body": body,
        "headers": props.get(HEADERS) or "",
        "attachments": _attachments(cf),
    }
