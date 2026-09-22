"""Order and company logic: reading, writing, alerting and searching."""

import datetime
import re
import sqlite3

from . import config, db, geo, pcb, prefs

ORDER_FIELDS = (
    "order_no", "company_id", "po_number", "description", "status", "value",
    "currency", "order_date", "promise_date", "ship_date", "owner", "priority",
    "notes",
)

SORTABLE = {
    "order_no": "o.order_no",
    "company": "c.name",
    "po_number": "o.po_number",
    "status": "o.status",
    "value": "o.value",
    "order_date": "o.order_date",
    "promise_date": "o.promise_date",
    "owner": "o.owner",
    "updated_at": "o.updated_at",
    "priority": "o.priority",
}


def today() -> datetime.date:
    return datetime.date.today()


# Formats that mean the same thing everywhere, tried first.
_UNAMBIGUOUS = ("%Y-%m-%d", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y", "%b %d %Y",
                "%d-%B-%Y", "%Y%m%d")
# Slash and dot forms, whose reading depends on config.DATE_INPUT_ORDER.
_MDY = ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y")
_DMY = ("%d/%m/%Y", "%d/%m/%y", "%d.%m.%Y", "%d-%m-%Y")


def _parse_date(value):
    """Read a date written in any of the forms people actually use."""
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value

    text = " ".join(str(value).replace(",", " ").split())
    if not text:
        return None
    # Drop a trailing clock time, so stored timestamps parse as their date.
    text = re.sub(r"[ T]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?Z?$", "", text).strip()
    if not text:
        return None

    ambiguous = _MDY + _DMY if config.DATE_INPUT_ORDER.upper() == "MDY" else _DMY + _MDY
    for fmt in _UNAMBIGUOUS + ambiguous:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def normalise_date(value) -> str | None:
    """Accept the date formats people actually paste in; store one of them.

    A date we cannot read is kept as typed rather than thrown away, but an
    absent one stays absent — it must never become the text "None".
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parsed = _parse_date(text)
    return parsed.isoformat() if parsed else text


# --- Alerts ----------------------------------------------------------------

def stage_index(status: str) -> int:
    try:
        return config.PIPELINE.index(status)
    except ValueError:
        return -1


def alerts_for(row, doc_kinds=()) -> list[str]:
    """Which flags an order raises right now, worst first."""
    status = row["status"]
    if status in config.TERMINAL_STATUSES:
        return []

    flags = []
    if status == "ON HOLD":
        flags.append("ON HOLD")

    promise = _parse_date(row["promise_date"])
    if promise and status not in ("DELIVERED", "INVOICED", "SHIPPED"):
        days = (promise - today()).days
        if days < 0:
            flags.append("OVERDUE")
        elif days <= int(prefs.get('due_soon_days')):
            flags.append("DUE SOON")

    updated = _parse_date(row["updated_at"])
    if updated and status != "ON HOLD":
        if (today() - updated).days >= int(prefs.get('stalled_days')):
            flags.append("STALLED")

    required_from = stage_index(config.PO_REQUIRED_FROM)
    if required_from >= 0 and stage_index(status) >= required_from:
        if "PO" not in set(doc_kinds):
            flags.append("NO PO")

    return flags


# --- Reads -----------------------------------------------------------------

def _decorate(rows, conn) -> list[dict]:
    """Attach document counts and alert flags to a batch of order rows."""
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    placeholders = ",".join("?" * len(ids))
    kinds: dict[int, list[str]] = {}
    counts: dict[int, int] = {}
    for doc in conn.execute(
        f"SELECT order_id, kind FROM documents WHERE order_id IN ({placeholders})", ids
    ):
        counts[doc["order_id"]] = counts.get(doc["order_id"], 0) + 1
        kinds.setdefault(doc["order_id"], []).append(doc["kind"] or "")

    out = []
    for row in rows:
        item = dict(row)
        item["doc_count"] = counts.get(row["id"], 0)
        item["alerts"] = alerts_for(row, kinds.get(row["id"], []))
        promise = _parse_date(row["promise_date"])
        item["days_to_promise"] = (promise - today()).days if promise else None
        out.append(item)
    return out


def list_orders(status=None, company_id=None, owner=None, alert=None,
                query=None, sort="promise_date", direction="asc",
                include_closed=True, limit=1000) -> list[dict]:
    conn = db.connect()
    where, params = [], []

    if status:
        where.append("o.status = ?")
        params.append(status)
    if company_id:
        where.append("o.company_id = ?")
        params.append(company_id)
    if owner:
        where.append("o.owner = ?")
        params.append(owner)
    if not include_closed:
        marks = ",".join("?" * len(config.TERMINAL_STATUSES))
        where.append(f"o.status NOT IN ({marks})")
        params.extend(sorted(config.TERMINAL_STATUSES))
    if query:
        ids = search_order_ids(query)
        if not ids:
            return []
        where.append(f"o.id IN ({','.join('?' * len(ids))})")
        params.extend(ids)

    order_by = SORTABLE.get(sort, "o.promise_date")
    direction = "DESC" if str(direction).lower().startswith("d") else "ASC"
    # Orders with no promise date should not crowd the top of a date sort.
    null_rule = f"CASE WHEN {order_by} IS NULL OR {order_by} = '' THEN 1 ELSE 0 END"

    sql = f"""
        SELECT o.*, c.name AS company, c.code AS company_code
        FROM orders o JOIN companies c ON c.id = o.company_id
        {'WHERE ' + ' AND '.join(where) if where else ''}
        ORDER BY {null_rule}, {order_by} {direction}, o.order_no
        LIMIT ?
    """
    rows = conn.execute(sql, (*params, limit)).fetchall()
    result = _decorate(rows, conn)

    if alert:
        wanted = alert.upper()
        result = [r for r in result if wanted in r["alerts"]]
    return result


def get_order(order_id: int) -> dict | None:
    conn = db.connect()
    row = conn.execute(
        """SELECT o.*, c.name AS company, c.code AS company_code,
                  c.contact_name, c.contact_email, c.phone
           FROM orders o JOIN companies c ON c.id = o.company_id
           WHERE o.id = ?""",
        (order_id,),
    ).fetchone()
    if row is None:
        return None

    item = _decorate([row], conn)[0]
    item["spec"] = get_spec(order_id)
    item["history"] = [
        dict(h) for h in conn.execute(
            """SELECT * FROM status_history WHERE order_id = ?
               ORDER BY changed_at DESC, id DESC""",
            (order_id,),
        )
    ]
    item["documents"] = [
        dict(d) for d in conn.execute(
            """SELECT id, filename, kind, mime, size, uploaded_at, extract_note,
                      length(COALESCE(content_text, '')) AS text_len
               FROM documents WHERE order_id = ?
               ORDER BY uploaded_at DESC""",
            (order_id,),
        )
    ]
    return item


# --- Writes ----------------------------------------------------------------

class OrderError(Exception):
    """A problem the user needs to see and fix."""


def _company_id_for(conn, data) -> int:
    """Resolve company_id, creating the company when only a name is given."""
    if data.get("company_id"):
        return int(data["company_id"])
    name = (data.get("company") or "").strip()
    if not name:
        raise OrderError("A company is required.")
    row = conn.execute(
        "SELECT id FROM companies WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO companies(name, created_at) VALUES (?, ?)", (name, db.now())
    )
    return cur.lastrowid


def create_order(data: dict, actor: str = "") -> int:
    conn = db.connect()
    order_no = (data.get("order_no") or "").strip()
    if not order_no:
        raise OrderError("An order number is required.")
    status = (data.get("status") or config.PIPELINE[0]).strip().upper()
    if status not in config.ALL_STATUSES:
        raise OrderError(f"Unknown status '{status}'.")

    stamp = db.now()
    with conn:
        company_id = _company_id_for(conn, data)
        try:
            cur = conn.execute(
                """INSERT INTO orders
                   (order_no, company_id, po_number, description, status, value,
                    currency, order_date, promise_date, ship_date, owner,
                    priority, notes, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    order_no, company_id,
                    (data.get("po_number") or "").strip() or None,
                    data.get("description") or None,
                    status,
                    _as_number(data.get("value")),
                    (data.get("currency") or "USD").strip().upper()[:8],
                    normalise_date(data.get("order_date")),
                    normalise_date(data.get("promise_date")),
                    normalise_date(data.get("ship_date")),
                    (data.get("owner") or "").strip() or None,
                    (data.get("priority") or "NORMAL").strip().upper(),
                    data.get("notes") or None,
                    stamp, stamp,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise OrderError(f"Order '{order_no}' already exists.") from exc
        order_id = cur.lastrowid
        conn.execute(
            """INSERT INTO status_history(order_id, from_status, to_status, note,
                                          changed_by, changed_at)
               VALUES (?, NULL, ?, 'order created', ?, ?)""",
            (order_id, status, actor or None, stamp),
        )
        db.reindex_order(conn, order_id)
        db.touch(conn)
    if data.get("spec"):
        save_spec(order_id, data["spec"])
    return order_id


def update_order(order_id: int, data: dict, actor: str = "", note: str = "") -> None:
    conn = db.connect()
    current = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if current is None:
        raise OrderError("That order no longer exists.")

    updates, params = [], []
    new_status = None

    for field in ORDER_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field == "company_id":
            continue
        if field == "status":
            value = (value or "").strip().upper()
            if value not in config.ALL_STATUSES:
                raise OrderError(f"Unknown status '{value}'.")
            if value != current["status"]:
                new_status = value
        elif field == "value":
            value = _as_number(value)
        elif field in ("order_date", "promise_date", "ship_date"):
            value = normalise_date(value)
        elif isinstance(value, str):
            value = value.strip() or None
        updates.append(f"{field} = ?")
        params.append(value)

    if data.get("company") or data.get("company_id"):
        with conn:
            company_id = _company_id_for(conn, data)
        if company_id != current["company_id"]:
            updates.append("company_id = ?")
            params.append(company_id)

    if not updates:
        return

    stamp = db.now()
    updates.append("updated_at = ?")
    params.append(stamp)
    params.append(order_id)

    with conn:
        try:
            conn.execute(f"UPDATE orders SET {', '.join(updates)} WHERE id = ?", params)
        except sqlite3.IntegrityError as exc:
            raise OrderError("Another order already uses that order number.") from exc
        if new_status:
            conn.execute(
                """INSERT INTO status_history(order_id, from_status, to_status,
                                              note, changed_by, changed_at)
                   VALUES (?,?,?,?,?,?)""",
                (order_id, current["status"], new_status, note or None,
                 actor or None, stamp),
            )
        elif note:
            conn.execute(
                """INSERT INTO status_history(order_id, from_status, to_status,
                                              note, changed_by, changed_at)
                   VALUES (?,?,?,?,?,?)""",
                (order_id, current["status"], current["status"], note,
                 actor or None, stamp),
            )
        db.reindex_order(conn, order_id)
        db.touch(conn)


def delete_order(order_id: int) -> None:
    """Remove an order and every document filed against it."""
    from . import documents

    conn = db.connect()
    stored = [
        r["stored_name"] for r in conn.execute(
            "SELECT stored_name FROM documents WHERE order_id = ?", (order_id,)
        )
    ]
    doc_ids = [
        r["id"] for r in conn.execute(
            "SELECT id FROM documents WHERE order_id = ?", (order_id,)
        )
    ]
    with conn:
        conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        conn.execute("DELETE FROM orders_fts WHERE order_id = ?", (order_id,))
        for did in doc_ids:
            conn.execute("DELETE FROM documents_fts WHERE doc_id = ?", (did,))
        db.touch(conn)
    for name in stored:
        documents.remove_file(name)


def _as_number(value) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace(",", "").replace("$", "").replace("€", "")
    cleaned = cleaned.replace("£", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# --- Companies -------------------------------------------------------------

def list_companies() -> list[dict]:
    conn = db.connect()
    rows = conn.execute(
        """SELECT c.*,
                  (SELECT COUNT(*) FROM orders o WHERE o.company_id = c.id) AS order_count,
                  (SELECT COUNT(*) FROM orders o WHERE o.company_id = c.id
                     AND o.status NOT IN ('PAID','CANCELLED')) AS open_count,
                  (SELECT COALESCE(SUM(o.value), 0) FROM orders o
                     WHERE o.company_id = c.id AND o.status NOT IN ('PAID','CANCELLED')) AS open_value
           FROM companies c ORDER BY c.name"""
    ).fetchall()
    return [dict(r) for r in rows]


def save_company(data: dict) -> int:
    conn = db.connect()
    data = _with_location(dict(data))
    company_id = data.get("id")
    fields = ("name", "code", "contact_name", "contact_email", "phone", "notes",
              "country", "city", "lat", "lon", "timezone")
    with conn:
        if company_id:
            sets = [f"{f} = ?" for f in fields if f in data]
            if sets:
                conn.execute(
                    f"UPDATE companies SET {', '.join(sets)} WHERE id = ?",
                    [*(data[f] for f in fields if f in data), company_id],
                )
                db.touch(conn)
            return int(company_id)
        name = (data.get("name") or "").strip()
        if not name:
            raise OrderError("A company name is required.")
        cur = conn.execute(
            """INSERT INTO companies(name, code, contact_name, contact_email,
                                     phone, notes, country, city, lat, lon,
                                     timezone, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, data.get("code"), data.get("contact_name"),
             data.get("contact_email"), data.get("phone"), data.get("notes"),
             data.get("country"), data.get("city"), data.get("lat"),
             data.get("lon"), data.get("timezone"), db.now()),
        )
        db.touch(conn)
        return cur.lastrowid


# --- Search ----------------------------------------------------------------

def fts_query(text: str) -> str:
    """Turn what a person typed into something FTS5 will accept.

    Bare words become prefix matches, so typing half an order number finds it.
    Quoted phrases are kept whole.
    """
    text = (text or "").strip()
    if not text:
        return ""
    if '"' in text:
        return text
    terms = []
    for raw in text.split():
        token = "".join(ch if ch.isalnum() else " " for ch in raw).split()
        if not token:
            continue
        # Hyphenated references like PO-2026-448 tokenise into parts; keep them
        # together as a phrase so the whole reference has to match.
        terms.append(f'"{" ".join(token)}"*' if len(token) > 1 else f"{token[0]}*")
    return " AND ".join(terms)


def search_order_ids(text: str) -> list[int]:
    query = fts_query(text)
    if not query:
        return []
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT order_id FROM orders_fts WHERE orders_fts MATCH ? LIMIT 500", (query,)
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r["order_id"] for r in rows]


def search(text: str, limit: int = 40) -> dict:
    """Search orders and document contents in one go."""
    query = fts_query(text)
    conn = db.connect()
    result = {"query": text, "orders": [], "documents": []}
    if not query:
        return result

    try:
        order_rows = conn.execute(
            """SELECT o.*, c.name AS company, c.code AS company_code
               FROM orders_fts f
               JOIN orders o ON o.id = f.order_id
               JOIN companies c ON c.id = o.company_id
               WHERE orders_fts MATCH ?
               ORDER BY rank LIMIT ?""",
            (query, limit),
        ).fetchall()
        result["orders"] = _decorate(order_rows, conn)

        doc_rows = conn.execute(
            """SELECT d.id, d.filename, d.kind, d.order_id, d.uploaded_at,
                      o.order_no, c.name AS company,
                      snippet(documents_fts, 1, '[', ']', ' … ', 14) AS snippet
               FROM documents_fts f
               JOIN documents d ON d.id = f.doc_id
               LEFT JOIN orders o ON o.id = d.order_id
               LEFT JOIN companies c ON c.id = d.company_id
               WHERE documents_fts MATCH ?
               ORDER BY rank LIMIT ?""",
            (query, limit),
        ).fetchall()
        result["documents"] = [dict(r) for r in doc_rows]
    except sqlite3.OperationalError as exc:
        result["error"] = f"search could not run: {exc}"
    return result


# --- Dashboard -------------------------------------------------------------

def dashboard() -> dict:
    conn = db.connect()
    rows = conn.execute(
        """SELECT o.*, c.name AS company, c.code AS company_code
           FROM orders o JOIN companies c ON c.id = o.company_id"""
    ).fetchall()
    decorated = _decorate(rows, conn)

    open_orders = [o for o in decorated if o["status"] not in config.TERMINAL_STATUSES]
    by_status = {}
    for order in decorated:
        by_status[order["status"]] = by_status.get(order["status"], 0) + 1

    by_company = {}
    for order in open_orders:
        entry = by_company.setdefault(
            order["company"], {"company": order["company"], "open": 0,
                               "value": 0.0, "alerts": 0}
        )
        entry["open"] += 1
        entry["value"] += order["value"] or 0
        entry["alerts"] += 1 if order["alerts"] else 0

    counts = {"OVERDUE": 0, "DUE SOON": 0, "STALLED": 0, "NO PO": 0, "ON HOLD": 0}
    for order in decorated:
        for flag in order["alerts"]:
            counts[flag] = counts.get(flag, 0) + 1

    doc_row = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()

    return {
        "total_orders": len(decorated),
        "open_orders": len(open_orders),
        "open_value": round(sum(o["value"] or 0 for o in open_orders), 2),
        "document_count": doc_row["n"],
        "company_count": len(conn.execute("SELECT id FROM companies").fetchall()),
        "alerts": counts,
        "by_status": [{"status": s, "count": by_status.get(s, 0)}
                      for s in config.ALL_STATUSES if by_status.get(s)],
        "by_company": sorted(by_company.values(), key=lambda e: -e["value"])[:12],
        "attention": sorted(
            [o for o in open_orders if o["alerts"]],
            key=lambda o: (0 if "OVERDUE" in o["alerts"] else 1,
                           o["days_to_promise"] if o["days_to_promise"] is not None else 999),
        )[:15],
    }


# --- Customer locations ----------------------------------------------------

def _as_coord(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _with_location(data: dict) -> dict:
    """Fill in position and time zone from the country, unless given."""
    country = (data.get("country") or "").strip().upper() or None
    if country:
        data["country"] = country
    if data.get("lat") in (None, "") or data.get("lon") in (None, ""):
        found = geo.locate(country, data.get("city"))
        if found:
            if not (data.get("city") or "").strip():
                data["city"] = found["city"]
            data["lat"] = found["lat"]
            data["lon"] = found["lon"]
            if not (data.get("timezone") or "").strip():
                data["timezone"] = found["timezone"]
    data["lat"] = _as_coord(data.get("lat"))
    data["lon"] = _as_coord(data.get("lon"))
    return data


def map_points() -> dict:
    """Customers that can be drawn on the world map, with their workload."""
    points = []
    for company in list_companies():
        lat, lon = _as_coord(company.get("lat")), _as_coord(company.get("lon"))
        if lat is None or lon is None:
            found = geo.locate(company.get("country"), company.get("city"))
            if not found:
                continue
            lat, lon = found["lat"], found["lon"]
            company = {**company, "timezone": company.get("timezone")
                       or found["timezone"], "city": company.get("city")
                       or found["city"]}
        points.append({
            "id": company["id"],
            "name": company["name"],
            "code": company.get("code") or "",
            "country": company.get("country") or "",
            "country_name": geo.country_name(company.get("country")),
            "city": company.get("city") or "",
            "lat": lat,
            "lon": lon,
            "timezone": company.get("timezone") or "UTC",
            "open": company.get("open_count") or 0,
            "value": company.get("open_value") or 0,
        })

    alerting = {}
    for order in list_orders(include_closed=False, limit=5000):
        if order["alerts"]:
            alerting[order["company"]] = alerting.get(order["company"], 0) + 1
    for point in points:
        point["alerts"] = alerting.get(point["name"], 0)

    home = geo.locate(prefs.get("home_country")) or geo.locate("KR")
    return {"points": sorted(points, key=lambda p: p["lon"]), "home": home,
            "unplaced": [c["name"] for c in list_companies()
                         if _as_coord(c.get("lat")) is None
                         and not geo.locate(c.get("country"), c.get("city"))]}


# --- Build specification and cost sheet ------------------------------------

def get_spec(order_id: int) -> dict:
    """The spec as stored, plus everything worked out from it."""
    conn = db.connect()
    row = conn.execute(
        "SELECT * FROM order_specs WHERE order_id = ?", (order_id,)
    ).fetchone()
    stored = {k: row[k] for k in row.keys()} if row else {}
    settings = prefs.load()
    spec = {name: stored.get(name) for name in pcb.FIELD_NAMES}
    return {
        "has_spec": bool(row),
        "updated_at": stored.get("updated_at"),
        "values": spec,
        "derived": pcb.derive(spec, settings),
        "cost": pcb.cost_sheet(spec, settings),
    }


def save_spec(order_id: int, data: dict) -> dict:
    """Write the spec for one order, creating the row on first use."""
    conn = db.connect()
    if conn.execute("SELECT 1 FROM orders WHERE id = ?", (order_id,)).fetchone() is None:
        raise OrderError("That order no longer exists.")

    values = pcb.clean(data or {})
    if not values:
        return get_spec(order_id)

    settings = prefs.load()
    # A quote keeps the rates it was priced at, so re-opening it later still
    # shows the figure the customer was given.
    for field, source in (("fx_rate", "fx_rate"),
                          ("inflation_rate", "inflation_rate"),
                          ("markup_pct", "markup_pct"),
                          ("stencil_unit_krw", "stencil_unit_krw")):
        if values.get(field) is None:
            existing = conn.execute(
                f"SELECT {field} FROM order_specs WHERE order_id = ?", (order_id,)
            ).fetchone()
            if existing and existing[field] is not None:
                values[field] = existing[field]
            else:
                values[field] = pcb.as_number(settings[source])

    stamp = db.now()
    columns = list(values)
    with conn:
        conn.execute(
            "INSERT INTO order_specs(order_id, updated_at) VALUES (?, ?) "
            "ON CONFLICT(order_id) DO NOTHING",
            (order_id, stamp),
        )
        conn.execute(
            f"UPDATE order_specs SET {', '.join(f'{c} = ?' for c in columns)}, "
            "updated_at = ? WHERE order_id = ?",
            [*(values[c] for c in columns), stamp, order_id],
        )
        db.touch(conn)
    return get_spec(order_id)


def reorder_sources(company_id=None, limit: int = 40) -> list[dict]:
    """Earlier orders whose specification can be copied into a new one."""
    conn = db.connect()
    where, params = ["s.order_id IS NOT NULL"], []
    if company_id:
        where.append("o.company_id = ?")
        params.append(int(company_id))
    rows = conn.execute(
        f"""SELECT o.id, o.order_no, o.description, o.order_date, c.name AS company,
                   s.product_type, s.layers, s.qty, s.lots, s.quote_ref,
                   s.pcb_total_krw, s.updated_at
            FROM order_specs s
            JOIN orders o ON o.id = s.order_id
            JOIN companies c ON c.id = o.company_id
            WHERE {' AND '.join(where)}
            ORDER BY s.updated_at DESC LIMIT ?""",
        (*params, limit),
    ).fetchall()
    return [dict(r) for r in rows]
