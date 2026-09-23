"""The order book as a picture: who, what, and what is attached to it.

A list is a good way to read a hundred orders and a poor way to see that
one customer has three disputes and nothing shipped. This builds the same
data as a small graph — a hub with its neighbours fanned around it — and
lets the front end draw it.

Three depths, each one hub and its neighbours:

    everything      one node per customer
    a customer      their orders, their folders, their disputes
    an order        where it is in the pipeline, and everything filed on it

Only the layer being looked at is built, so a thousand orders never become a
thousand nodes: you always see one hub and what hangs off it.
"""

from . import cases, config, db, documents, mail, orders, threads

# How a node is coloured. Worst wins.
TONE_LATE = "late"        # overdue, or a dispute past its answer date
TONE_DUE = "due"          # wants attention within the week
TONE_OPEN = "open"        # live, nothing wrong
TONE_DONE = "done"        # settled, paid, closed
TONE_IDLE = "idle"        # nothing running


def _node(node_id, kind, label, sub="", tone=TONE_OPEN, badges=(),
          drill="", link="", weight=1) -> dict:
    return {"id": node_id, "kind": kind, "label": label, "sub": sub,
            "tone": tone, "badges": list(badges), "drill": drill,
            "link": link, "weight": weight}


def _group(title, nodes, side="right") -> dict:
    return {"title": title, "side": side, "nodes": nodes}


# --- everything ------------------------------------------------------------

def overview() -> dict:
    """One node per customer, around a hub."""
    companies = orders.list_companies()
    folders = threads.counts_by_company()
    conn = db.connect()
    case_counts = {row["company_id"]: row["n"] for row in conn.execute(
        f"""SELECT company_id, COUNT(*) AS n FROM cases
            WHERE status NOT IN ({','.join('?' * len(cases.SETTLED_STATUSES))})
            GROUP BY company_id""", cases.SETTLED_STATUSES)}
    flagged = {}
    for order in orders.list_orders(include_closed=False, limit=2000):
        if order["alerts"]:
            flagged[order["company"]] = flagged.get(order["company"], 0) + 1

    nodes = []
    for company in companies:
        late = flagged.get(company["name"], 0)
        open_folders = folders.get(company["id"], {}).get("open", 0)
        open_cases = case_counts.get(company["id"], 0)
        if late or open_cases:
            tone = TONE_LATE
        elif company["open_count"] or open_folders:
            tone = TONE_OPEN
        else:
            tone = TONE_IDLE

        badges = []
        if company["open_count"]:
            badges.append(f"{company['open_count']} open")
        if open_folders:
            badges.append(f"{open_folders} folder(s)")
        if open_cases:
            badges.append(f"{open_cases} dispute(s)")
        nodes.append(_node(
            f"company/{company['id']}", "COMPANY", company["name"],
            sub=" · ".join(filter(None, (
                ", ".join(filter(None, (company.get("city"),
                                        company.get("country")))),
                f"{company['order_count']} order(s)"))),
            tone=tone, badges=badges, drill=f"company/{company['id']}",
            weight=max(1, company["open_count"])))

    nodes.sort(key=lambda row: (row["tone"] != TONE_LATE, row["label"]))
    return {
        "hub": _node("all", "ROOT", "YOUR CUSTOMERS",
                     sub=f"{len(companies)} on file"),
        "groups": [_group("CUSTOMERS", nodes, side="both")],
        "detail": {"kind": "ROOT", "title": "YOUR CUSTOMERS",
                   "rows": [("CUSTOMERS", str(len(companies))),
                            ("OPEN ORDERS",
                             str(sum(c["open_count"] for c in companies))),
                            ("WITH SOMETHING FLAGGED", str(len(flagged)))],
                   "links": [("SEE ALL ORDERS", "orders"),
                             ("SEE THE CUSTOMERS", "companies")]},
    }


# --- one customer ----------------------------------------------------------

def _order_tone(order) -> str:
    if order["status"] in config.TERMINAL_STATUSES:
        return TONE_DONE
    if "OVERDUE" in order["alerts"]:
        return TONE_LATE
    if order["alerts"]:
        return TONE_DUE
    return TONE_OPEN


def for_company(company_id: int) -> dict | None:
    conn = db.connect()
    company = conn.execute("SELECT * FROM companies WHERE id = ?",
                           (company_id,)).fetchone()
    if company is None:
        return None
    company = dict(company)

    their_orders = orders.list_orders(company_id=company_id, include_closed=True,
                                      sort="promise_date", limit=200)
    order_nodes = [
        _node(f"order/{order['id']}", "ORDER", orders.headline(order),
              sub=" · ".join(filter(None, (orders.sub_headline(order),
                                           order["status"]))),
              tone=_order_tone(order),
              badges=[a for a in order["alerts"]],
              drill=f"order/{order['id']}", link=f"order/{order['id']}",
              weight=1 + (order["doc_count"] or 0))
        for order in their_orders
    ]

    folder_nodes = [
        _node(f"folder/{folder['id']}", "FOLDER", folder["topic"],
              sub=f"{folder['ref']} · {folder['status']}",
              tone=(TONE_LATE if folder["overdue"] else
                    TONE_OPEN if folder["open"] else TONE_DONE),
              badges=([f"{folder['open_actions']} action(s)"]
                      if folder["open_actions"] else []),
              link=f"folder/{folder['id']}")
        for folder in threads.list_folders(company_id=company_id)
    ]

    case_nodes = [
        _node(f"case/{case['id']}", "CASE", case["title"],
              sub=f"{case['ref']} · {case['status']}",
              tone=(TONE_LATE if case["overdue"] else
                    TONE_DUE if case["open"] else TONE_DONE),
              badges=[case["severity"]] if case.get("severity") else [],
              link=f"case/{case['id']}")
        for case in cases.list_cases(company_id=company_id)
    ]

    open_orders = [o for o in their_orders
                   if o["status"] not in config.TERMINAL_STATUSES]
    rows = [
        ("WHERE", ", ".join(filter(None, (company.get("city"),
                                          company.get("country")))) or "—"),
        ("CONTACT", company.get("contact_name") or "—"),
        ("EMAIL", company.get("contact_email") or "—"),
        ("ORDERS", f"{len(their_orders)} on file, {len(open_orders)} open"),
        ("OPEN VALUE", sum(o["value"] or 0 for o in open_orders)),
        ("FOLDERS", str(len([f for f in folder_nodes if f["tone"] != TONE_DONE]))),
        ("DISPUTES", str(len([c for c in case_nodes if c["tone"] != TONE_DONE]))),
    ]

    groups = [_group("ORDERS", order_nodes, side="left")]
    others = folder_nodes + case_nodes
    if others:
        groups.append(_group("FOLDERS & DISPUTES", others, side="right"))

    return {
        "hub": _node(f"company/{company_id}", "COMPANY", company["name"],
                     sub=f"{len(open_orders)} open order(s)"),
        "groups": groups,
        "detail": {
            "kind": "COMPANY", "title": company["name"], "rows": rows,
            "money_rows": ["OPEN VALUE"],
            "links": [("THEIR ORDERS", f"company-orders/{company_id}"),
                      ("THEIR FOLDERS", f"company-folders/{company_id}"),
                      ("EDIT CUSTOMER", f"company-edit/{company_id}")],
        },
    }


# --- one order -------------------------------------------------------------

