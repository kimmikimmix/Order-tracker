"""The local HTTP server: a JSON API plus the single-page front end.

Bound to 127.0.0.1 by default, so it is reachable from this machine only —
nothing is exposed to the network and no data leaves the computer.
"""

import csv
import io
import json
import mimetypes
import re
import threading
import traceback
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import (attach, backup, briefing, cases, config, db, documents, geo,
               graph, importer, mail, multipart, orders, pcb, prefs,
               printsheet, relocate, settings, threads)

MAX_BODY_BYTES = config.MAX_UPLOAD_BYTES + (8 * 1024 * 1024)


class ApiError(Exception):
    def __init__(self, message, status=HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


ROUTES = []


def route(method, pattern):
    """Register a handler for a method and path pattern."""
    compiled = re.compile(f"^{pattern}$")

    def decorator(fn):
        ROUTES.append((method, compiled, fn))
        return fn

    return decorator


# --- API: orders -----------------------------------------------------------

@route("GET", r"/api/bootstrap")
def api_bootstrap(handler, match):
    return {
        "pipeline": config.PIPELINE,
        "special_statuses": config.SPECIAL_STATUSES,
        "all_statuses": config.ALL_STATUSES,
        "terminal_statuses": sorted(config.TERMINAL_STATUSES),
        "doc_kinds": sorted(config.DOC_KINDS) + ["OTHER"],
        "import_fields": list(importer.FIELDS),
        "field_labels": {name: list(pair)
                         for name, pair in config.FIELD_LABELS.items()},
        "companies": _companies(),
        "products": orders.product_list(),
        "dashboard": _dashboard(),
        "thresholds": {
            "due_soon_days": int(prefs.get("due_soon_days")),
            "stalled_days": int(prefs.get("stalled_days")),
        },
        "prefs": prefs.load(),
        "mail_categories": [name for name, _ in mail.CATEGORIES] + ["GENERAL"],
        "case_kinds": prefs.get("case_kinds"),
        "case_severities": prefs.get("case_severities"),
        "case_statuses": prefs.get("case_statuses"),
        "case_entry_kinds": prefs.get("case_entry_kinds"),
        "thread_kinds": prefs.get("thread_kinds"),
        "thread_statuses": prefs.get("thread_statuses"),
        "countries": geo.country_list(),
        "cities": geo.city_list(),
        "spec_fields": [{"name": n, "kind": k, "label": pcb.LABELS.get(n, n)}
                        for n, k in pcb.SPEC_FIELDS],
        "cost_fields": [{"name": n, "kind": k} for n, k in pcb.COST_FIELDS],
        "saved": backup.last_saved(),
    }


@route("GET", r"/api/ping")
def api_ping(handler, match):
    """Used to spot an Order Tracker that is already running on this port."""
    return {"app": "order-tracker", "data": str(config.DATA_DIR)}


def _companies() -> list[dict]:
    """The customer list, with how many folders each one has running."""
    counts = threads.counts_by_company()
    return [company | {"folders": counts.get(company["id"], {}).get("total", 0),
                       "open_folders": counts.get(company["id"], {}).get("open", 0)}
            for company in orders.list_companies()]


def _dashboard() -> dict:
    """The order book's own figures, plus the trays that need attention."""
    board = orders.dashboard()
    board["mail"] = mail.tray()
    board["cases"] = cases.summary()
    board["folders"] = threads.summary()
    board["today"] = briefing.today()
    return board


@route("GET", r"/api/graph")
def api_graph(handler, match):
    """One hub and its neighbours, at whichever depth was asked for."""
    return graph.view(handler.query.get("at", ""))


@route("GET", r"/api/today")
def api_today(handler, match):
    days = int(handler.query.get("days") or briefing.SOON_DAYS)
    return briefing.today(days)


@route("GET", r"/api/dashboard")
def api_dashboard(handler, match):
    return _dashboard()


@route("GET", r"/api/orders")
def api_orders(handler, match):
    q = handler.query
    return {
        "orders": orders.list_orders(
            status=q.get("status"),
            company_id=_int_or_none(q.get("company_id")),
            owner=q.get("owner"),
            alert=q.get("alert"),
            query=q.get("q"),
            sort=q.get("sort", "promise_date"),
            direction=q.get("dir", "asc"),
            include_closed=q.get("closed", "1") == "1",
        )
    }


@route("GET", r"/api/orders/(\d+)")
def api_order_detail(handler, match):
    order_id = int(match.group(1))
    order = orders.get_order(order_id)
    if order is None:
        raise ApiError("No such order.", HTTPStatus.NOT_FOUND)
    # Joined here rather than in orders.py: cases already read orders, and
    # a module that imports the module importing it is a cycle waiting to
    # happen.
    order["cases"] = cases.list_cases(order_id=order_id)
    order["emails"] = mail.list_mail(order_id=order_id)
    return order


@route("POST", r"/api/orders")
def api_order_create(handler, match):
    data = handler.json_body()
    try:
        order_id = orders.create_order(data, actor=data.get("actor", ""))
    except orders.OrderError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True, "id": order_id, "order": orders.get_order(order_id)}


