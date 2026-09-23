"""Disputes, defect claims, and every conversation they take to settle.

When a customer says a lot is faulty, what decides the outcome months later
is not the specification — it is whether you can show what was said, when,
by whom, and what you did about it. So a case is two things: a position
(what is wrong, how bad, how much is at stake, where it stands) and a log
(every call, mail, meeting and action, in order, each with a date).

A case always hangs off an order, because that is how the argument is
always framed: this lot, that PO. The log entries can carry a follow-up
date, which is what turns "I should chase them" into something the
dashboard can remind you about.
"""

import datetime
import re

from . import attach, chase, db, orders, prefs

OPEN_STATUSES = ("OPEN", "INVESTIGATING", "AWAITING CUSTOMER",
                 "AWAITING FACTORY")
SETTLED_STATUSES = ("RESOLVED", "CLOSED", "REJECTED")
# Cases nobody is working any more. A resolved case can still owe someone a
# credit note, so its outstanding actions keep showing; a closed one cannot.
ARCHIVED_STATUSES = ("CLOSED", "REJECTED")


class CaseError(Exception):
    """Something the user needs to see and fix."""


def _today() -> str:
    return datetime.date.today().isoformat()


def _plus_days(days) -> str:
    return (datetime.date.today() + datetime.timedelta(days=int(days))).isoformat()


def next_ref(conn=None) -> str:
    """The next case reference, counted within the year: C-2026-001."""
    conn = conn or db.connect()
    year = datetime.date.today().year
    prefix = f"C-{year}-"
    highest = 0
    for row in conn.execute("SELECT ref FROM cases WHERE ref LIKE ?",
                            (prefix + "%",)):
        match = re.search(r"(\d+)$", row["ref"] or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1:03d}"


def _clean(data: dict) -> dict:
    """Trim what came from the form and read its dates."""
    out = {}
    for key, value in (data or {}).items():
        out[key] = value.strip() if isinstance(value, str) else value
    for key in ("opened_at", "due_at", "closed_at"):
        if key in out:
            out[key] = orders.normalise_date(out[key])
    for key in ("qty_affected",):
        out[key] = _int(out.get(key))
    for key in ("claim_krw",):
        out[key] = _float(out.get(key))
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