def for_order(order_id: int) -> dict | None:
    order = orders.get_order(order_id)
    if order is None:
        return None

    here = config.PIPELINE.index(order["status"]) \
        if order["status"] in config.PIPELINE else -1
    stage_nodes = []
    for index, stage in enumerate(config.PIPELINE):
        if here >= 0 and index > here + 1:
            continue                      # the future, beyond the next step
        stage_nodes.append(_node(
            f"stage/{order_id}/{stage}", "STAGE", stage,
            sub=("done" if here >= 0 and index < here
                 else "now" if index == here
                 else "next"),
            tone=(TONE_DONE if here >= 0 and index < here
                  else TONE_OPEN if index == here else TONE_IDLE)))

    attached = []
    for document in order["documents"][:40]:
        attached.append(_node(
            f"doc/{document['id']}", "DOC", document["filename"],
            sub=document.get("kind") or "OTHER", tone=TONE_IDLE,
            link=f"document/{document['id']}"))
    for item in order.get("emails", mail.list_mail(order_id=order_id)):
        attached.append(_node(
            f"mail/{item['id']}", "EMAIL", item.get("subject") or "(no subject)",
            sub=f"{'sent' if item.get('direction') == 'OUT' else 'received'}"
                f" · {str(item.get('sent_at') or '')[:10]}",
            tone=TONE_DUE if item.get("needs_review") else TONE_IDLE,
            link=f"mail/{item['id']}"))
    for case in cases.list_cases(order_id=order_id):
        attached.append(_node(
            f"case/{case['id']}", "CASE", case["title"],
            sub=f"{case['ref']} · {case['status']}",
            tone=TONE_LATE if case["overdue"] else TONE_DUE,
            link=f"case/{case['id']}"))
    for folder in threads.list_folders():
        if folder.get("order_id") == order_id:
            attached.append(_node(
                f"folder/{folder['id']}", "FOLDER", folder["topic"],
                sub=f"{folder['ref']} · {folder['status']}",
                tone=TONE_OPEN if folder["open"] else TONE_DONE,
                link=f"folder/{folder['id']}"))

    spec = order.get("spec") or {}
    cost = (spec.get("cost") or {}).get("total") or {}
    rows = [
        ("PRODUCT", order.get("product_name") or "—"),
        ("PRODUCT NO", order.get("product_code") or "—"),
        ("ORDER NO", order["order_no"]),
        ("CUSTOMER", order.get("company") or "—"),
        ("CUSTOMER PO", order.get("po_number") or "—"),
        ("STATUS", order["status"]),
        ("PROMISED", order.get("promise_date") or "—"),
        ("VALUE", order.get("value") or 0),
        ("QUOTED", cost.get("quoted_usd") or 0),
        ("DOCUMENTS", str(len(order["documents"]))),
    ]

    return {
        "hub": _node(f"order/{order_id}", "ORDER", orders.headline(order),
                     sub=" · ".join(filter(None, (
                         order["order_no"], order.get("company") or ""))),
                     tone=_order_tone(order), badges=order["alerts"]),
        "groups": [
            _group("THE PROCESS", stage_nodes, side="left"),
            _group("ON THIS ORDER", attached, side="right"),
        ],
        "detail": {
            "kind": "ORDER", "title": orders.headline(order), "rows": rows,
            "money_rows": ["VALUE", "QUOTED"],
            "pipeline": {"stages": config.PIPELINE, "here": order["status"]},
            "alerts": order["alerts"],
            "links": [("OPEN THE ORDER", f"order/{order_id}"),
                      ("SPECIFICATION", f"order/{order_id}/spec"),
                      ("COST", f"order/{order_id}/cost"),
                      ("DOCUMENTS", f"order/{order_id}/docs"),
                      ("PRINT SHEET", f"print/order/{order_id}")],
            "company_id": order.get("company_id"),
        },
    }


def view(what: str = "") -> dict:
    """Whichever depth was asked for: "", "company/3", "order/12"."""
    kind, _, key = str(what or "").partition("/")
    if kind == "company" and key.isdigit():
        found = for_company(int(key))
    elif kind == "order" and key.isdigit():
        found = for_order(int(key))
    else:
        found = None
    if found is None:
        found = overview()
        found["at"] = ""
        return found
    found["at"] = what
    return found