@route("POST", r"/api/orders/(\d+)")
def api_order_update(handler, match):
    order_id = int(match.group(1))
    data = handler.json_body()
    try:
        orders.update_order(order_id, data, actor=data.get("actor", ""),
                            note=data.get("note", ""))
    except orders.OrderError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True, "order": orders.get_order(order_id)}


@route("POST", r"/api/orders/(\d+)/history")
def api_order_note_add(handler, match):
    """A line of your own in an order's history."""
    order_id = int(match.group(1))
    try:
        entry_id = orders.add_note(order_id, handler.json_body())
    except orders.OrderError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True, "id": entry_id, "order": orders.get_order(order_id)}


@route("POST", r"/api/history/(\d+)")
def api_order_note_update(handler, match):
    try:
        orders.update_note(int(match.group(1)), handler.json_body())
    except orders.OrderError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True}


@route("DELETE", r"/api/history/(\d+)")
def api_order_note_delete(handler, match):
    try:
        order_id = orders.delete_note(int(match.group(1)))
    except orders.OrderError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True, "order": orders.get_order(order_id)}


@route("DELETE", r"/api/orders/(\d+)")
def api_order_delete(handler, match):
    orders.delete_order(int(match.group(1)))
    return {"ok": True}


# --- API: companies --------------------------------------------------------

@route("GET", r"/api/companies")
def api_companies(handler, match):
    return {"companies": _companies()}


@route("POST", r"/api/companies")
def api_company_save(handler, match):
    try:
        company_id = orders.save_company(handler.json_body())
    except orders.OrderError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True, "id": company_id, "companies": _companies()}


# --- API: search -----------------------------------------------------------

@route("GET", r"/api/search")
def api_search(handler, match):
    return orders.search(handler.query.get("q", ""))


# --- API: documents --------------------------------------------------------

@route("GET", r"/api/documents")
def api_documents(handler, match):
    q = handler.query
    return {
        "documents": documents.list_documents(
            order_id=_int_or_none(q.get("order_id")),
            unfiled=q.get("unfiled") == "1",
        )
    }


@route("POST", r"/api/documents/upload")
def api_document_upload(handler, match):
    fields = handler.multipart_body()
    order_id = _int_or_none(multipart.value(fields, "order_id"))
    kind = multipart.value(fields, "kind") or None
    files = fields.get("files") or fields.get("file") or []
    if not files:
        raise ApiError("No file was included in the upload.")

    saved, failed = [], []
    for part in files:
        if not part.filename:
            continue
        try:
            # A saved email is worth more than a stored file: read it, so
            # its sender, its summary and its attachments come with it.
            if kind in (None, "", "EMAIL") and mail.looks_like_mail(
                    part.filename, part.data):
                item = mail.intake(part.filename, part.data, order_id=order_id)
                saved.append({
                    "id": item.get("doc_id"), "filename": part.filename,
                    "kind": "EMAIL", "order_id": item.get("order_id"),
                    "autofiled_to": item.get("order_id"),
                    "duplicate": item.get("duplicate", False),
                    "mail_id": item.get("id"),
                    "subject": item.get("subject"),
                    "text_len": len(item.get("summary") or ""),
                })
                continue
            doc = documents.store(part.filename, part.data,
                                  order_id=order_id, kind=kind)
            if not order_id:
                matched = documents.autofile(doc["id"])
                doc["autofiled_to"] = matched
            saved.append({
                "id": doc["id"], "filename": doc["filename"],
                "kind": doc["kind"], "order_id": doc.get("order_id"),
                "autofiled_to": doc.get("autofiled_to"),
                "duplicate": doc.get("duplicate", False),
                "extract_note": doc.get("extract_note"),
                "text_len": len(doc.get("content_text") or ""),
            })
        except Exception as exc:
            failed.append({"filename": part.filename, "error": str(exc)})

    return {"ok": True, "saved": saved, "failed": failed}


