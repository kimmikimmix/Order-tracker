"""SQLite storage: schema, connections and full-text search wiring.

One file on disk holds everything structured; the documents themselves live
beside it under data/documents/. Copy the data/ folder and you have copied
the entire system.
"""

import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone

from . import config, drives

_local = threading.local()

SCHEMA_VERSION = 5


def now() -> str:
    """UTC timestamp in a sortable, SQLite-friendly form."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


_network = None


def on_network() -> bool:
    """Is the data folder on a network share? Worked out once."""
    global _network
    if _network is None:
        _network = drives.describe(config.DATA_DIR)["network"]
    return _network


def forget_network() -> None:
    """Re-check the drive. Used after the data folder moves, and by tests."""
    global _network
    _network = None


class StorageError(Exception):
    """The data folder exists but cannot hold the database."""


def probe_folder(folder) -> dict:
    """Find out what a folder will actually take, rather than guessing.

    "Unable to open database file" covers several very different problems.
    Distinguishing them takes two seconds and turns a list of possible
    causes into a single answer.
    """
    folder = Path(folder)
    found = {
        "folder": str(folder),
        "exists": False,
        "made": "",
        "file_ok": False,
        "file_error": "",
        "db_ok": False,
        "db_error": "",
        "network": False,
        "where": "",
    }

    place = drives.describe(folder)
    found["network"] = place["network"]
    found["where"] = place["where"]

    try:
        folder.mkdir(parents=True, exist_ok=True)
        found["exists"] = folder.is_dir()
    except OSError as exc:
        found["made"] = str(exc)
        return found

    probe = folder / ".write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        found["file_ok"] = True
    except OSError as exc:
        found["file_error"] = str(exc)
        return found

    db_probe = folder / ".db-probe"
    try:
        conn = sqlite3.connect(db_probe, timeout=5)
        conn.execute("CREATE TABLE IF NOT EXISTS probe (x INTEGER)")
        conn.close()
        found["db_ok"] = True
    except sqlite3.Error as exc:
        found["db_error"] = str(exc)
    try:
        db_probe.unlink(missing_ok=True)
    except OSError:
        pass
    return found


CONTROLLED_FOLDER_ADVICE = (
    "Ordinary files can be written there, but a database cannot. On Windows\n"
    "that means something is watching the folder and refusing the kind of\n"
    "file SQLite makes. In order of likelihood:\n"
    "\n"
    "  1. Controlled folder access — Windows Security > Virus & threat\n"
    "     protection > Ransomware protection > Controlled folder access.\n"
    "     Either turn it off, or Allow an app: add python.exe.\n"
    "  2. Antivirus doing the same thing under its own name.\n"
    "  3. OneDrive holding the folder online-only. Right-click it and\n"
    "     choose Always keep on this device."
)

NO_FILES_ADVICE = (
    "Files cannot be written there at all, so this is a permission on the\n"
    "folder rather than anything about databases. Pick somewhere you own."
)


def _explain_open_failure(exc: Exception) -> "StorageError":
    """Turn SQLite's terse refusal into something actionable.

    The folder is probed here and now, so the message can say what is
    actually wrong instead of listing everything it might be.
    """
    found = probe_folder(config.DATA_DIR)
    lines = [f"Could not open the database at:\n    {config.DB_PATH}",
             f"SQLite said: {exc}"]

    if found["made"]:
        lines.append(f"The folder itself could not be created:\n    "
                     f"{found['made']}")
    elif not found["file_ok"]:
        lines.append(f"Writing a plain file there fails too:\n    "
                     f"{found['file_error']}\n\n{NO_FILES_ADVICE}")
    elif found["db_ok"]:
        lines.append(
            "Oddly, a test database CAN be created there now. Something had\n"
            "the folder locked a moment ago — antivirus scanning it, or a\n"
            "copy of Order Tracker still shutting down. Try again.")
    else:
        lines.append(f"A test database is refused as well:\n    "
                     f"{found['db_error']}\n\n{CONTROLLED_FOLDER_ADVICE}")

    if found["network"]:
        lines.append(
            f"That folder is also on {found['where']}, a network drive.\n"
            "SQLite cannot be relied on over one — keep the data on this\n"
            "machine and back up to the share instead.")

    lines.append(
        "The quickest way past all of it is to keep your orders somewhere\n"
        "unrestricted. This remembers the choice, so you only do it once:\n"
        '\n    py setup.py --folder "%LOCALAPPDATA%\\OrderTracker"\n\n'
        "For a full report of what was tried:\n    py doctor.py")

    return StorageError("\n\n".join(lines))


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
        # Write-ahead logging is faster and safer, but it needs shared memory
        # that a network share cannot provide — SQLite says plainly that WAL
        # does not work over a network filesystem. On one, fall back to the
        # old rollback journal and make every write wait for the disk, which
        # is as careful as it can be made there.
        network = on_network()
        # Changing journal mode needs a moment of exclusive access, which a
        # busy or networked database may refuse. Getting the preferred mode
        # is worth asking for and never worth failing to start over.
        try:
            conn.execute("PRAGMA journal_mode=" + ("DELETE" if network else "WAL"))
        except sqlite3.OperationalError:
            pass
        conn.execute("PRAGMA synchronous=" + ("FULL" if network else "NORMAL"))
        conn.execute("PRAGMA foreign_keys=ON")
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

-- The PCB build specification and cost sheet for an order. One row per
-- order, created the moment anything on the spec form is filled in. Kept
-- apart from orders so the blotter stays quick to read and so an order with
-- no engineering detail costs nothing to store.
CREATE TABLE IF NOT EXISTS order_specs (
    order_id          INTEGER PRIMARY KEY
                      REFERENCES orders(id) ON DELETE CASCADE,

    -- quotation
    quote_date        TEXT,
    quote_ref         TEXT,
    contact_person    TEXT,

    -- what it is
    product_type      TEXT,
    ipc_class         TEXT,
    ccl_material      TEXT,

    -- size and panelisation, all in millimetres
    pcb_x_mm          REAL,
    pcb_y_mm          REAL,
    array_x_mm        REAL,
    array_y_mm        REAL,
    ups               INTEGER,
    panel_code        TEXT,

    -- finish
    surface_finish    TEXT,
    finish_thickness  TEXT,

    -- stack-up
    layers            INTEGER,
    thickness_mm      REAL,
    thickness_tol_pct REAL,
    copper_outer_oz   REAL,
    copper_inner_oz   REAL,

    impedance         INTEGER DEFAULT 0,
    impedance_note    TEXT,

    -- drilling
    min_drill_mm      REAL,
    min_drill_count   INTEGER,
    total_drill_count INTEGER,
    bvh               INTEGER DEFAULT 0,
    bvh_layers        TEXT,

    options           TEXT,
    qty               INTEGER,
    lots              INTEGER,

    -- cost sheet, every figure entered in won
    pcb_total_krw     REAL,
    pcb_unit_krw      REAL,
    turnkey           INTEGER DEFAULT 0,
    smt_total_krw     REAL,
    smt_unit_krw      REAL,
    stencil_count     INTEGER,
    stencil_unit_krw  REAL,
    parts_total_krw   REAL,
    parts_unit_krw    REAL,

    -- the rates this quote was priced at, kept so an old quote still adds up
    inflation_on      INTEGER DEFAULT 0,
    inflation_rate    REAL,
    markup_on         INTEGER DEFAULT 0,
    markup_pct        REAL,
    fx_rate           REAL,

    updated_at        TEXT NOT NULL
);

-- Email that has been uploaded and read. The mail itself is kept as an
-- ordinary document, so it is searchable and downloadable like anything
-- else; this table holds what was worked out about it — who sent it, what
-- it is about, and which order it was filed against.
CREATE TABLE IF NOT EXISTS emails (
    id           INTEGER PRIMARY KEY,
    doc_id       INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    order_id     INTEGER REFERENCES orders(id) ON DELETE SET NULL,
    company_id   INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    case_id      INTEGER,
    direction    TEXT DEFAULT 'IN',
    message_key  TEXT UNIQUE,
    sent_at      TEXT,
    from_name    TEXT,
    from_email   TEXT,
    from_domain  TEXT,
    to_addrs     TEXT,
    subject      TEXT,
    summary      TEXT,
    keywords     TEXT,
    category     TEXT,
    refs         TEXT,
    confidence   REAL DEFAULT 0,
    matched_on   TEXT,
    needs_review INTEGER DEFAULT 1,
    attachments  INTEGER DEFAULT 0,
    filed_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emails_order   ON emails(order_id);
CREATE INDEX IF NOT EXISTS idx_emails_company ON emails(company_id);
CREATE INDEX IF NOT EXISTS idx_emails_sender  ON emails(from_email);
CREATE INDEX IF NOT EXISTS idx_emails_review  ON emails(needs_review);

-- A dispute, a defect claim, or anything else that needs chasing on an
-- order. The case holds the position; case_entries holds every call, mail
-- and action taken about it, which is what actually settles an argument
-- six months later.
CREATE TABLE IF NOT EXISTS cases (
    id           INTEGER PRIMARY KEY,
    ref          TEXT NOT NULL UNIQUE,
    order_id     INTEGER REFERENCES orders(id) ON DELETE CASCADE,
    company_id   INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    kind         TEXT NOT NULL,
    severity     TEXT NOT NULL,
    status       TEXT NOT NULL,
    opened_at    TEXT NOT NULL,
    due_at       TEXT,
    closed_at    TEXT,
    qty_affected INTEGER,
    claim_krw    REAL,
    lot_ref      TEXT,
    detail       TEXT,
    root_cause   TEXT,
    resolution   TEXT,
    owner        TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cases_order  ON cases(order_id);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);

CREATE TABLE IF NOT EXISTS case_entries (
    id           INTEGER PRIMARY KEY,
    case_id      INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,
    happened_at  TEXT NOT NULL,
    who          TEXT,
    summary      TEXT NOT NULL,
    detail       TEXT,
    doc_id       INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    email_id     INTEGER REFERENCES emails(id) ON DELETE SET NULL,
    follow_up_at TEXT,
    done_at      TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_case ON case_entries(case_id, happened_at);
CREATE INDEX IF NOT EXISTS idx_entries_due  ON case_entries(follow_up_at);

-- A folder for one running conversation with a customer: an enquiry, a
-- request, a sample, a complaint — anything that is not yet an order and
-- has to be chased. The topic is the headline; the summary says what they
-- want; the situation says where it stands right now. Emails received and
-- sent are filed inside it, and its log carries the actions.
CREATE TABLE IF NOT EXISTS threads (
    id           INTEGER PRIMARY KEY,
    ref          TEXT NOT NULL UNIQUE,
    company_id   INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    order_id     INTEGER REFERENCES orders(id) ON DELETE SET NULL,
    topic        TEXT NOT NULL,
    summary      TEXT,
    situation    TEXT,
    kind         TEXT,
    status       TEXT NOT NULL,
    priority     TEXT DEFAULT 'NORMAL',
    value_usd    REAL,
    opened_at    TEXT NOT NULL,
    follow_up_at TEXT,
    closed_at    TEXT,
    owner        TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_threads_company ON threads(company_id);
CREATE INDEX IF NOT EXISTS idx_threads_status  ON threads(status);
CREATE INDEX IF NOT EXISTS idx_threads_follow  ON threads(follow_up_at);

CREATE TABLE IF NOT EXISTS thread_entries (
    id           INTEGER PRIMARY KEY,
    thread_id    INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,
    happened_at  TEXT NOT NULL,
    who          TEXT,
    summary      TEXT NOT NULL,
    detail       TEXT,
    doc_id       INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    email_id     INTEGER REFERENCES emails(id) ON DELETE SET NULL,
    follow_up_at TEXT,
    done_at      TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_thread_entries ON thread_entries(thread_id, happened_at);
CREATE INDEX IF NOT EXISTS idx_thread_due     ON thread_entries(follow_up_at);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Full-text indexes. Kept as plain (non-content) FTS tables and refreshed by
-- the application, which is simpler to reason about than external-content
-- tables when rows are edited from several places.
CREATE VIRTUAL TABLE IF NOT EXISTS orders_fts USING fts5(
    order_no, po_number, company, product, description, notes, owner,
    order_id UNINDEXED,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    filename, body,
    doc_id UNINDEXED,
    tokenize = 'unicode61'
);
"""


