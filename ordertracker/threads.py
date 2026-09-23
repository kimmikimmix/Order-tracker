"""A folder per running conversation with a customer.

Not everything a customer sends is an order, and most of it starts long
before one exists: a request for a price, a question about a stack-up, a
sample, a chase about a delivery. Each of those is a folder — a topic on
the front saying what it is about, the emails received and sent filed
inside it, where it stands right now, a date to come back to it, and the
actions still to do.

The order book answers "what have we sold". This answers the other half:
"what is anybody waiting on me for".
"""

import datetime
import re

from . import chase, db, orders, prefs

LOG = "thread_entries"

# Folders nobody is working any more.
SETTLED_STATUSES = ("WON", "LOST", "CLOSED")


class ThreadError(Exception):
    """Something the user needs to see and fix."""


def _today() -> str:
    return datetime.date.today().isoformat()


def _plus_days(days) -> str:
    return (datetime.date.today() + datetime.timedelta(days=int(days))).isoformat()


def next_ref(conn=None) -> str:
    """The next folder reference, counted within the year: F-2026-001."""
    conn = conn or db.connect()
    prefix = f"F-{datetime.date.today().year}-"
    highest = 0
    for row in conn.execute("SELECT ref FROM threads WHERE ref LIKE ?",
                            (prefix + "%",)):
        found = re.search(r"(\d+)$", row["ref"] or "")
        if found:
            highest = max(highest, int(found.group(1)))
    return f"{prefix}{highest + 1:03d}"


FIELDS = ("topic", "summary", "situation", "kind", "status", "priority",
          "value_usd", "opened_at", "follow_up_at", "closed_at", "owner",
          "order_id")


def _clean(data: dict) -> dict:
    out = {}
    for key, value in (data or {}).items():
        out[key] = value.strip() if isinstance(value, str) else value
    for key in ("opened_at", "follow_up_at", "closed_at"):
        if key in out:
            out[key] = orders.normalise_date(out[key])
    if "value_usd" in out:
        out["value_usd"] = _float(out.get("value_usd"))
    if "order_id" in out:
        out["order_id"] = _int(out.get("order_id"))
    return out