@route("POST", r"/api/attachments/([a-z_]+)/(\d+)")
def api_attach(handler, match):
    """Hang photos or files on one line of a log."""
    owner, owner_id = match.group(1), int(match.group(2))
    fields = handler.multipart_body()
    files = fields.get("files") or fields.get("file") or []
    if not files:
        raise ApiError("No file was included in the upload.")

    saved, failed = [], []
    for part in files:
        if not part.filename:
            continue
        try:
            saved.append(attach.add(owner, owner_id, part.filename, part.data))
        except attach.AttachError as exc:
            raise ApiError(str(exc)) from exc
        except Exception as exc:                  # unreadable, out of room
            failed.append({"filename": part.filename, "error": str(exc)})
    return {"ok": True, "saved": saved, "failed": failed}


@route("DELETE", r"/api/attachments/(\d+)")
def api_attach_remove(handler, match):
    attach.remove(int(match.group(1)))
    return {"ok": True}


def _disposition(kind: str, filename: str) -> str:
    """A Content-Disposition value that survives a Korean filename.

    An HTTP header can only carry latin-1, and a name in Hangul is not
    latin-1 — put one in raw and the whole response dies after the status
    line, which the browser shows as a broken image. So the real name goes
    in the RFC 5987 form, percent-encoded and marked UTF-8, and a plain
    ASCII stand-in goes in the old form beside it.
    """
    plain = documents.ascii_name(filename)
    encoded = urllib.parse.quote(documents.safe_name(filename), safe="")
    return f"{kind}; filename=\"{plain}\"; filename*=UTF-8\'\'{encoded}"


@route("GET", r"/api/documents/(\d+)/file")
def api_document_file(handler, match):
    doc = documents.get(int(match.group(1)))
    if doc is None:
        raise ApiError("No such document.", HTTPStatus.NOT_FOUND)
    path = documents.path_for(doc)
    if not path.exists():
        raise ApiError("That file is missing from the documents folder.",
                       HTTPStatus.NOT_FOUND)

    data = path.read_bytes()
    inline = handler.query.get("download") != "1"
    # Only render types a browser shows safely inline; anything else downloads.
    safe_inline = {"application/pdf", "text/plain", "image/png", "image/jpeg",
                   "image/gif", "image/webp"}
    mime = doc["mime"] or "application/octet-stream"
    if inline and mime in safe_inline:
        disposition = "inline"
    else:
        disposition = "attachment"
        if mime not in safe_inline:
            mime = "application/octet-stream"

    handler.send_bytes(
        data, mime,
        extra_headers={
            "Content-Disposition": _disposition(disposition, doc["filename"]),
            "X-Content-Type-Options": "nosniff",
        },
    )
    return None


@route("GET", r"/api/documents/(\d+)/text")
def api_document_text(handler, match):
    doc = documents.get(int(match.group(1)))
    if doc is None:
        raise ApiError("No such document.", HTTPStatus.NOT_FOUND)
    return {
        "id": doc["id"], "filename": doc["filename"],
        "text": doc["content_text"] or "",
        "note": doc["extract_note"] or "",
    }


@route("POST", r"/api/documents/(\d+)")
def api_document_update(handler, match):
    doc_id = int(match.group(1))
    data = handler.json_body()
    if "kind" in data:
        documents.set_kind(doc_id, data["kind"])
    if data.get("autofile"):
        documents.autofile(doc_id)
    if "order_id" in data:
        try:
            documents.attach(doc_id, _int_or_none(data["order_id"]))
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
    return {"ok": True, "document": documents.get(doc_id)}