# Columns added after the first release. SQLite has no "ADD COLUMN IF NOT
# EXISTS", so each is applied only when the table is missing it.
LATER_COLUMNS = {
    "orders": [
        ("product_code", "TEXT"),   # the part number the board is known by
        ("product_name", "TEXT"),   # or the name, when there is no number
    ],
    "emails": [
        ("thread_id", "INTEGER"),   # the folder it was filed into, if any
    ],
    "companies": [
        ("country", "TEXT"),      # two-letter code, e.g. KR, DE, US
        ("city", "TEXT"),
        ("lat", "REAL"),
        ("lon", "REAL"),
        ("timezone", "TEXT"),     # IANA name, e.g. Asia/Seoul
    ],
}


def _add_missing_columns(conn) -> list[str]:
    """Bring an older database up to the current set of columns."""
    added = []
    for table, columns in LATER_COLUMNS.items():
        have = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, kind in columns:
            if name in have:
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
            added.append(f"{table}.{name}")
    return added


def _stale_search_index(conn) -> bool:
    """True when the search index was built before a column existed.

    An FTS table cannot have a column added to it, so the only way to
    start indexing something new is to throw the index away and build it
    again. It holds nothing that is not in the orders themselves, so
    losing it costs a second, not any data.
    """
    try:
        columns = {row["name"] for row in conn.execute(
            "PRAGMA table_info(orders_fts)")}
    except sqlite3.Error:
        return False
    return bool(columns) and "product" not in columns


