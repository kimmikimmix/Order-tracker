"""Document storage: keep the file, read its text, file it against an order.

Files are stored under data/documents/ with a content-addressed name so two
copies of the same PO never occupy two slots, while the original filename is
kept in the database for display.
"""

import hashlib
import mimetypes
import re
import unicodedata
from pathlib import Path

from . import config, db
from .extract import extract_text

# Cap on how much extracted text is kept per document. Long contracts are
# still fully searchable well past this; it only bounds the database.
MAX_TEXT_CHARS = 400_000


def _best_keyword_match(haystack: str) -> str | None:
    """The kind whose longest keyword appears in the text, if any.

    Longest wins so that "invoice for PO-2026-4481" is filed as an INVOICE
    rather than being claimed by the bare "po" in the reference number.
    """
    best_kind, best_length = None, 0
    for kind, keywords in config.DOC_KINDS.items():
        for word in keywords:
            if word.startswith("."):
                continue  # an extension, handled separately
            if len(word) <= best_length:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", haystack):
                best_kind, best_length = kind, len(word)
    return best_kind


def guess_kind(filename: str, text: str = "") -> str:
    """Classify a document from its name, falling back to its first lines."""
    suffix = Path(filename).suffix.lower()
    for kind, keywords in config.DOC_KINDS.items():
        if suffix and suffix in keywords:
            return kind

    return (_best_keyword_match(filename.lower())
            or _best_keyword_match((text or "")[:400].lower())
            or "OTHER")


# Characters no filesystem will take, plus the device names Windows reserves.
_UNSAFE_CHARS = set('<>:"/\\|?*')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL",
                   *(f"COM{i}" for i in range(1, 10)),
                   *(f"LPT{i}" for i in range(1, 10))}

# Room for the content hash prefix inside the usual 255-byte filename limit.
_MAX_NAME_BYTES = 180


def _strip_unsafe(text: str) -> str:
    return "".join("_" if (ch in _UNSAFE_CHARS or ord(ch) < 32) else ch
                   for ch in text)


def _truncate_bytes(text: str, limit: int) -> str:
    """Trim to a byte budget without splitting a character in half."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", "ignore")


def safe_name(filename: str) -> str:
    """A filename safe to put on disk, keeping its extension.

    Non-Latin names are kept as they are: every filesystem this runs on
    stores Unicode, and transliterating a Korean or Japanese filename to
    ASCII throws away the whole name — and, worse, the extension with it,
    which is what decides how the file gets read for searching.
    """
    raw = unicodedata.normalize("NFC", str(filename or "")).strip()
    raw = raw.replace("\\", "/").rsplit("/", 1)[-1]  # drop any folder part
    if not raw:
        return "file"

    stem, dot, extension = raw.rpartition(".")
    if not dot or not stem:          # no extension, or a leading-dot name
        stem, extension = raw, ""

    stem = _strip_unsafe(stem).strip(" .")
    extension = _strip_unsafe(extension).strip(" .")

    if stem.upper() in _RESERVED_NAMES:
        stem = f"_{stem}"
    if not stem:
        stem = "file"

    suffix = f".{extension[:16]}" if extension else ""
    stem = _truncate_bytes(stem, _MAX_NAME_BYTES - len(suffix.encode("utf-8")))
    return f"{stem}{suffix}"


def store(filename: str, data: bytes, order_id=None, company_id=None,
          kind=None) -> dict:
    """Save an uploaded file, index its text and return the document row."""
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise ValueError(
            f"{filename} is larger than the {config.MAX_UPLOAD_BYTES // (1024*1024)} MB limit."
        )

    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    clean = safe_name(filename)
    stored_name = f"{digest[:16]}_{clean}"
    path = config.DOCS_DIR / stored_name

    if not path.exists():
        path.write_bytes(data)

    conn = db.connect()
    existing = conn.execute(
        "SELECT * FROM documents WHERE stored_name = ?", (stored_name,)
    ).fetchone()
    if existing:
        # Same bytes already on file. Re-point it if this upload says where it
        # belongs and the old row did not know.
        if order_id and not existing["order_id"]:
            attach(existing["id"], order_id)
            return dict(conn.execute(
                "SELECT * FROM documents WHERE id = ?", (existing["id"],)
            ).fetchone()) | {"duplicate": True}
        return dict(existing) | {"duplicate": True}

    text, note = extract_text(path)
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        note = (note + "; " if note else "") + "long document, indexed in part"

    if order_id and not company_id:
        row = conn.execute(
            "SELECT company_id FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if row:
            company_id = row["company_id"]

    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with conn:
        cur = conn.execute(
            """INSERT INTO documents(order_id, company_id, filename, stored_name,
                                     kind, mime, size, sha256, content_text,
                                     extract_note, uploaded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (order_id, company_id, filename, stored_name,
             kind or guess_kind(filename, text), mime, len(data), digest,
             text or None, note or None, db.now()),
        )
        doc_id = cur.lastrowid
        db.reindex_document(conn, doc_id)
        if order_id:
            conn.execute("UPDATE orders SET updated_at = ? WHERE id = ?",
                         (db.now(), order_id))
            db.reindex_order(conn, order_id)

    return dict(conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone())


def autofile(doc_id: int) -> int | None:
    """Try to work out which order a loose document belongs to.

    Matches the order number or customer PO number against the document's
    filename and its text. Only an unambiguous single match is accepted —
    a guess that files paperwork against the wrong customer is worse than
    leaving it in the unfiled tray.
    """
    conn = db.connect()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None or doc["order_id"]:
        return doc["order_id"] if doc else None

    haystack = f"{doc['filename']}\n{(doc['content_text'] or '')[:20000]}".upper()
    haystack = re.sub(r"[^A-Z0-9]+", " ", haystack)

    matches = set()
    for row in conn.execute("SELECT id, order_no, po_number FROM orders"):
        for reference in (row["order_no"], row["po_number"]):
            if not reference or len(str(reference)) < 4:
                continue
            flat = re.sub(r"[^A-Z0-9]+", " ", str(reference).upper()).strip()
            if flat and flat in haystack:
                matches.add(row["id"])

    if len(matches) != 1:
        return None
    order_id = matches.pop()
    attach(doc_id, order_id)
    return order_id


def attach(doc_id: int, order_id, company_id=None) -> None:
    """File a document against an order, or against a customer alone.

    Plenty of paperwork arrives before anybody knows which order it is
    for — and some of it never belongs to one. Filing it under the
    customer keeps it findable instead of leaving it in the loose tray.
    """
    conn = db.connect()
    if order_id:
        row = conn.execute(
            "SELECT company_id FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if row is None:
            raise ValueError("That order no longer exists.")
        company_id = row["company_id"]
    with conn:
        conn.execute(
            "UPDATE documents SET order_id = ?, company_id = ? WHERE id = ?",
            (order_id, company_id, doc_id),
        )
        if order_id:
            conn.execute("UPDATE orders SET updated_at = ? WHERE id = ?",
                         (db.now(), order_id))


def set_kind(doc_id: int, kind: str) -> None:
    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET kind = ? WHERE id = ?",
                     (kind.strip().upper() or "OTHER", doc_id))


def get(doc_id: int) -> dict | None:
    row = db.connect().execute(
        "SELECT * FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    return dict(row) if row else None


def path_for(doc: dict) -> Path:
    return config.DOCS_DIR / doc["stored_name"]


def list_documents(order_id=None, unfiled=False, limit=500) -> list[dict]:
    conn = db.connect()
    sql = """SELECT d.id, d.filename, d.kind, d.mime, d.size, d.uploaded_at,
                    d.order_id, d.extract_note,
                    length(COALESCE(d.content_text,'')) AS text_len,
                    o.order_no, c.name AS company
             FROM documents d
             LEFT JOIN orders o ON o.id = d.order_id
             LEFT JOIN companies c ON c.id = d.company_id"""
    params = []
    if unfiled:
        sql += " WHERE d.order_id IS NULL"
    elif order_id:
        sql += " WHERE d.order_id = ?"
        params.append(order_id)
    sql += " ORDER BY d.uploaded_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def delete(doc_id: int) -> None:
    conn = db.connect()
    doc = conn.execute(
        "SELECT stored_name, sha256 FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if doc is None:
        return
    with conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.execute("DELETE FROM documents_fts WHERE doc_id = ?", (doc_id,))
    still_used = conn.execute(
        "SELECT 1 FROM documents WHERE stored_name = ? LIMIT 1", (doc["stored_name"],)
    ).fetchone()
    if not still_used:
        remove_file(doc["stored_name"])


def remove_file(stored_name: str) -> None:
    """Delete the file from disk, tolerating one that is already gone."""
    try:
        (config.DOCS_DIR / stored_name).unlink(missing_ok=True)
    except OSError:
        pass


def reextract_all() -> int:
    """Re-run extraction over every stored file. Useful after an upgrade."""
    conn = db.connect()
    rows = conn.execute("SELECT id, stored_name FROM documents").fetchall()
    done = 0
    for row in rows:
        path = config.DOCS_DIR / row["stored_name"]
        if not path.exists():
            continue
        text, note = extract_text(path)
        with conn:
            conn.execute(
                "UPDATE documents SET content_text = ?, extract_note = ? WHERE id = ?",
                (text[:MAX_TEXT_CHARS] or None, note or None, row["id"]),
            )
            db.reindex_document(conn, row["id"])
        done += 1
    return done