@route("DELETE", r"/api/documents/(\d+)")
def api_document_delete(handler, match):
    documents.delete(int(match.group(1)))
    return {"ok": True}


# --- API: email intake -----------------------------------------------------

@route("GET", r"/api/mail")
def api_mail_list(handler, match):
    q = handler.query
    review = q.get("review")
    return {
        "mail": mail.list_mail(
            needs_review=None if review in (None, "", "all") else review == "1",
            order_id=_int_or_none(q.get("order_id")),
            company_id=_int_or_none(q.get("company_id")),
            category=q.get("category") or None,
            direction=q.get("direction") or None,
            query=q.get("q") or None),
        "tray": mail.tray(),
    }


@route("POST", r"/api/mail/upload")
def api_mail_upload(handler, match):
    """Take saved emails, read them, and file what can be filed."""
    fields = handler.multipart_body()
    order_id = _int_or_none(multipart.value(fields, "order_id"))
    files = fields.get("files") or fields.get("file") or []
    if not files:
        raise ApiError("No email was included in the upload.")

    read, failed = [], []
    for part in files:
        if not part.filename:
            continue
        try:
            read.append(mail.intake(part.filename, part.data, order_id=order_id))
        except Exception as exc:
            failed.append({"filename": part.filename, "error": str(exc)})
    return {"ok": True, "mail": read, "failed": failed, "tray": mail.tray()}


@route("GET", r"/api/mail/(\d+)")
def api_mail_detail(handler, match):
    item = mail.get(int(match.group(1)))
    if item is None:
        raise ApiError("No such email.", HTTPStatus.NOT_FOUND)
    if item.get("doc_id"):
        document = documents.get(item["doc_id"])
        item["body"] = (document or {}).get("content_text") or ""
    return item


@route("POST", r"/api/mail/(\d+)")
def api_mail_assign(handler, match):
    """Change where a mail is filed, which way it went, or both.

    Kept as one route but two separate decisions: relabelling a mail as
    sent must not disturb the order it is filed against, and refiling it
    must not change which way it went.
    """
    mail_id = int(match.group(1))
    data = handler.json_body()
    try:
        if data.get("direction"):
            mail.set_direction(mail_id, data["direction"])
        if {"order_id", "company_id", "confirmed"} & set(data):
            mail.assign(mail_id,
                        order_id=_int_or_none(data.get("order_id")),
                        company_id=_int_or_none(data.get("company_id")),
                        confirmed=bool(data.get("confirmed", True)))
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True, "mail": mail.get(mail_id)}


@route("DELETE", r"/api/mail/(\d+)")
def api_mail_delete(handler, match):
    keep = handler.query.get("keep_document") == "1"
    mail.delete(int(match.group(1)), with_document=not keep)
    return {"ok": True}


# --- API: enquiry folders --------------------------------------------------

@route("GET", r"/api/threads")
def api_threads(handler, match):
    q = handler.query
    days = int(q.get("days") or prefs.get("due_soon_days") or 7)
    return {
        "folders": threads.list_folders(
            company_id=_int_or_none(q.get("company_id")),
            status=q.get("status") or None,
            open_only=q.get("open") == "1",
            query=q.get("q") or None),
        "follow_ups": threads.follow_ups(days),
        "due": threads.due_folders(days),
        "summary": threads.summary(),
    }


@route("POST", r"/api/threads")
def api_thread_open(handler, match):
    data = handler.json_body()
    try:
        folder_id = threads.open_folder(data, actor=str(data.get("actor") or ""))
    except threads.ThreadError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True, "id": folder_id, "folder": threads.get_folder(folder_id)}


@route("GET", r"/api/threads/(\d+)")
def api_thread_detail(handler, match):
    folder = threads.get_folder(int(match.group(1)))
    if folder is None:
        raise ApiError("No such folder.", HTTPStatus.NOT_FOUND)
    return folder


@route("POST", r"/api/threads/(\d+)")
def api_thread_update(handler, match):
    data = handler.json_body()
    try:
        return {"ok": True, "folder": threads.update_folder(
            int(match.group(1)), data, actor=str(data.get("actor") or ""))}
    except threads.ThreadError as exc:
        raise ApiError(str(exc)) from exc


