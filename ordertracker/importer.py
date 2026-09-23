"""Bring orders in from the CSV and Excel exports you already have.

Nobody wants to retype an order book, and every system exports different
column names, so this reads the header row, guesses which column is which,
shows you the guess, and only writes once you have confirmed it.
"""

import csv
import io
import re

from . import db, orders
from .xlsx import Workbook

# Header names seen in the wild, per target field. Matching is loose: case,
# spaces and punctuation are ignored. Korean headers are listed beside the
# English ones, because the spreadsheets that come out of the factory are
# written in Korean and should not have to be retyped.
ALIASES = {
    "order_no": ("orderno", "ordernumber", "order", "salesorder", "sonumber",
                 "so", "sono", "orderid", "reference", "ourref", "jobno",
                 "주문번호", "수주번호", "오더번호"),
    "po_number": ("po", "pono", "ponumber", "purchaseorder", "customerpo",
                  "custpo", "yourref", "buyerref", "발주번호", "고객발주번호"),
    "company": ("company", "customer", "customername", "client", "account",
                "accountname", "buyer", "soldto", "companyname",
                "거래처", "고객사", "업체", "업체명", "거래처명"),
    "product_code": ("productcode", "productno", "productnumber", "partno",
                     "partnumber", "pn", "pncode", "itemcode", "itemno",
                     "sku", "modelno", "articleno", "drawingno",
                     "관리번호", "품번", "모델번호"),
    "product_name": ("productname", "product", "model", "modelname",
                     "itemname", "boardname", "partname",
                     "모델이름", "모델명", "품명", "제품명"),
    "work_order_no": ("workorderno", "workorder", "worksheetno", "joborderno",
                      "jobnumber", "worksorderno", "wono",
                      "작지번호", "작지", "작업지시번호", "작업번호"),
    "description": ("description", "details", "summary",
                    "lineitem", "goods", "partdescription"),
    "status": ("status", "orderstatus", "stage", "state", "progress",
               "상태", "진행상태", "진행"),
    "value": ("value", "amount", "total", "nettotal", "ordervalue", "price",
              "totalvalue", "netamount", "revenue", "금액", "수주금액", "단가"),
    "currency": ("currency", "curr", "ccy"),
    "order_date": ("orderdate", "date", "dateordered", "created", "placed",
                   "orderreceived", "수주일", "주문일", "수주일자"),
    "promise_date": ("promisedate", "duedate", "delivery", "deliverydate",
                     "requireddate", "eta", "promised", "targetdate",
                     "requesteddelivery", "shipby", "납기", "납기일",
                     "납기일자", "납품일"),
    "ship_date": ("shipdate", "shipped", "dispatchdate", "despatched",
                  "actualship", "출하일", "출고일", "선적일"),
    "owner": ("owner", "salesrep", "rep", "accountmanager", "salesperson",
              "assignedto", "responsible", "담당자", "영업담당"),
    "priority": ("priority", "urgency"),
    "notes": ("notes", "comment", "comments", "remarks", "memo", "비고", "메모"),
}

FIELDS = tuple(ALIASES.keys())


def _norm(text: str) -> str:
    """A header reduced to what matters: case, spaces and punctuation go.

    Hangul is kept, so a column headed "작 지 번 호" still matches.
    """
    return re.sub(r"[^a-z0-9\uac00-\ud7a3]+", "", (text or "").lower())


def suggest_mapping(headers) -> dict:
    """Guess {field: column index} from a header row."""
    mapping = {}
    used = set()
    normalised = [_norm(h) for h in headers]

    for field, aliases in ALIASES.items():
        for index, header in enumerate(normalised):
            if index in used or not header:
                continue
            if header == _norm(field) or header in aliases:
                mapping[field] = index
                used.add(index)
                break

    # Second pass: allow a partial match for anything still unmapped.
    for field, aliases in ALIASES.items():
        if field in mapping:
            continue
        for index, header in enumerate(normalised):
            if index in used or not header:
                continue
            if any(alias in header or header in alias for alias in aliases if len(alias) > 3):
                mapping[field] = index
                used.add(index)
                break
    return mapping