def init_db() -> None:
    """Create the schema if it is not there yet, and tidy known bad values."""
    conn = connect()
    rebuild = _stale_search_index(conn)
    with conn:
        if rebuild:
            conn.execute("DROP TABLE IF EXISTS orders_fts")
        conn.executescript(SCHEMA)
        _add_missing_columns(conn)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        repair_dates(conn)
    if rebuild:
        rebuild_search_index()


def touch(conn, key: str = "last_saved") -> str:
    """Record that something changed, so the app can show when it last did."""
    stamp = now()
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, stamp),
    )
    return stamp


def meta_get(key: str, default=None):
    try:
        row = connect().execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
    except Exception:
        return default
    return row["value"] if row else default


def meta_set(key: str, value) -> None:
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


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
        """SELECT o.id, o.order_no, o.po_number, o.product_code, o.product_name,
                  o.description, o.notes, o.owner, c.name AS company
           FROM orders o JOIN companies c ON c.id = o.company_id
           WHERE o.id = ?""",
        (order_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute(
        """INSERT INTO orders_fts(order_no, po_number, company, product,
                                  description, notes, owner, order_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row["order_no"] or "",
            row["po_number"] or "",
            row["company"] or "",
            " ".join(filter(None, (row["product_code"], row["product_name"]))),
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