def _int(value):
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _float(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def open_folder(data: dict, actor: str = "") -> int:
    """Start a folder for a customer. Returns its id."""
    data = _clean(data)
    topic = (data.get("topic") or "").strip()
    if not topic:
        raise ThreadError("Give the folder a topic — one line saying what "
                          "this is about.")

    conn = db.connect()
    try:
        company_id = orders.company_id_for(conn, data)
    except orders.OrderError as exc:
        raise ThreadError(str(exc)) from exc
    if not company_id:
        raise ThreadError("A folder belongs to a customer — choose one first.")

    statuses = prefs.get("thread_statuses") or ["OPEN"]
    kinds = prefs.get("thread_kinds") or ["ENQUIRY"]
    stamp = db.now()
    opened = data.get("opened_at") or _today()

    with conn:
        cursor = conn.execute(
            """INSERT INTO threads(ref, company_id, order_id, topic, summary,
                                   situation, kind, status, priority,
                                   value_usd, opened_at, follow_up_at, owner,
                                   created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (next_ref(conn), company_id, data.get("order_id"), topic,
             data.get("summary"), data.get("situation"),
             (data.get("kind") or kinds[0]).upper(),
             (data.get("status") or statuses[0]).upper(),
             (data.get("priority") or "NORMAL").upper(),
             data.get("value_usd"), opened,
             data.get("follow_up_at")
             or _plus_days(prefs.get("thread_due_days") or 3),
             data.get("owner") or actor, stamp, stamp))
        folder_id = cursor.lastrowid
        db.touch(conn)

    chase.add(LOG, folder_id, {
        "kind": "NOTE", "happened_at": opened, "who": data.get("owner") or actor,
        "summary": f"Folder opened: {topic}", "detail": data.get("summary")})
    return folder_id


def update_folder(folder_id: int, data: dict, actor: str = "") -> dict:
    """Change a folder, logging a status move as an entry of its own."""
    data = _clean(data)
    conn = db.connect()
    folder = conn.execute("SELECT * FROM threads WHERE id = ?",
                          (folder_id,)).fetchone()
    if folder is None:
        raise ThreadError("That folder no longer exists.")

    changes = {k: data[k] for k in FIELDS if k in data}
    if "topic" in changes and not changes["topic"]:
        raise ThreadError("A folder cannot lose its topic.")
    for key in ("kind", "status", "priority"):
        if changes.get(key):
            changes[key] = str(changes[key]).upper()

    moved_to = changes.get("status")
    if moved_to and moved_to in SETTLED_STATUSES and not changes.get("closed_at"):
        changes["closed_at"] = _today()
    if moved_to and moved_to not in SETTLED_STATUSES:
        changes["closed_at"] = None

    stamp = db.now()
    with conn:
        if changes:
            sets = ", ".join(f"{key} = ?" for key in changes)
            conn.execute(f"UPDATE threads SET {sets}, updated_at = ? WHERE id = ?",
                         [*changes.values(), stamp, folder_id])
        db.touch(conn)

    if moved_to and moved_to != folder["status"]:
        chase.add(LOG, folder_id, {
            "kind": "DECISION", "who": actor,
            "summary": f"Status moved from {folder['status']} to {moved_to}"})
    return get_folder(folder_id)


def delete_folder(folder_id: int) -> None:
    conn = db.connect()
    with conn:
        conn.execute("UPDATE emails SET thread_id = NULL WHERE thread_id = ?",
                     (folder_id,))
        conn.execute("DELETE FROM threads WHERE id = ?", (folder_id,))
        db.touch(conn)


# --- the log ---------------------------------------------------------------

def add_entry(folder_id: int, data: dict) -> int:
    try:
        return chase.add(LOG, folder_id, data)
    except chase.LogError as exc:
        raise ThreadError(str(exc)) from exc


def update_entry(entry_id: int, data: dict) -> None:
    chase.update(LOG, entry_id, data)


def complete_follow_up(entry_id: int, done: bool = True) -> None:
    chase.complete(LOG, entry_id, done)


def delete_entry(entry_id: int) -> None:
    chase.delete(LOG, entry_id)


def file_email(folder_id: int, email_id: int, actor: str = "") -> dict:
    """Put an email in the folder, and log it as having arrived or gone.

    A mail that nobody could place — no order number, no sender we know,
    passed on by a colleague halfway through — takes the folder's customer
    as its own, because putting it in this folder is a person saying who it
    is from. It is then settled: no order reference was needed.

    A mail that already has a customer keeps it. The folder is a second
    home for that one, not a reassignment.
    """
    conn = db.connect()
    folder = conn.execute("SELECT * FROM threads WHERE id = ?",
                          (folder_id,)).fetchone()
    if folder is None:
        raise ThreadError("That folder no longer exists.")
    mail = conn.execute("SELECT * FROM emails WHERE id = ?",
                        (email_id,)).fetchone()
    if mail is None:
        raise ThreadError("That email is no longer on file.")

    already = conn.execute(
        f"SELECT 1 FROM {LOG} WHERE thread_id = ? AND email_id = ?",
        (folder_id, email_id)).fetchone()

    adopt = not mail["company_id"]
    with conn:
        if adopt:
            note = (f"filed into {folder['ref']} by hand"
                    + (f" by {actor}" if actor else ""))
            conn.execute(
                """UPDATE emails SET thread_id = ?, company_id = ?,
                                     needs_review = 0, confidence = 1.0,
                                     matched_on = ?
                   WHERE id = ?""",
                (folder_id, folder["company_id"], note, email_id))
        else:
            conn.execute("UPDATE emails SET thread_id = ? WHERE id = ?",
                         (folder_id, email_id))
        db.touch(conn)

    if adopt and mail["doc_id"]:
        # Keep the stored mail with the customer too, so it is findable
        # from their paperwork and not only from the folder.
        from . import documents
        try:
            documents.attach(mail["doc_id"], mail["order_id"],
                             folder["company_id"])
        except ValueError:
            pass
    if not already:
        chase.add(LOG, folder_id, {
            "kind": "EMAIL OUT" if mail["direction"] == "OUT" else "EMAIL IN",
            "happened_at": (mail["sent_at"] or mail["filed_at"] or "")[:10],
            "who": mail["from_name"] or mail["from_email"],
            "summary": mail["subject"] or "(no subject)",
            "detail": mail["summary"], "email_id": email_id,
            "doc_id": mail["doc_id"]})
    return get_folder(folder_id)


def remove_email(folder_id: int, email_id: int) -> None:
    conn = db.connect()
    with conn:
        conn.execute("UPDATE emails SET thread_id = NULL "
                     "WHERE id = ? AND thread_id = ?", (email_id, folder_id))
        db.touch(conn)


# --- reading ---------------------------------------------------------------

def _decorate(row) -> dict:
    item = dict(row)
    item["open"] = item["status"] not in SETTLED_STATUSES
    item["overdue"] = bool(item["open"] and item.get("follow_up_at")
                           and item["follow_up_at"] < _today())
    parsed = orders.as_date(item.get("opened_at"))
    item["age_days"] = ((datetime.date.today() - parsed).days
                        if parsed else None)
    return item


def get_folder(folder_id: int) -> dict | None:
    conn = db.connect()
    row = conn.execute(
        """SELECT t.*, c.name AS company, c.contact_name, c.contact_email,
                  o.order_no, o.product_code, o.product_name
           FROM threads t
           JOIN companies c ON c.id = t.company_id
           LEFT JOIN orders o ON o.id = t.order_id
           WHERE t.id = ?""", (folder_id,)).fetchone()
    if row is None:
        return None
    item = _decorate(row)
    item["entries"] = chase.entries(LOG, folder_id)
    item["open_actions"] = chase.open_actions(item["entries"])
    item["emails"] = [
        dict(mail) for mail in conn.execute(
            """SELECT id, doc_id, sent_at, filed_at, direction, from_name,
                      from_email, subject, summary, category, attachments
               FROM emails WHERE thread_id = ?
               ORDER BY COALESCE(sent_at, filed_at) DESC""", (folder_id,))
    ]
    return item


def list_folders(company_id=None, status=None, open_only=False, query=None,
                 limit=500) -> list[dict]:
    sql = ["""SELECT t.*, c.name AS company,
                     o.order_no, o.product_code, o.product_name,
                     (SELECT COUNT(*) FROM emails e
                       WHERE e.thread_id = t.id) AS email_count,
                     (SELECT COUNT(*) FROM thread_entries x
                       WHERE x.thread_id = t.id) AS entries,
                     (SELECT COUNT(*) FROM thread_entries x
                       WHERE x.thread_id = t.id AND x.follow_up_at IS NOT NULL
                         AND x.done_at IS NULL) AS open_actions
              FROM threads t
              JOIN companies c ON c.id = t.company_id
              LEFT JOIN orders o ON o.id = t.order_id"""]
    where, params = [], []
    if company_id:
        where.append("t.company_id = ?")
        params.append(company_id)
    if status:
        where.append("t.status = ?")
        params.append(str(status).upper())
    if open_only:
        marks = ",".join("?" * len(SETTLED_STATUSES))
        where.append(f"t.status NOT IN ({marks})")
        params.extend(SETTLED_STATUSES)
    if query:
        where.append("(t.topic LIKE ? OR t.summary LIKE ? OR t.situation LIKE ? "
                     "OR t.ref LIKE ? OR c.name LIKE ?)")
        params += [f"%{query}%"] * 5
    if where:
        sql.append("WHERE " + " AND ".join(where))
    # Whatever is due soonest comes first; folders with no date wait at the
    # bottom rather than jumping the queue.
    sql.append("""ORDER BY CASE WHEN t.follow_up_at IS NULL THEN 1 ELSE 0 END,
                           t.follow_up_at ASC, t.opened_at DESC LIMIT ?""")
    params.append(limit)
    return [_decorate(row) for row in db.connect().execute(" ".join(sql), params)]


def follow_ups(within_days: int = 7) -> list[dict]:
    """Actions logged in folders that need doing, soonest first."""
    horizon = _plus_days(within_days)
    marks = ",".join("?" * len(SETTLED_STATUSES))
    rows = db.connect().execute(
        f"""SELECT e.*, t.ref, t.topic, t.status, t.company_id,
                   c.name AS company
            FROM thread_entries e
            JOIN threads t ON t.id = e.thread_id
            JOIN companies c ON c.id = t.company_id
            WHERE e.follow_up_at IS NOT NULL AND e.done_at IS NULL
              AND e.follow_up_at <= ? AND t.status NOT IN ({marks})
            ORDER BY e.follow_up_at ASC, e.id ASC""",
        (horizon, *SETTLED_STATUSES)).fetchall()
    today = _today()
    return [dict(row) | {"late": row["follow_up_at"] < today} for row in rows]


def due_folders(within_days: int = 7) -> list[dict]:
    """Folders whose own next-contact date has come round."""
    horizon = _plus_days(within_days)
    marks = ",".join("?" * len(SETTLED_STATUSES))
    rows = db.connect().execute(
        f"""SELECT t.*, c.name AS company
            FROM threads t JOIN companies c ON c.id = t.company_id
            WHERE t.follow_up_at IS NOT NULL AND t.follow_up_at <= ?
              AND t.status NOT IN ({marks})
            ORDER BY t.follow_up_at ASC""",
        (horizon, *SETTLED_STATUSES)).fetchall()
    return [_decorate(row) for row in rows]


def summary() -> dict:
    """Counts for the dashboard."""
    conn = db.connect()
    marks = ",".join("?" * len(SETTLED_STATUSES))
    today = _today()
    open_count = conn.execute(
        f"SELECT COUNT(*) AS n FROM threads WHERE status NOT IN ({marks})",
        SETTLED_STATUSES).fetchone()["n"]
    due = conn.execute(
        f"""SELECT COUNT(*) AS n FROM threads
            WHERE status NOT IN ({marks}) AND follow_up_at IS NOT NULL
              AND follow_up_at <= ?""",
        (*SETTLED_STATUSES, today)).fetchone()["n"]
    overdue = conn.execute(
        f"""SELECT COUNT(*) AS n FROM threads
            WHERE status NOT IN ({marks}) AND follow_up_at IS NOT NULL
              AND follow_up_at < ?""",
        (*SETTLED_STATUSES, today)).fetchone()["n"]
    actions = conn.execute(
        f"""SELECT COUNT(*) AS n FROM thread_entries e
            JOIN threads t ON t.id = e.thread_id
            WHERE e.follow_up_at IS NOT NULL AND e.done_at IS NULL
              AND t.status NOT IN ({marks})""", SETTLED_STATUSES).fetchone()["n"]
    late_actions = conn.execute(
        f"""SELECT COUNT(*) AS n FROM thread_entries e
            JOIN threads t ON t.id = e.thread_id
            WHERE e.follow_up_at IS NOT NULL AND e.done_at IS NULL
              AND e.follow_up_at < ? AND t.status NOT IN ({marks})""",
        (today, *SETTLED_STATUSES)).fetchone()["n"]
    return {"open": open_count, "due": due, "overdue": overdue,
            "open_actions": actions, "late_actions": late_actions}


def for_company(company_id: int) -> dict:
    """What one customer has running, for their row in the customer list."""
    conn = db.connect()
    marks = ",".join("?" * len(SETTLED_STATUSES))
    row = conn.execute(
        f"""SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status NOT IN ({marks}) THEN 1 ELSE 0 END) AS open
            FROM threads WHERE company_id = ?""",
        (*SETTLED_STATUSES, company_id)).fetchone()
    return {"total": row["total"] or 0, "open": row["open"] or 0}


def counts_by_company() -> dict:
    """{company_id: {"open": n, "total": n}} for the customer list."""
    marks = ",".join("?" * len(SETTLED_STATUSES))
    rows = db.connect().execute(
        f"""SELECT company_id, COUNT(*) AS total,
                   SUM(CASE WHEN status NOT IN ({marks}) THEN 1 ELSE 0 END) AS open
            FROM threads GROUP BY company_id""", SETTLED_STATUSES).fetchall()
    return {row["company_id"]: {"total": row["total"] or 0,
                                "open": row["open"] or 0} for row in rows}