def read_table(data: bytes, filename: str) -> list[list[str]]:
    """Rows from a CSV or XLSX payload, header row included."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        with io.BytesIO(data) as buf, Workbook(buf) as wb:
            return [row for row in wb.rows(0)]

    text = data.decode("utf-8-sig", "replace")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def preview(data: bytes, filename: str, sample_size: int = 8) -> dict:
    rows = read_table(data, filename)
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return {"headers": [], "rows": [], "mapping": {}, "total": 0,
                "error": "That file has no rows in it."}
    headers = [str(c).strip() for c in rows[0]]
    body = rows[1:]
    return {
        "headers": headers,
        "rows": body[:sample_size],
        "mapping": suggest_mapping(headers),
        "total": len(body),
        "fields": list(FIELDS),
    }


def run_import(data: bytes, filename: str, mapping: dict,
               update_existing: bool = True, default_status: str = "",
               actor: str = "") -> dict:
    """Apply an import. Returns a per-row summary of what happened."""
    rows = read_table(data, filename)
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return {"created": 0, "updated": 0, "skipped": 0, "errors": ["The file is empty."]}

    body = rows[1:]
    mapping = {field: int(index) for field, index in mapping.items()
               if str(index).strip() != "" and int(index) >= 0}

    if "order_no" not in mapping:
        return {"created": 0, "updated": 0, "skipped": 0,
                "errors": ["No column is mapped to the order number, so rows "
                           "cannot be matched. Map one and try again."]}

    conn = db.connect()
    created = updated = skipped = 0
    errors = []

    for line_no, row in enumerate(body, start=2):
        def cell(field):
            index = mapping.get(field)
            if index is None or index >= len(row):
                return ""
            return str(row[index]).strip()

        order_no = cell("order_no")
        if not order_no:
            skipped += 1
            continue

        record = {field: cell(field) for field in mapping}
        record.pop("company_id", None)

        status = (record.get("status") or default_status or "").strip().upper()
        record["status"] = _map_status(status)
        if not record.get("company"):
            record["company"] = "(unassigned)"

        existing = conn.execute(
            "SELECT id FROM orders WHERE order_no = ?", (order_no,)
        ).fetchone()

        try:
            if existing:
                if not update_existing:
                    skipped += 1
                    continue
                # Do not blank out fields the spreadsheet simply omits.
                changes = {k: v for k, v in record.items() if v not in ("", None)}
                orders.update_order(existing["id"], changes, actor=actor,
                                    note=f"updated from {filename}")
                updated += 1
            else:
                orders.create_order(record, actor=actor)
                created += 1
        except orders.OrderError as exc:
            errors.append(f"row {line_no} ({order_no}): {exc}")
        except Exception as exc:  # keep importing the rest of the file
            errors.append(f"row {line_no} ({order_no}): {exc}")

    return {"created": created, "updated": updated, "skipped": skipped,
            "errors": errors[:50], "error_count": len(errors)}


def _map_status(raw: str) -> str:
    """Fit an incoming status onto the configured pipeline."""
    from . import config

    if not raw:
        return config.PIPELINE[0]
    candidate = raw.strip().upper()
    if candidate in config.ALL_STATUSES:
        return candidate

    flat = _norm(candidate)
    for status in config.ALL_STATUSES:
        if _norm(status) == flat:
            return status

    synonyms = {
        "open": "ORDER RECEIVED", "new": "ORDER RECEIVED",
        "pending": "ORDER RECEIVED", "received": "ORDER RECEIVED",
        "acknowledged": "CONFIRMED", "accepted": "CONFIRMED",
        "confirmed": "CONFIRMED", "wip": "IN PRODUCTION",
        "inprogress": "IN PRODUCTION", "manufacturing": "IN PRODUCTION",
        "production": "IN PRODUCTION", "ready": "READY TO SHIP",
        "picked": "READY TO SHIP", "dispatched": "SHIPPED",
        "despatched": "SHIPPED", "intransit": "SHIPPED",
        "complete": "DELIVERED", "completed": "DELIVERED",
        "closed": "PAID", "invoiced": "INVOICED", "billed": "INVOICED",
        "paid": "PAID", "settled": "PAID", "cancelled": "CANCELLED",
        "canceled": "CANCELLED", "void": "CANCELLED", "hold": "ON HOLD",
        "onhold": "ON HOLD", "quoted": "QUOTE", "quotation": "QUOTE",
    }
    return synonyms.get(flat, config.PIPELINE[0])
