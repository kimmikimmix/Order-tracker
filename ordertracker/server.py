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

from . import (backup, config, db, documents, geo, importer, multipart,
               orders, pcb, prefs, printsheet, settings)

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
        "companies": orders.list_companies(),
        "dashboard": orders.dashboard(),
        "thresholds": {
            "due_soon_days": int(prefs.get("due_soon_days")),
            "stalled_days": int(prefs.get("stalled_days")),
        },
        "prefs": prefs.load(),
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


@route("GET", r"/api/dashboard")
def api_dashboard(handler, match):
    return orders.dashboard()


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
    order = orders.get_order(int(match.group(1)))
    if order is None:
        raise ApiError("No such order.", HTTPStatus.NOT_FOUND)
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


@route("DELETE", r"/api/orders/(\d+)")
def api_order_delete(handler, match):
    orders.delete_order(int(match.group(1)))
    return {"ok": True}


# --- API: companies --------------------------------------------------------

@route("GET", r"/api/companies")
def api_companies(handler, match):
    return {"companies": orders.list_companies()}


@route("POST", r"/api/companies")
def api_company_save(handler, match):
    try:
        company_id = orders.save_company(handler.json_body())
    except orders.OrderError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True, "id": company_id, "companies": orders.list_companies()}


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

    filename = doc["filename"].replace('"', "")
    handler.send_bytes(
        data, mime,
        extra_headers={
            "Content-Disposition":
                f'{disposition}; filename="{documents.safe_name(filename)}"',
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
    columns = ["order_no", "company", "po_number", "description", "status",
               "value", "currency", "order_date", "promise_date", "ship_date",
               "owner", "priority", "doc_count", "notes"]
    writer.writerow(columns + ["alerts"])
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


# --- The printable sheet ---------------------------------------------------

@route("GET", r"/print/order/(\d+)")
def print_order(handler, match):
    page = printsheet.render(int(match.group(1)))
    if page is None:
        raise ApiError("No such order.", HTTPStatus.NOT_FOUND)
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
            self.send_header(key, value)
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
