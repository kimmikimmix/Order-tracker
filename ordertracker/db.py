"""SQLite storage: schema, connections and full-text search wiring.

One file on disk holds everything structured; the documents themselves live
beside it under data/documents/. Copy the data/ folder and you have copied
the entire system.
"""

import sqlite3
import threading
from datetime import datetime, timezone

from . import config

_local = threading.local()

SCHEMA_VERSION = 1


def now() -> str:
    """UTC timestamp in a sortable, SQLite-friendly form."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class StorageError(Exception):
    """The data folder exists but cannot hold the database."""


def _explain_open_failure(exc: Exception) -> "StorageError":
    """Turn SQLite's terse refusal into something actionable."""
    return StorageError(
        f"Could not open the database at:\n    {config.DB_PATH}\n\n"
        f"SQLite said: {exc}\n\n"
        "The folder was created, so something is stopping files being made\n"
        "inside it. On Windows this is usually ransomware protection\n"
        "(Windows Security > Virus & threat protection > Controlled folder\n"
        "access), OneDrive holding the folder online-only, or antivirus.\n\n"
        "Run the check for a full report:\n"
        "    py doctor.py\n\n"
        "Or keep the data somewhere unrestricted:\n"
        '    py run.py --demo --data "%LOCALAPPDATA%\\OrderTracker"'
    )


def connect() -> sqlite3.Connection:
    """Return this thread's connection, creating it on first use."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(config.DB_PATH, timeout=30)
        except sqlite3.OperationalError as exc:
            raise _explain_open_failure(exc) from exc
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    code         TEXT,
    contact_name TEXT,
    contact_email TEXT,
    phone        TEXT,
    notes        TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY,
    order_no     TEXT NOT NULL UNIQUE,
    company_id   INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    po_number    TEXT,
    description  TEXT,
    status       TEXT NOT NULL,
    value        REAL DEFAULT 0,
    currency     TEXT DEFAULT 'USD',
    order_date   TEXT,
    promise_date TEXT,
    ship_date    TEXT,
    owner        TEXT,
    priority     TEXT DEFAULT 'NORMAL',
    notes        TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_company ON orders(company_id);
CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_promise ON orders(promise_date);

CREATE TABLE IF NOT EXISTS status_history (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    note        TEXT,
    changed_by  TEXT,
    changed_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_order ON status_history(order_id, changed_at);

CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY,
    order_id     INTEGER REFERENCES orders(id) ON DELETE CASCADE,
    company_id   INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    stored_name  TEXT NOT NULL UNIQUE,
    kind         TEXT,
    mime         TEXT,
    size         INTEGER,
    sha256       TEXT,
    content_text TEXT,
    extract_note TEXT,
    uploaded_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_docs_order   ON documents(order_id);
CREATE INDEX IF NOT EXISTS idx_docs_company ON documents(company_id);
CREATE INDEX IF NOT EXISTS idx_docs_sha     ON documents(sha256);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Full-text indexes. Kept as plain (non-content) FTS tables and refreshed by
-- the application, which is simpler to reason about than external-content
-- tables when rows are edited from several places.
CREATE VIRTUAL TABLE IF NOT EXISTS orders_fts USING fts5(
    order_no, po_number, company, description, notes, owner,
    order_id UNINDEXED,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    filename, body,
    doc_id UNINDEXED,
    tokenize = 'unicode61'
);
"""


def init_db() -> None:
    """Create the schema if it is not there yet, and tidy known bad values."""
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        repair_dates(conn)


def repair_dates(conn: sqlite3.Connection) -> int:
    """Clear date columns holding the text "None".

    Early versions turned a missing date into the string "None", which then
    showed up in the blotter and stopped the overdue check working. Absent
    dates belong in the database as NULL.
    """
    fixed = 0
    for column in ("order_date", "promise_date", "ship_date"):
        cursor = conn.execute(
            f"UPDATE orders SET {column} = NULL "
            f"WHERE {column} IN ('None', 'none', '')"
        )
        fixed += cursor.rowcount or 0
    return fixed


# --- Full-text maintenance -------------------------------------------------

def reindex_order(conn: sqlite3.Connection, order_id: int) -> None:
    """Rewrite the search row for one order."""
    conn.execute("DELETE FROM orders_fts WHERE order_id = ?", (order_id,))
    row = conn.execute(
        """SELECT o.id, o.order_no, o.po_number, o.description, o.notes, o.owner,
                  c.name AS company
           FROM orders o JOIN companies c ON c.id = o.company_id
           WHERE o.id = ?""",
        (order_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute(
        """INSERT INTO orders_fts(order_no, po_number, company, description,
                                  notes, owner, order_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            row["order_no"] or "",
            row["po_number"] or "",
            row["company"] or "",
            row["description"] or "",
            row["notes"] or "",
            row["owner"] or "",
            order_id,
        ),
    )


def reindex_document(conn: sqlite3.Connection, doc_id: int) -> None:
    """Rewrite the search row for one document."""
    conn.execute("DELETE FROM documents_fts WHERE doc_id = ?", (doc_id,))
    row = conn.execute(
        "SELECT id, filename, content_text FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute(
        "INSERT INTO documents_fts(filename, body, doc_id) VALUES (?, ?, ?)",
        (row["filename"] or "", row["content_text"] or "", doc_id),
    )


def rebuild_search_index() -> None:
    """Rebuild both FTS tables from scratch. Safe to run at any time."""
    conn = connect()
    with conn:
        conn.execute("DELETE FROM orders_fts")
        conn.execute("DELETE FROM documents_fts")
        for (oid,) in conn.execute("SELECT id FROM orders").fetchall():
            reindex_order(conn, oid)
        for (did,) in conn.execute("SELECT id FROM documents").fetchall():
            reindex_document(conn, did)