@route("DELETE", r"/api/threads/(\d+)")
def api_thread_delete(handler, match):
    threads.delete_folder(int(match.group(1)))
    return {"ok": True}


@route("POST", r"/api/threads/(\d+)/entries")
def api_thread_entry_add(handler, match):
    folder_id = int(match.group(1))
    try:
        entry_id = threads.add_entry(folder_id, handler.json_body())
    except threads.ThreadError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True, "id": entry_id, "folder": threads.get_folder(folder_id)}


@route("POST", r"/api/thread-entries/(\d+)")
def api_thread_entry_update(handler, match):
    data = handler.json_body()
    entry_id = int(match.group(1))
    try:
        if "done" in data:
            threads.complete_follow_up(entry_id, bool(data["done"]))
        else:
            threads.update_entry(entry_id, data)
    except threads.ThreadError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True}


@route("DELETE", r"/api/thread-entries/(\d+)")
def api_thread_entry_delete(handler, match):
    threads.delete_entry(int(match.group(1)))
    return {"ok": True}


@route("POST", r"/api/threads/(\d+)/emails")
def api_thread_file_email(handler, match):
    data = handler.json_body()
    email_id = _int_or_none(data.get("email_id"))
    if not email_id:
        raise ApiError("Choose an email to file.")
    try:
        return {"ok": True, "folder": threads.file_email(
            int(match.group(1)), email_id, actor=str(data.get("actor") or ""))}
    except threads.ThreadError as exc:
        raise ApiError(str(exc)) from exc


@route("DELETE", r"/api/threads/(\d+)/emails/(\d+)")
def api_thread_remove_email(handler, match):
    threads.remove_email(int(match.group(1)), int(match.group(2)))
    return {"ok": True}


# --- API: disputes and defects ---------------------------------------------

@route("GET", r"/api/cases")
def api_cases(handler, match):
    q = handler.query
    return {
        "cases": cases.list_cases(
            status=q.get("status") or None,
            order_id=_int_or_none(q.get("order_id")),
            company_id=_int_or_none(q.get("company_id")),
            open_only=q.get("open") == "1",
            query=q.get("q") or None),
        "follow_ups": cases.follow_ups(
            int(q.get("days") or prefs.get("due_soon_days") or 7)),
        "summary": cases.summary(),
    }


@route("POST", r"/api/cases")
def api_case_open(handler, match):
    data = handler.json_body()
    try:
        case_id = cases.open_case(data, actor=str(data.get("actor") or ""))
    except cases.CaseError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True, "id": case_id, "case": cases.get_case(case_id)}


@route("GET", r"/api/cases/(\d+)")
def api_case_detail(handler, match):
    case = cases.get_case(int(match.group(1)))
    if case is None:
        raise ApiError("No such case.", HTTPStatus.NOT_FOUND)
    return case


@route("POST", r"/api/cases/(\d+)")
def api_case_update(handler, match):
    data = handler.json_body()
    try:
        return {"ok": True, "case": cases.update_case(
            int(match.group(1)), data, actor=str(data.get("actor") or ""))}
    except cases.CaseError as exc:
        raise ApiError(str(exc)) from exc


@route("DELETE", r"/api/cases/(\d+)")
def api_case_delete(handler, match):
    cases.delete_case(int(match.group(1)))
    return {"ok": True}


@route("POST", r"/api/cases/(\d+)/entries")
def api_case_entry_add(handler, match):
    case_id = int(match.group(1))
    try:
        entry_id = cases.add_entry(case_id, handler.json_body())
    except cases.CaseError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True, "id": entry_id, "case": cases.get_case(case_id)}


@route("POST", r"/api/case-entries/(\d+)")
def api_case_entry_update(handler, match):
    data = handler.json_body()
    entry_id = int(match.group(1))
    try:
        if "done" in data:
            cases.complete_follow_up(entry_id, bool(data["done"]))
        else:
            cases.update_entry(entry_id, data)
    except cases.CaseError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True}


@route("DELETE", r"/api/case-entries/(\d+)")
def api_case_entry_delete(handler, match):
    cases.delete_entry(int(match.group(1)))
    return {"ok": True}


@route("GET", r"/api/follow-ups")
def api_follow_ups(handler, match):
    days = int(handler.query.get("days") or 7)
    return {"follow_ups": cases.follow_ups(days)}


