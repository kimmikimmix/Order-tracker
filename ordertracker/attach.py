"""Photos and files hung on one line of a log.

A defect is argued with pictures. So a line in a dispute log, a line in a
folder's log and a note in an order's history can all carry images — the
board under the microscope, the packing that arrived crushed, the AOI
report — and they are read back beside the words that explain them.

The picture itself is an ordinary document, so it is stored once however
many times it is attached, it is searchable if there is any text in it,
and it opens with everything else in the DOCS page. Only the link from a
line to a document lives here.

The three logs are three tables, so the line is named by table and id
rather than by a foreign key. Table names reach SQL directly, so — as in
chase.py — they come from this file and nowhere else.
"""

from . import db, documents

# Which logs a file can hang on, and how to find the order and the customer
# the line ultimately belongs to, so the document is filed against them
# rather than landing in the unfiled pile.
OWNERS = {
    "case_entries": """SELECT k.order_id, k.company_id FROM case_entries e
                       JOIN cases k ON k.id = e.case_id WHERE e.id = ?""",
    "thread_entries": """SELECT t.order_id, t.company_id FROM thread_entries e
                         JOIN threads t ON t.id = e.thread_id WHERE e.id = ?""",
    "status_history": """SELECT o.id AS order_id, o.company_id FROM status_history h
                         JOIN orders o ON o.id = h.order_id WHERE h.id = ?""",
}

# What a browser will show without being asked to download it.
IMAGE_MIMES = ("image/png", "image/jpeg", "image/gif", "image/webp")


class AttachError(Exception):
    """Something the user needs to see and fix."""


def _owner(owner: str) -> str:
    try:
        return OWNERS[owner]
    except KeyError:
        raise AttachError(f"{owner} is not something a file can hang on") \
            from None


def _belongs_to(conn, owner: str, owner_id: int):
    """The order and customer of the line, or None when there is no line."""
    return conn.execute(_owner(owner), (owner_id,)).fetchone()


def add(owner: str, owner_id: int, filename: str, data: bytes) -> dict:
    """Store one file and hang it on a line. Returns the document row."""
    conn = db.connect()
    where = _belongs_to(conn, owner, owner_id)
    if where is None:
        raise AttachError("That line is no longer there.")

    try:
        doc = documents.store(filename, data, order_id=where["order_id"],
                              company_id=where["company_id"])
    except ValueError as exc:                      # too big for the limit
        raise AttachError(str(exc)) from exc

    with conn:
        conn.execute(
            """INSERT INTO attachments(owner, owner_id, doc_id, added_at)
               VALUES (?,?,?,?)
               ON CONFLICT(owner, owner_id, doc_id) DO NOTHING""",
            (owner, int(owner_id), doc["id"], db.now()),
        )
        db.touch(conn)
    return _row(conn, owner, owner_id, doc["id"])


def _row(conn, owner: str, owner_id: int, doc_id: int) -> dict:
    found = conn.execute(
        """SELECT a.id, a.doc_id, d.filename, d.mime, d.size, d.kind
             FROM attachments a JOIN documents d ON d.id = a.doc_id
            WHERE a.owner = ? AND a.owner_id = ? AND a.doc_id = ?""",
        (owner, int(owner_id), doc_id)).fetchone()
    return _decorate(found) if found else {}


def _decorate(row) -> dict:
    item = dict(row)
    item["is_image"] = (item.get("mime") or "") in IMAGE_MIMES
    return item


def for_lines(owner: str, owner_ids) -> dict:
    """{line id: [file, …]} for a whole log in one go."""
    ids = [int(i) for i in owner_ids]
    if not ids or owner not in OWNERS:
        return {}
    rows = db.connect().execute(
        f"""SELECT a.id, a.owner_id, a.doc_id, d.filename, d.mime, d.size,
                   d.kind
              FROM attachments a JOIN documents d ON d.id = a.doc_id
             WHERE a.owner = ? AND a.owner_id IN ({','.join('?' * len(ids))})
             ORDER BY a.id""",
        (owner, *ids)).fetchall()
    out = {}
    for row in rows:
        out.setdefault(row["owner_id"], []).append(_decorate(row))
    return out


def remove(attachment_id: int) -> None:
    """Take a file off a line, and off the disk if nothing else holds it."""
    conn = db.connect()
    row = conn.execute("SELECT doc_id FROM attachments WHERE id = ?",
                       (attachment_id,)).fetchone()
    if row is None:
        return
    with conn:
        conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        db.touch(conn)
    _drop_if_loose(conn, row["doc_id"])


def remove_all(owner: str, owner_id: int) -> None:
    """Called when the line itself goes."""
    if owner not in OWNERS:
        return
    conn = db.connect()
    doc_ids = [r["doc_id"] for r in conn.execute(
        "SELECT doc_id FROM attachments WHERE owner = ? AND owner_id = ?",
        (owner, int(owner_id)))]
    if not doc_ids:
        return
    with conn:
        conn.execute("DELETE FROM attachments WHERE owner = ? AND owner_id = ?",
                     (owner, int(owner_id)))
        db.touch(conn)
    for doc_id in doc_ids:
        _drop_if_loose(conn, doc_id)


def _drop_if_loose(conn, doc_id: int) -> None:
    """A photo nobody else holds goes with the line it was taken for.

    A document that was also filed against an order in its own right is
    left alone: it is paperwork, not just this line's picture.
    """
    held = conn.execute("SELECT 1 FROM attachments WHERE doc_id = ? LIMIT 1",
                        (doc_id,)).fetchone()
    if held:
        return
    doc = conn.execute("SELECT kind FROM documents WHERE id = ?",
                       (doc_id,)).fetchone()
    if doc is not None and (doc["kind"] or "") in ("PHOTO", "OTHER"):
        documents.delete(doc_id)


def sweep(conn) -> int:
    """Forget links whose line has been deleted. Run at startup.

    A case, a folder or an order taking its log with it does so through
    foreign keys, which know nothing about a table named in a column. This
    is the tidying up after that.
    """
    removed = 0
    for owner in OWNERS:
        rows = conn.execute(
            f"""SELECT a.id FROM attachments a
                 WHERE a.owner = ?
                   AND NOT EXISTS (SELECT 1 FROM {owner} x WHERE x.id = a.owner_id)""",
            (owner,)).fetchall()
        for row in rows:
            conn.execute("DELETE FROM attachments WHERE id = ?", (row["id"],))
            removed += 1
    return removed
