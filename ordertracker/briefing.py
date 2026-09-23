"""What needs doing today, gathered from everywhere it is hiding.

The order book, the email tray, the folders and the case log each know part
of the answer to "what do I have to do this morning". Nobody wants to visit
four pages to find out, so this asks all four and returns one list, worst
first, with a link to the thing itself against every line.

Nothing here decides anything or changes anything. It reads.
"""

import datetime

from . import cases, config, db, mail, orders, threads

# How far ahead "today" looks for something that is coming rather than late.
SOON_DAYS = 1


def _today() -> str:
    return datetime.date.today().isoformat()


def _when(value) -> str:
    """A date in plain words: late, today, tomorrow, or the date itself."""
    parsed = orders.as_date(value)
    if parsed is None:
        return ""
    days = (parsed - datetime.date.today()).days
    if days < -1:
        return f"{-days} days late"
    if days == -1:
        return "1 day late"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


def _item(kind, title, detail, link, when="", late=False, chip="") -> dict:
    return {"kind": kind, "title": title, "detail": detail, "link": link,
            "when": when, "late": bool(late), "chip": chip}


def email_to_check() -> list[dict]:
    """Mail the matching was not sure enough about to file by itself."""
    out = []
    for item in mail.list_mail(needs_review=True, limit=50):
        who = item.get("from_name") or item.get("from_email") or "unknown sender"
        out.append(_item(
            "EMAIL",
            item.get("subject") or "(no subject)",
            f"{who} · {item.get('company') or 'no customer yet'}",
            f"mail/{item['id']}",
            when=str(item.get("sent_at") or item.get("filed_at") or "")[:10],
            chip=item.get("category") or "GENERAL"))
    return out


def actions_due(days: int = SOON_DAYS) -> list[dict]:
    """Follow-ups logged in cases and folders that are due or late."""
    out = []
    for action in cases.follow_ups(days):
        out.append(_item(
            "ACTION", action["summary"],
            f"{action['ref']} · {action.get('company') or ''}"
            f" · {action.get('order_no') or ''}".strip(" ·"),
            f"case/{action['case_id']}",
            when=_when(action["follow_up_at"]), late=action["late"],
            chip="CASE"))
    for action in threads.follow_ups(days):
        out.append(_item(
            "ACTION", action["summary"],
            f"{action['ref']} · {action.get('company') or ''}",
            f"folder/{action['thread_id']}",
            when=_when(action["follow_up_at"]), late=action["late"],
            chip="FOLDER"))
    out.sort(key=lambda row: (not row["late"], row["title"]))
    return out


def folders_due(days: int = SOON_DAYS) -> list[dict]:
    """Conversations whose own come-back date has arrived."""
    return [
        _item("FOLDER", folder["topic"],
              f"{folder['ref']} · {folder['company']} · {folder['status']}",
              f"folder/{folder['id']}",
              when=_when(folder["follow_up_at"]), late=folder["overdue"],
              chip=folder.get("kind") or "")
        for folder in threads.due_folders(days)
    ]


def cases_due(days: int = SOON_DAYS) -> list[dict]:
    """Disputes whose answer is due or already late."""
    horizon = (datetime.date.today()
               + datetime.timedelta(days=days)).isoformat()
    out = []
    for case in cases.list_cases(open_only=True):
        due = case.get("due_at")
        if not due or due > horizon:
            continue
        out.append(_item(
            "CASE", case["title"],
            f"{case['ref']} · {case.get('company') or ''}"
            f" · {case.get('order_no') or ''}".strip(" ·"),
            f"case/{case['id']}",
            when=_when(due), late=case["overdue"], chip=case.get("severity")))
    return out


def orders_due(days: int = SOON_DAYS) -> list[dict]:
    """Orders past their promised date, or promised within the day."""
    horizon = (datetime.date.today()
               + datetime.timedelta(days=days)).isoformat()
    today = _today()
    out = []
    for order in orders.list_orders(include_closed=False, limit=500):
        promised = order.get("promise_date")
        if not promised or promised > horizon:
            continue
        out.append(_item(
            "ORDER", f"{order['order_no']} — {order.get('company') or ''}",
            " · ".join(filter(None, (
                order.get("product_code") or order.get("product_name"),
                order.get("description"), order["status"]))),
            f"order/{order['id']}",
            when=_when(promised), late=promised < today,
            chip=order["status"]))
    out.sort(key=lambda row: (not row["late"], row["title"]))
    return out


def unfiled_documents() -> list[dict]:
    """Paperwork dropped in but never filed against an order.

    Saved emails are left out: they are in the tray above, and listing
    them twice makes the morning look worse than it is.
    """
    from . import documents
    return [
        _item("DOCUMENT", document["filename"],
              document.get("kind") or "OTHER", "docs",
              when=str(document.get("uploaded_at") or "")[:10])
        for document in documents.list_documents(unfiled=True, limit=20)
        if (document.get("kind") or "") != "EMAIL"
    ]


def today(days: int = SOON_DAYS) -> dict:
    """Everything that wants attention, in the order it wants it.

    The groups are returned separately rather than as one list: the reason
    a thing needs doing is most of what tells you how long it will take.
    """
    groups = [
        {"key": "actions", "title": "ACTIONS TO TAKE", "view": "folders",
         "items": actions_due(days)},
        {"key": "email", "title": "EMAIL TO CHECK", "view": "inbox",
         "items": email_to_check()},
        {"key": "orders", "title": "ORDERS DUE", "view": "blotter",
         "items": orders_due(days)},
        {"key": "folders", "title": "FOLDERS TO COME BACK TO",
         "view": "folders", "items": folders_due(days)},
        {"key": "cases", "title": "DISPUTES TO ANSWER", "view": "cases",
         "items": cases_due(days)},
        {"key": "documents", "title": "PAPERWORK NOT FILED", "view": "docs",
         "items": unfiled_documents()},
    ]
    groups = [group for group in groups if group["items"]]
    total = sum(len(group["items"]) for group in groups)
    late = sum(1 for group in groups for item in group["items"] if item["late"])
    return {
        "date": _today(),
        "total": total,
        "late": late,
        "groups": groups,
    }