def open_case(data: dict, actor: str = "") -> int:
    """Start a case against an order. Returns its id."""
    data = _clean(data)
    order_id = _int(data.get("order_id"))
    if not order_id:
        raise CaseError("A case belongs to an order — choose one first.")
    title = (data.get("title") or "").strip()
    if not title:
        raise CaseError("Give the case a title, so it can be recognised in a list.")

    conn = db.connect()
    order = conn.execute("SELECT id, company_id FROM orders WHERE id = ?",
                         (order_id,)).fetchone()
    if order is None:
        raise CaseError("That order no longer exists.")

    kinds = prefs.get("case_kinds") or ["OTHER"]
    severities = prefs.get("case_severities") or ["MEDIUM"]
    statuses = prefs.get("case_statuses") or ["OPEN"]

    kind = (data.get("kind") or kinds[0]).upper()
    severity = (data.get("severity") or "MEDIUM").upper()
    status = (data.get("status") or statuses[0]).upper()
    opened = data.get("opened_at") or _today()
    due = data.get("due_at") or _plus_days(prefs.get("case_due_days") or 7)

    stamp = db.now()
    with conn:
        cursor = conn.execute(
            """INSERT INTO cases(ref, order_id, company_id, title, kind,
                                 severity, status, opened_at, due_at,
                                 qty_affected, claim_krw, lot_ref, detail,
                                 root_cause, resolution, owner,
                                 created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (next_ref(conn), order_id, order["company_id"], title, kind,
             severity, status, opened, due,
             data.get("qty_affected"), data.get("claim_krw"),
             data.get("lot_ref"), data.get("detail"),
             data.get("root_cause"), data.get("resolution"),
             data.get("owner") or actor, stamp, stamp))
        case_id = cursor.lastrowid
        conn.execute(
            """INSERT INTO case_entries(case_id, kind, happened_at, who,
                                        summary, detail, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (case_id, "NOTE", opened, data.get("owner") or actor,
             f"Case opened: {title}", data.get("detail"), stamp))
        conn.execute("UPDATE orders SET updated_at = ? WHERE id = ?",
                     (stamp, order_id))
        db.touch(conn)
    return case_id


FIELDS = ("title", "kind", "severity", "status", "opened_at", "due_at",
          "closed_at", "qty_affected", "claim_krw", "lot_ref", "detail",
          "root_cause", "resolution", "owner")


def update_case(case_id: int, data: dict, actor: str = "") -> dict:
    """Change a case, logging a status move as an entry of its own."""
    data = _clean(data)
    conn = db.connect()
    case = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if case is None:
        raise CaseError("That case no longer exists.")

    changes = {k: data[k] for k in FIELDS if k in data}
    if "title" in changes and not changes["title"]:
        raise CaseError("A case cannot lose its title.")
    for key in ("kind", "severity", "status"):
        if changes.get(key):
            changes[key] = str(changes[key]).upper()

    moved_to = changes.get("status")
    if moved_to and moved_to in SETTLED_STATUSES and not changes.get("closed_at"):
        changes["closed_at"] = _today()
    if moved_to and moved_to in OPEN_STATUSES:
        changes["closed_at"] = None

    stamp = db.now()
    with conn:
        if changes:
            sets = ", ".join(f"{key} = ?" for key in changes)
            conn.execute(f"UPDATE cases SET {sets}, updated_at = ? WHERE id = ?",
                         [*changes.values(), stamp, case_id])
        if moved_to and moved_to != case["status"]:
            conn.execute(
                """INSERT INTO case_entries(case_id, kind, happened_at, who,
                                            summary, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (case_id, "DECISION", _today(), actor,
                 f"Status moved from {case['status']} to {moved_to}", stamp))
        db.touch(conn)
    return get_case(case_id)


ENTRY_FIELDS = chase.FIELDS
LOG = "case_entries"


def add_entry(case_id: int, data: dict) -> int:
    """Log one thing that happened, or one action to take."""
    try:
        return chase.add(LOG, case_id, data)
    except chase.LogError as exc:
        raise CaseError(str(exc)) from exc


def update_entry(entry_id: int, data: dict) -> None:
    """Correct an entry somebody logged earlier."""
    try:
        chase.update(LOG, entry_id, data)
    except chase.LogError as exc:
        raise CaseError(str(exc)) from exc


def complete_follow_up(entry_id: int, done: bool = True) -> None:
    """Tick off (or untick) a follow-up action."""
    chase.complete(LOG, entry_id, done)


def delete_entry(entry_id: int) -> None:
    chase.delete(LOG, entry_id)


def delete_case(case_id: int) -> None:
    attach.remove_all("cases", case_id)         # its own pictures
    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
        db.touch(conn)


# --- reading ---------------------------------------------------------------

def _decorate(row: dict) -> dict:
    """Add the flags a list wants: open or settled, and whether it is late."""
    item = dict(row)
    item["open"] = item["status"] not in SETTLED_STATUSES
    item["overdue"] = bool(
        item["open"] and item.get("due_at") and item["due_at"] < _today())
    item["age_days"] = _days_since(item.get("opened_at"))
    return item


def _days_since(value) -> int | None:
    parsed = orders.as_date(value)
    if parsed is None:
        return None
    return (datetime.date.today() - parsed).days


def get_case(case_id: int) -> dict | None:
    conn = db.connect()
    row = conn.execute(
        """SELECT k.*, o.order_no, o.po_number, o.status AS order_status,
                  o.product_code, o.product_name,
                  c.name AS company, c.contact_name, c.contact_email
           FROM cases k
           LEFT JOIN orders o ON o.id = k.order_id
           LEFT JOIN companies c ON c.id = k.company_id
           WHERE k.id = ?""", (case_id,)).fetchone()
    if row is None:
        return None
    item = _decorate(dict(row))
    item["attachments"] = attach.for_lines("cases", [case_id]).get(case_id, [])
    item["entries"] = chase.entries(LOG, case_id)
    item["open_actions"] = chase.open_actions(item["entries"])
    return item


def list_cases(status=None, order_id=None, company_id=None, open_only=False,
               query=None, limit=500) -> list[dict]:
    sql = ["""SELECT k.*, o.order_no, o.product_code, o.product_name,
                     c.name AS company,
                     (SELECT COUNT(*) FROM case_entries e
                       WHERE e.case_id = k.id) AS entries,
                     (SELECT COUNT(*) FROM case_entries e
                       WHERE e.case_id = k.id AND e.follow_up_at IS NOT NULL
                         AND e.done_at IS NULL) AS open_actions,
                     (SELECT MIN(e.follow_up_at) FROM case_entries e
                       WHERE e.case_id = k.id AND e.follow_up_at IS NOT NULL
                         AND e.done_at IS NULL) AS next_action_at
              FROM cases k
              LEFT JOIN orders o ON o.id = k.order_id
              LEFT JOIN companies c ON c.id = k.company_id"""]
    where, params = [], []
    if status:
        where.append("k.status = ?")
        params.append(str(status).upper())
    if open_only:
        marks = ",".join("?" * len(SETTLED_STATUSES))
        where.append(f"k.status NOT IN ({marks})")
        params.extend(SETTLED_STATUSES)
    if order_id:
        where.append("k.order_id = ?")
        params.append(order_id)
    if company_id:
        where.append("k.company_id = ?")
        params.append(company_id)
    if query:
        where.append("(k.title LIKE ? OR k.ref LIKE ? OR k.detail LIKE ? "
                     "OR o.order_no LIKE ? OR c.name LIKE ?)")
        params += [f"%{query}%"] * 5
    if where:
        sql.append("WHERE " + " AND ".join(where))
    sql.append("ORDER BY k.opened_at DESC, k.id DESC LIMIT ?")
    params.append(limit)
    return [_decorate(dict(row))
            for row in db.connect().execute(" ".join(sql), params)]


def follow_ups(within_days: int = 7, include_overdue: bool = True) -> list[dict]:
    """Actions that need doing, soonest first."""
    horizon = _plus_days(within_days)
    rows = db.connect().execute(
        """SELECT e.*, k.ref, k.title, k.status, k.severity, k.order_id,
                  o.order_no, o.product_code, o.product_name,
                  c.name AS company
           FROM case_entries e
           JOIN cases k ON k.id = e.case_id
           LEFT JOIN orders o ON o.id = k.order_id
           LEFT JOIN companies c ON c.id = k.company_id
           WHERE e.follow_up_at IS NOT NULL AND e.done_at IS NULL
             AND e.follow_up_at <= ?
             AND k.status NOT IN (%s)
           ORDER BY e.follow_up_at ASC, e.id ASC""" % ",".join(
            "?" * len(ARCHIVED_STATUSES)),
        (horizon, *ARCHIVED_STATUSES)).fetchall()
    today = _today()
    out = []
    for row in rows:
        item = dict(row)
        item["late"] = item["follow_up_at"] < today
        if item["late"] and not include_overdue:
            continue
        out.append(item)
    return out


def summary() -> dict:
    """Counts for the dashboard."""
    conn = db.connect()
    marks = ",".join("?" * len(SETTLED_STATUSES))
    open_count = conn.execute(
        f"SELECT COUNT(*) AS n FROM cases WHERE status NOT IN ({marks})",
        SETTLED_STATUSES).fetchone()["n"]
    today = _today()
    overdue = conn.execute(
        f"""SELECT COUNT(*) AS n FROM cases
            WHERE status NOT IN ({marks}) AND due_at IS NOT NULL AND due_at < ?""",
        (*SETTLED_STATUSES, today)).fetchone()["n"]
    live = ",".join("?" * len(ARCHIVED_STATUSES))
    actions = conn.execute(
        f"""SELECT COUNT(*) AS n FROM case_entries e JOIN cases k ON k.id = e.case_id
            WHERE e.follow_up_at IS NOT NULL AND e.done_at IS NULL
              AND k.status NOT IN ({live})""", ARCHIVED_STATUSES).fetchone()["n"]
    late_actions = conn.execute(
        f"""SELECT COUNT(*) AS n FROM case_entries e JOIN cases k ON k.id = e.case_id
            WHERE e.follow_up_at IS NOT NULL AND e.done_at IS NULL
              AND e.follow_up_at < ? AND k.status NOT IN ({live})""",
        (today, *ARCHIVED_STATUSES)).fetchone()["n"]
    claim = conn.execute(
        f"""SELECT COALESCE(SUM(claim_krw), 0) AS total FROM cases
            WHERE status NOT IN ({marks})""", SETTLED_STATUSES).fetchone()["total"]
    return {
        "open": open_count,
        "overdue": overdue,
        "open_actions": actions,
        "late_actions": late_actions,
        "claim_krw": claim or 0,
    }