# --- API: import / export --------------------------------------------------

@route("POST", r"/api/import/preview")
def api_import_preview(handler, match):
    fields = handler.multipart_body()
    part = multipart.first(fields, "file")
    if part is None or not part.filename:
        raise ApiError("Choose a CSV or Excel file first.")
    try:
        result = importer.preview(part.data, part.filename)
    except Exception as exc:
        raise ApiError(f"That file could not be read: {exc}") from exc
    result["filename"] = part.filename
    return result


@route("POST", r"/api/import/run")
def api_import_run(handler, match):
    fields = handler.multipart_body()
    part = multipart.first(fields, "file")
    if part is None or not part.filename:
        raise ApiError("Choose a CSV or Excel file first.")
    try:
        mapping = json.loads(multipart.value(fields, "mapping", "{}"))
    except json.JSONDecodeError as exc:
        raise ApiError("The column mapping was not valid.") from exc

    return importer.run_import(
        part.data, part.filename, mapping,
        update_existing=multipart.value(fields, "update_existing", "1") == "1",
        default_status=multipart.value(fields, "default_status", ""),
        actor=multipart.value(fields, "actor", ""),
    )


@route("GET", r"/api/export/orders\.csv")
def api_export(handler, match):
    rows = orders.list_orders(limit=100000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    columns = ["product_name", "product_code", "order_no", "work_order_no",
               "company", "po_number", "description", "status",
               "value", "currency", "order_date", "promise_date", "ship_date",
               "owner", "priority", "doc_count", "notes"]
    # Korean first in the header row, so the file opens in Excel reading
    # the way the screens do; the English name follows in brackets.
    writer.writerow([
        f"{config.FIELD_LABELS[c][0]} ({config.FIELD_LABELS[c][1]})"
        if c in config.FIELD_LABELS else c
        for c in columns] + ["alerts"])
    for row in rows:
        writer.writerow([row.get(c, "") for c in columns] + ["; ".join(row["alerts"])])

    handler.send_bytes(
        buf.getvalue().encode("utf-8-sig"), "text/csv",
        extra_headers={"Content-Disposition": 'attachment; filename="orders.csv"'},
    )
    return None


@route("POST", r"/api/quit")
def api_quit(handler, match):
    """Stop the app from the browser, so no console window is needed."""
    # shutdown() blocks until the serving loop ends, so it cannot be called
    # from the thread serving this very request. The short delay lets this
    # reply reach the browser before the socket goes away.
    threading.Timer(0.4, handler.server.shutdown).start()
    return {"ok": True, "stopped": True}


@route("POST", r"/api/maintenance/reindex")
def api_reindex(handler, match):
    db.rebuild_search_index()
    count = documents.reextract_all()
    return {"ok": True, "documents_reread": count}



# --- API: build specification and costing -----------------------------------

@route("GET", r"/api/orders/(\d+)/spec")
def api_spec_get(handler, match):
    return orders.get_spec(int(match.group(1)))


@route("POST", r"/api/orders/(\d+)/spec")
def api_spec_save(handler, match):
    try:
        return orders.save_spec(int(match.group(1)), handler.json_body())
    except orders.OrderError as exc:
        raise ApiError(str(exc)) from exc


@route("GET", r"/api/reorder-sources")
def api_reorder_sources(handler, match):
    """Earlier orders whose specification can be reused for a repeat order."""
    return {"orders": orders.reorder_sources(
        company_id=_int_or_none(handler.query.get("company_id")))}


@route("POST", r"/api/quote")
def api_quote(handler, match):
    """Price a spec without saving it, so the form can total as it is typed."""
    data = handler.json_body()
    spec = pcb.clean(data)
    settings_now = prefs.load()
    return {"derived": pcb.derive(spec, settings_now),
            "cost": pcb.cost_sheet(spec, settings_now)}


# --- API: the world map ----------------------------------------------------

@route("GET", r"/api/map")
def api_map(handler, match):
    return orders.map_points()


# --- API: settings ---------------------------------------------------------

@route("GET", r"/api/prefs")
def api_prefs(handler, match):
    saved = settings.load()
    return {"prefs": prefs.load(), "defaults": prefs.DEFAULTS,
            "welcome": {"name": saved.get("welcome_name") or "",
                        "show": bool(saved.get("show_welcome", True))},
            "paths": {"data": str(config.DATA_DIR),
                      "documents": str(config.DOCS_DIR),
                      "app": str(config.BASE_DIR),
                      "portable": config.PORTABLE,
                      "settings_file": str(settings.settings_path())}}


@route("POST", r"/api/prefs")
def api_prefs_save(handler, match):
    data = handler.json_body()
    welcome = data.pop("welcome", None)
    if isinstance(welcome, dict):
        settings.save(welcome_name=str(welcome.get("name") or ""),
                      show_welcome=bool(welcome.get("show", True)))
    return {"ok": True, "prefs": prefs.save(data)}


@route("POST", r"/api/prefs/reset")
def api_prefs_reset(handler, match):
    return {"ok": True, "prefs": prefs.reset()}


# --- API: saving and backups -----------------------------------------------

@route("GET", r"/api/status")
def api_status(handler, match):
    return backup.status()


@route("POST", r"/api/backup")
def api_backup(handler, match):
    folder = (handler.json_body() or {}).get("folder")
    try:
        return backup.run(folder)
    except backup.BackupError as exc:
        raise ApiError(str(exc)) from exc


# --- API: moving to another drive ------------------------------------------

@route("POST", r"/api/move/check")
def api_move_check(handler, match):
    """What a copy to this folder would involve. Writes nothing."""
    folder = (handler.json_body() or {}).get("folder", "")
    if not str(folder).strip():
        raise ApiError("Type the folder you want it copied to first.")
    try:
        return relocate.plan(folder)
    except OSError as exc:
        raise ApiError(f"That folder could not be checked: {exc}") from exc


@route("POST", r"/api/move")
def api_move(handler, match):
    """Copy the app and its data somewhere else, from inside the app.

    Doing it from here saves getting a command prompt into the right folder,
    which is the step that goes wrong most often. The app copying itself is
    safe: it reads its own database through SQLite's backup call and writes
    only to the new folder.
    """
    data = handler.json_body()
    folder = str(data.get("folder") or "").strip()
    if not folder:
        raise ApiError("Type the folder you want it copied to first.")
    try:
        return relocate.run(
            folder,
            keep_git=bool(data.get("keep_git", True)),
            shortcut=bool(data.get("shortcut", True)),
            replace_data=bool(data.get("replace_data", False)))
    except relocate.MoveError as exc:
        raise ApiError(str(exc)) from exc
    except OSError as exc:
        raise ApiError(f"The copy failed: {exc}") from exc


# --- The printable sheet ---------------------------------------------------

@route("GET", r"/print/order/(\d+)")
def print_order(handler, match):
    page = printsheet.render(int(match.group(1)))
    if page is None:
        raise ApiError("No such order.", HTTPStatus.NOT_FOUND)
    handler.send_bytes(page.encode("utf-8"), "text/html; charset=utf-8")
    return None


@route("GET", r"/print/folder/(\d+)")
def print_folder(handler, match):
    page = printsheet.folder_sheet(int(match.group(1)))
    if not page:
        raise ApiError("No such folder.", HTTPStatus.NOT_FOUND)
    handler.send_bytes(page.encode("utf-8"), "text/html; charset=utf-8")
    return None


@route("GET", r"/print/case/(\d+)")
def print_case(handler, match):
    page = printsheet.case_sheet(int(match.group(1)))
    if not page:
        raise ApiError("No such case.", HTTPStatus.NOT_FOUND)
    handler.send_bytes(page.encode("utf-8"), "text/html; charset=utf-8")
    return None


# --- Handler ---------------------------------------------------------------

def _int_or_none(value):
    try:
        return int(value) if value not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "OrderTracker"
    protocol_version = "HTTP/1.1"

    # -- plumbing ----------------------------------------------------------

    def log_message(self, fmt, *args):
        if self.path.startswith("/api/") and not self.path.startswith("/api/bootstrap"):
            print(f"  {self.command} {self.path}")

    def _origin_is_ours(self) -> bool:
        """Reject a write triggered by some other page in the browser.

        Our own requests carry an Origin matching the address bar. A page on
        another site would carry its own, and must not be able to change or
        stop anything here.
        """
        origin = self.headers.get("Origin")
        if not origin:
            return True  # not a browser, or a same-origin navigation
        host = (self.headers.get("Host") or "").strip()
        return origin in (f"http://{host}", f"https://{host}")

    def _host_is_local(self) -> bool:
        """Refuse requests that arrive under some other hostname.

        Stops a web page you happen to be visiting from pointing a hostname at
        127.0.0.1 and reading your order book through the browser.
        """
        host = (self.headers.get("Host") or "").split(":")[0].strip("[]").lower()
        return host in ("localhost", "127.0.0.1", "::1", "") or host == config.HOST

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_PUT(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        if not self._host_is_local():
            self.send_error(HTTPStatus.FORBIDDEN, "Non-local host header")
            return
        if method != "GET" and not self._origin_is_ours():
            self.send_error(HTTPStatus.FORBIDDEN, "Cross-site request")
            return

        parsed = urllib.parse.urlparse(self.path)
        self.query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        path = urllib.parse.unquote(parsed.path)
        self._body = None

        for route_method, pattern, fn in ROUTES:
            if route_method != method:
                continue
            match = pattern.match(path)
            if not match:
                continue
            try:
                result = fn(self, match)
            except ApiError as exc:
                self.send_json({"error": str(exc)}, status=exc.status)
            except Exception as exc:
                traceback.print_exc()
                self.send_json({"error": f"{type(exc).__name__}: {exc}"},
                               status=HTTPStatus.INTERNAL_SERVER_ERROR)
            else:
                if result is not None:
                    self.send_json(result)
            return

        if method == "GET":
            self.serve_static(path)
        else:
            self.send_json({"error": "Unknown endpoint."}, status=HTTPStatus.NOT_FOUND)

    # -- request bodies ----------------------------------------------------

    def read_body(self) -> bytes:
        if self._body is None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                raise ApiError("That upload is too large.",
                               HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            self._body = self.rfile.read(length) if length else b""
        return self._body

    def json_body(self) -> dict:
        raw = self.read_body()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError("The request body was not valid JSON.") from exc
        if not isinstance(data, dict):
            raise ApiError("Expected a JSON object.")
        return data

    def multipart_body(self) -> dict:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ApiError("Expected a file upload.")
        return multipart.parse(self.read_body(), content_type)

    # -- responses ---------------------------------------------------------

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_bytes(body, "application/json; charset=utf-8", status=status)

    def send_bytes(self, body: bytes, content_type: str,
                   status=HTTPStatus.OK, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra_headers or {}).items():
            # A header holds latin-1 and nothing else. Anything that slips
            # through goes out escaped rather than raising halfway
            # through a reply, which would leave the browser with a
            # successful status and an empty body.
            text = str(value)
            try:
                text.encode("latin-1")
            except UnicodeEncodeError:
                text = text.encode("ascii", "backslashreplace").decode("ascii")
            self.send_header(key, text)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser navigated away mid-response

    def serve_static(self, path):
        # The icon and its preview live outside web/, in assets/.
        if path.startswith("/assets/"):
            root = config.ASSETS_DIR
            rel = path[len("/assets/"):]
        else:
            root = config.WEB_DIR
            rel = "index.html" if path in ("/", "") else path.lstrip("/")

        target = (root / rel).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN, "Outside the web directory")
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        if target.name == "index.html":
            self.send_bytes(self.page_with_welcome(target),
                            "text/html; charset=utf-8")
            return

        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_bytes(target.read_bytes(), mime)

    def page_with_welcome(self, target) -> bytes:
        """Inline the welcome settings so the splash never flashes wrongly."""
        from . import settings

        saved = settings.load()
        payload = json.dumps({
            "name": saved.get("welcome_name") or "",
            "show": bool(saved.get("show_welcome", True)),
        })
        html = target.read_text("utf-8")
        return html.replace(
            "</head>",
            f"<script>window.__WELCOME__ = {payload};</script>\n</head>", 1
        ).encode("utf-8")


def serve(host=None, port=None):
    host = host or config.HOST
    port = port or config.PORT
    db.init_db()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd
