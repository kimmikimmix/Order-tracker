"""The dated log that hangs off anything being chased.

Two things in this app need exactly the same machinery: a dispute over an
order, and a folder of correspondence with a customer. Both are a headline
with a log underneath — every call, mail, meeting and decision, each keeping
the date it happened, and the ones that need chasing keeping the date they
are due.

Each owner keeps its entries in its own table, so deleting a case or a
folder takes its log with it through an ordinary foreign key and nothing has
to remember to tidy up. It is the code that is shared, not the table.
"""

import datetime

from . import db, orders

# The logs this module will touch, and what each calls its owner. Table
# names reach SQL directly, so they come from here and nowhere else.
LOGS = {
    "case_entries": ("case_id", "cases"),
    "thread_entries": ("thread_id", "threads"),
}

FIELDS = ("kind", "happened_at", "who", "summary", "detail", "doc_id",
          "email_id", "follow_up_at", "done_at")


class LogError(Exception):
    """Something the user needs to see and fix."""


def _log(table: str) -> tuple[str, str]:
    try:
        return LOGS[table]
    except KeyError:
        raise ValueError(f"{table} is not a log this app keeps") from None


def today() -> str:
    return datetime.date.today().isoformat()


def _int(value):
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def add(table: str, parent_id: int, data: dict) -> int:
    """Log one thing that happened, or one action to take."""
    owner_column, owner_table = _log(table)
    conn = db.connect()
    if conn.execute(f"SELECT 1 FROM {owner_table} WHERE id = ?",
                    (parent_id,)).fetchone() is None:
        raise LogError("That no longer exists.")

    data = dict(data or {})
    summary = str(data.get("summary") or "").strip()
    if not summary:
        raise LogError("Say in one line what happened — that is the entry.")

    stamp = db.now()
    with conn:
        cursor = conn.execute(
            f"""INSERT INTO {table}({owner_column}, kind, happened_at, who,
                                    summary, detail, doc_id, email_id,
                                    follow_up_at, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (parent_id, str(data.get("kind") or "NOTE").upper(),
             orders.normalise_date(data.get("happened_at")) or today(),
             str(data.get("who") or "").strip() or None,
             summary, str(data.get("detail") or "").strip() or None,
             _int(data.get("doc_id")), _int(data.get("email_id")),
             orders.normalise_date(data.get("follow_up_at")), stamp))
        conn.execute(f"UPDATE {owner_table} SET updated_at = ? WHERE id = ?",
                     (stamp, parent_id))
        db.touch(conn)
    return cursor.lastrowid


def update(table: str, entry_id: int, data: dict) -> None:
    """Correct an entry, keeping everything it is not asked to change."""
    _log(table)
    data = dict(data or {})
    if "summary" in data and not str(data["summary"] or "").strip():
        raise LogError("An entry needs a line saying what happened. "
                       "Delete it instead of emptying it.")
    changes = {}
    for key in FIELDS:
        if key not in data:
            continue
        value = data[key]
        if key in ("happened_at", "follow_up_at", "done_at"):
            value = orders.normalise_date(value)
        elif key in ("doc_id", "email_id"):
            value = _int(value)
        elif isinstance(value, str):
            value = value.strip() or None
        changes[key] = value
    if not changes:
        return
    conn = db.connect()
    with conn:
        sets = ", ".join(f"{key} = ?" for key in changes)
        conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?",
                     [*changes.values(), entry_id])
        db.touch(conn)


def complete(table: str, entry_id: int, done: bool = True) -> None:
    """Tick off (or untick) an action."""
    _log(table)
    conn = db.connect()
    with conn:
        conn.execute(f"UPDATE {table} SET done_at = ? WHERE id = ?",
                     (db.now() if done else None, entry_id))
        db.touch(conn)


def delete(table: str, entry_id: int) -> None:
    _log(table)
    conn = db.connect()
    with conn:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (entry_id,))
        db.touch(conn)


def entries(table: str, parent_id: int) -> list[dict]:
    """The whole log, newest first, with each action's state worked out."""
    owner_column, _ = _log(table)
    now = today()
    return [
        dict(row) | {"late": bool(row["follow_up_at"] and not row["done_at"]
                                  and row["follow_up_at"] < now)}
        for row in db.connect().execute(
            f"""SELECT e.*, d.filename, d.stored_name
                FROM {table} e
                LEFT JOIN documents d ON d.id = e.doc_id
                WHERE e.{owner_column} = ?
                ORDER BY e.happened_at DESC, e.id DESC""", (parent_id,))
    ]


def open_actions(entries_list) -> int:
    """How many entries are still waiting to be done."""
    return sum(1 for entry in entries_list
               if entry.get("follow_up_at") and not entry.get("done_at"))
