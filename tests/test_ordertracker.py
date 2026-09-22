"""Tests for Order Tracker. Run with: python3 -m unittest discover tests"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ordertracker import config  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="ordertracker-test-"))
config.DATA_DIR = _TMP
config.DOCS_DIR = _TMP / "documents"
config.DB_PATH = _TMP / "test.db"

import fixtures  # noqa: E402
from ordertracker import (db, documents, importer, multipart,  # noqa: E402
                          orders, sampledata)
from ordertracker.extract import extract_text  # noqa: E402


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


def fresh_db():
    """Empty every table so each test starts from a known state."""
    db.init_db()
    conn = db.connect()
    with conn:
        for table in ("status_history", "documents", "orders", "companies",
                      "orders_fts", "documents_fts"):
            conn.execute(f"DELETE FROM {table}")
    for stored in config.DOCS_DIR.glob("*"):
        stored.unlink()


# --------------------------------------------------------------- extraction

class TestExtraction(unittest.TestCase):

    def test_pdf_text_is_recovered(self):
        path = fixtures.make_pdf(
            ["PURCHASE ORDER", "PO Number: PO-2026-44817",
             "Buyer: Northwind Industrial GmbH", "Total USD 10,780.00"],
            _TMP / "po.pdf")
        text, note = extract_text(path)
        self.assertEqual(note, "")
        self.assertIn("PO-2026-44817", text)
        self.assertIn("Northwind Industrial GmbH", text)
        self.assertIn("10,780.00", text)

    def test_pdf_with_no_text_layer_reports_why(self):
        path = _TMP / "scan.pdf"
        path.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n")
        text, note = extract_text(path)
        self.assertEqual(text, "")
        self.assertIn("scan", note)

    def test_email_body_and_pdf_attachment_are_both_indexed(self):
        import email.message

        pdf = fixtures.make_pdf(["PACKING LIST", "Carrier MF-88213"], _TMP / "pk.pdf")
        msg = email.message.EmailMessage()
        msg["From"] = "Marta Lindqvist <marta@northwind-ind.example>"
        msg["Subject"] = "PO-2026-44817 revised date"
        msg.set_content("Please confirm delivery on 14 November.")
        msg.add_attachment(pdf.read_bytes(), maintype="application",
                           subtype="pdf", filename="packing.pdf")
        path = _TMP / "mail.eml"
        path.write_bytes(msg.as_bytes())

        text, _ = extract_text(path)
        self.assertIn("Marta Lindqvist", text)
        self.assertIn("14 November", text)
        self.assertIn("MF-88213", text)          # from inside the attachment

    def test_unknown_file_type_is_not_an_error(self):
        path = _TMP / "thing.dwg"
        path.write_bytes(b"\x00\x01binary")
        text, note = extract_text(path)
        self.assertEqual(text, "")
        self.assertTrue(note)


class TestSpreadsheetReader(unittest.TestCase):

    def test_reads_values_and_converts_date_serials(self):
        path = fixtures.make_xlsx([
            ["Order No", "Customer", "Value", "Promise Date"],
            ["SO-1001", "Northwind Industrial GmbH", 10780.0, "2026-11-14"],
            ["SO-1002", "Acme Components Ltd", 4250.5, "2026-10-02"],
        ], _TMP / "orders.xlsx", date_columns={3})

        from ordertracker.xlsx import read_rows, sheet_names
        self.assertEqual(sheet_names(path), ["Orders"])
        rows = read_rows(path)
        self.assertEqual(rows[1][0], "SO-1001")
        self.assertEqual(rows[1][3], "2026-11-14")
        self.assertEqual(rows[2][2], "4250.5")


class TestMultipart(unittest.TestCase):

    def test_parses_binary_files_and_fields(self):
        boundary = "----B1"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="order_id"\r\n\r\n7\r\n'
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="a b.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode() + b"%PDF\x00\xff\r\n" + f"--{boundary}--\r\n".encode()

        fields = multipart.parse(body, f"multipart/form-data; boundary={boundary}")
        self.assertEqual(multipart.value(fields, "order_id"), "7")
        part = multipart.first(fields, "files")
        self.assertEqual(part.filename, "a b.pdf")
        self.assertEqual(part.data, b"%PDF\x00\xff")


# -------------------------------------------------------------------- dates

class TestDateParsing(unittest.TestCase):

    def test_unambiguous_forms_always_work(self):
        for raw in ("2026-12-03", "3-Dec-2026", "2026/12/03", "20261203"):
            self.assertEqual(orders.normalise_date(raw), "2026-12-03", raw)

    def test_slash_dates_follow_the_configured_order(self):
        original = config.DATE_INPUT_ORDER
        try:
            config.DATE_INPUT_ORDER = "MDY"
            self.assertEqual(orders.normalise_date("12/03/2026"), "2026-12-03")
            config.DATE_INPUT_ORDER = "DMY"
            self.assertEqual(orders.normalise_date("03/12/2026"), "2026-12-03")
        finally:
            config.DATE_INPUT_ORDER = original

    def test_unreadable_date_is_kept_rather_than_dropped(self):
        self.assertEqual(orders.normalise_date("whenever"), "whenever")

    def test_an_absent_date_stays_absent(self):
        """It must never be stored as the text "None"."""
        for empty in (None, "", "   "):
            with self.subTest(empty=empty):
                self.assertIsNone(orders.normalise_date(empty))

    def test_stored_timestamps_parse_back_to_their_date(self):
        """Alert logic reads updated_at, which carries a clock time."""
        import datetime
        for raw in ("2026-08-25 09:00:00", "2026-08-25T09:00:00Z",
                    "2026-08-25 09:00"):
            with self.subTest(raw=raw):
                self.assertEqual(orders._parse_date(raw),
                                 datetime.date(2026, 8, 25))

    def test_long_month_names_are_understood(self):
        self.assertEqual(orders.normalise_date("3-December-2026"), "2026-12-03")
        self.assertEqual(orders.normalise_date("3 Dec 2026"), "2026-12-03")


# ------------------------------------------------------------------- orders

class TestOrders(unittest.TestCase):

    def setUp(self):
        fresh_db()

    def test_create_records_history_and_makes_the_company(self):
        order_id = orders.create_order(
            {"order_no": "SO-1", "company": "Kestrel Marine Systems",
             "value": "1,250.50", "status": "CONFIRMED"}, actor="test")
        order = orders.get_order(order_id)
        self.assertEqual(order["company"], "Kestrel Marine Systems")
        self.assertEqual(order["value"], 1250.5)
        self.assertEqual(len(order["history"]), 1)
        self.assertEqual(len(orders.list_companies()), 1)

    def test_an_order_with_no_dates_stores_them_as_absent(self):
        """A blank promise date must not show up in the blotter as "None"."""
        order_id = orders.create_order({"order_no": "SO-NODATE", "company": "A"})
        order = orders.get_order(order_id)
        self.assertIsNone(order["promise_date"])
        self.assertIsNone(order["order_date"])
        self.assertIsNone(order["ship_date"])
        self.assertIsNone(order["days_to_promise"])

    def test_dates_stored_as_the_text_none_are_repaired(self):
        """Data written by an earlier version must be cleaned up on startup."""
        order_id = orders.create_order({"order_no": "SO-OLD", "company": "A"})
        conn = db.connect()
        with conn:
            conn.execute("UPDATE orders SET promise_date = 'None', "
                         "order_date = 'None' WHERE id = ?", (order_id,))

        db.init_db()
        order = orders.get_order(order_id)
        self.assertIsNone(order["promise_date"])
        self.assertIsNone(order["order_date"])

    def test_duplicate_order_number_is_refused(self):
        orders.create_order({"order_no": "SO-1", "company": "A"})
        with self.assertRaises(orders.OrderError):
            orders.create_order({"order_no": "SO-1", "company": "B"})

    def test_status_change_is_written_to_history(self):
        order_id = orders.create_order({"order_no": "SO-1", "company": "A",
                                        "status": "CONFIRMED"})
        orders.update_order(order_id, {"status": "SHIPPED"}, note="left the dock")
        order = orders.get_order(order_id)
        self.assertEqual(order["status"], "SHIPPED")
        self.assertEqual(order["history"][0]["from_status"], "CONFIRMED")
        self.assertEqual(order["history"][0]["note"], "left the dock")

    def test_unknown_status_is_refused(self):
        order_id = orders.create_order({"order_no": "SO-1", "company": "A"})
        with self.assertRaises(orders.OrderError):
            orders.update_order(order_id, {"status": "MADE UP"})

    def test_overdue_and_due_soon_flags(self):
        import datetime
        today = datetime.date.today()
        late = orders.create_order({
            "order_no": "SO-LATE", "company": "A", "status": "IN PRODUCTION",
            "promise_date": (today - datetime.timedelta(days=3)).isoformat()})
        soon = orders.create_order({
            "order_no": "SO-SOON", "company": "A", "status": "IN PRODUCTION",
            "promise_date": (today + datetime.timedelta(days=2)).isoformat()})
        calm = orders.create_order({
            "order_no": "SO-CALM", "company": "A", "status": "IN PRODUCTION",
            "promise_date": (today + datetime.timedelta(days=90)).isoformat()})

        self.assertIn("OVERDUE", orders.get_order(late)["alerts"])
        self.assertIn("DUE SOON", orders.get_order(soon)["alerts"])
        self.assertNotIn("OVERDUE", orders.get_order(calm)["alerts"])
        self.assertNotIn("DUE SOON", orders.get_order(calm)["alerts"])

    def test_an_untouched_order_is_flagged_as_stalled(self):
        import datetime
        order_id = orders.create_order({"order_no": "SO-QUIET", "company": "A",
                                        "status": "IN PRODUCTION"})
        stale = datetime.date.today() - datetime.timedelta(
            days=config.STALLED_DAYS + 5)
        conn = db.connect()
        with conn:
            conn.execute("UPDATE orders SET updated_at = ? WHERE id = ?",
                         (stale.isoformat() + " 09:00:00", order_id))

        self.assertIn("STALLED", orders.get_order(order_id)["alerts"])
        self.assertEqual(orders.dashboard()["alerts"]["STALLED"], 1)

    def test_a_recently_touched_order_is_not_stalled(self):
        order_id = orders.create_order({"order_no": "SO-BUSY", "company": "A",
                                        "status": "IN PRODUCTION"})
        self.assertNotIn("STALLED", orders.get_order(order_id)["alerts"])

    def test_closed_orders_raise_no_flags(self):
        import datetime
        order_id = orders.create_order({
            "order_no": "SO-PAID", "company": "A", "status": "PAID",
            "promise_date": (datetime.date.today() - datetime.timedelta(days=90)).isoformat()})
        self.assertEqual(orders.get_order(order_id)["alerts"], [])

    def test_missing_po_is_flagged_once_the_order_is_confirmed(self):
        order_id = orders.create_order({"order_no": "SO-1", "company": "A",
                                        "status": "CONFIRMED"})
        self.assertIn("NO PO", orders.get_order(order_id)["alerts"])

        documents.store("PO-991 purchase order.pdf",
                        fixtures.make_pdf(["PURCHASE ORDER", "PO-991"],
                                          _TMP / "po991.pdf").read_bytes(),
                        order_id=order_id)
        self.assertNotIn("NO PO", orders.get_order(order_id)["alerts"])

    def test_quote_stage_does_not_demand_a_po(self):
        order_id = orders.create_order({"order_no": "SO-Q", "company": "A",
                                        "status": "QUOTE"})
        self.assertNotIn("NO PO", orders.get_order(order_id)["alerts"])

    def test_deleting_an_order_removes_its_documents(self):
        order_id = orders.create_order({"order_no": "SO-1", "company": "A"})
        doc = documents.store("note.txt", b"hello", order_id=order_id)
        stored = config.DOCS_DIR / doc["stored_name"]
        self.assertTrue(stored.exists())

        orders.delete_order(order_id)
        self.assertIsNone(orders.get_order(order_id))
        self.assertFalse(stored.exists())
        self.assertEqual(orders.search("hello")["documents"], [])

    def test_filters_and_sorting(self):
        orders.create_order({"order_no": "SO-1", "company": "A", "value": 100,
                             "status": "CONFIRMED", "owner": "R. Kim"})
        orders.create_order({"order_no": "SO-2", "company": "B", "value": 900,
                             "status": "PAID", "owner": "J. Alvarez"})

        self.assertEqual(len(orders.list_orders()), 2)
        self.assertEqual(len(orders.list_orders(include_closed=False)), 1)
        self.assertEqual(len(orders.list_orders(owner="R. Kim")), 1)
        self.assertEqual(len(orders.list_orders(status="PAID")), 1)

        by_value = orders.list_orders(sort="value", direction="desc")
        self.assertEqual(by_value[0]["order_no"], "SO-2")


# ------------------------------------------------------------------- search

class TestSearch(unittest.TestCase):

    def setUp(self):
        fresh_db()
        self.order_id = orders.create_order({
            "order_no": "SO-2603", "company": "Kestrel Marine Systems",
            "po_number": "PO-2026-44817", "description": "HX-440 heat exchanger",
            "status": "IN PRODUCTION"})

    def test_finds_orders_by_any_reference(self):
        for term in ("kestrel", "SO-2603", "44817", "heat exchanger", "SO-26"):
            with self.subTest(term=term):
                found = orders.search(term)["orders"]
                self.assertTrue(found, f"nothing found for {term!r}")
                self.assertEqual(found[0]["order_no"], "SO-2603")

    def test_finds_words_inside_a_stored_pdf(self):
        pdf = fixtures.make_pdf(
            ["PACKING LIST", "Carrier: Meridian Freight", "Tracking MF-88213"],
            _TMP / "packing.pdf")
        documents.store("packing.pdf", pdf.read_bytes(), order_id=self.order_id)

        result = orders.search("meridian")
        self.assertEqual(len(result["documents"]), 1)
        self.assertIn("Meridian", result["documents"][0]["snippet"])
        self.assertEqual(result["documents"][0]["order_no"], "SO-2603")

    def test_search_survives_punctuation_people_type(self):
        for term in ("PO-2026-44817", 'kestrel "heat exchanger"', "SO-2603!"):
            with self.subTest(term=term):
                self.assertNotIn("error", orders.search(term))

    def test_edits_are_reflected_in_later_searches(self):
        orders.update_order(self.order_id, {"description": "VLV-318 ball valve"})
        self.assertTrue(orders.search("ball valve")["orders"])
        self.assertFalse(orders.search("heat exchanger")["orders"])


# ---------------------------------------------------------------- documents

class TestDocuments(unittest.TestCase):

    def setUp(self):
        fresh_db()

    def test_identical_uploads_are_stored_once(self):
        order_id = orders.create_order({"order_no": "SO-1", "company": "A"})
        first = documents.store("po.txt", b"same bytes", order_id=order_id)
        second = documents.store("po.txt", b"same bytes", order_id=order_id)
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(documents.list_documents(order_id=order_id)), 1)

    def test_kind_is_guessed_from_the_filename(self):
        order_id = orders.create_order({"order_no": "SO-1", "company": "A"})
        cases = {"PO-2026 purchase order.pdf": "PO",
                 "Invoice 4471.pdf": "INVOICE",
                 "signed contract.pdf": "CONTRACT",
                 "packing list scan.pdf": "PACKING LIST",
                 "random thing.pdf": "OTHER",
                 # A reference number must not drag a file into the wrong kind.
                 "RE PO-2026-22337 delivery schedule.eml": "EMAIL",
                 "Invoice for PO-2026-4481.pdf": "INVOICE",
                 "Deposit receipt.pdf": "OTHER",
                 "exposition notes.pdf": "OTHER"}
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                doc = documents.store(filename, filename.encode(), order_id=order_id)
                self.assertEqual(doc["kind"], expected)

    def test_a_loose_file_is_filed_by_the_order_it_names(self):
        order_id = orders.create_order({"order_no": "SO-2603", "company": "A"})
        orders.create_order({"order_no": "SO-9999", "company": "B"})

        pdf = fixtures.make_pdf(["PACKING LIST", "Against sales order SO-2603"],
                                _TMP / "loose.pdf")
        doc = documents.store("packing list scan.pdf", pdf.read_bytes())
        self.assertIsNone(doc["order_id"])

        self.assertEqual(documents.autofile(doc["id"]), order_id)
        self.assertEqual(documents.get(doc["id"])["order_id"], order_id)

    def test_a_file_naming_two_orders_is_left_alone(self):
        orders.create_order({"order_no": "SO-2603", "company": "A"})
        orders.create_order({"order_no": "SO-2604", "company": "B"})
        pdf = fixtures.make_pdf(["Covers SO-2603 and SO-2604"], _TMP / "both.pdf")
        doc = documents.store("both.pdf", pdf.read_bytes())

        self.assertIsNone(documents.autofile(doc["id"]))
        self.assertIsNone(documents.get(doc["id"])["order_id"])

    def test_oversized_upload_is_refused(self):
        original = config.MAX_UPLOAD_BYTES
        try:
            config.MAX_UPLOAD_BYTES = 10
            with self.assertRaises(ValueError):
                documents.store("big.txt", b"x" * 50)
        finally:
            config.MAX_UPLOAD_BYTES = original

    def test_stored_filenames_cannot_escape_the_documents_folder(self):
        order_id = orders.create_order({"order_no": "SO-1", "company": "A"})
        doc = documents.store("../../etc/passwd", b"nope", order_id=order_id)
        stored = documents.path_for(doc).resolve()
        self.assertEqual(stored.parent, config.DOCS_DIR.resolve())


# ------------------------------------------------------------------ imports

class TestImporter(unittest.TestCase):

    def setUp(self):
        fresh_db()

    def test_column_names_are_matched_to_fields(self):
        mapping = importer.suggest_mapping(
            ["Sales Order #", "Customer Name", "Customer PO", "Order Status",
             "Net Value", "Requested Delivery", "Account Manager"])
        self.assertEqual(mapping["order_no"], 0)
        self.assertEqual(mapping["company"], 1)
        self.assertEqual(mapping["po_number"], 2)
        self.assertEqual(mapping["status"], 3)
        self.assertEqual(mapping["value"], 4)
        self.assertEqual(mapping["promise_date"], 5)
        self.assertEqual(mapping["owner"], 6)

    def test_csv_import_creates_then_updates(self):
        csv_bytes = (
            "Order No,Customer,Status,Value,Promise Date\n"
            "SO-1,Northwind Industrial GmbH,in progress,10780,2026-11-14\n"
            "SO-2,Acme Components Ltd,dispatched,4250.50,2026-10-02\n"
        ).encode()
        mapping = {"order_no": 0, "company": 1, "status": 2, "value": 3,
                   "promise_date": 4}

        result = importer.run_import(csv_bytes, "book.csv", mapping)
        self.assertEqual((result["created"], result["updated"]), (2, 0))

        first = orders.list_orders(sort="order_no")[0]
        self.assertEqual(first["status"], "IN PRODUCTION")   # "in progress"
        self.assertEqual(first["value"], 10780.0)

        again = importer.run_import(csv_bytes, "book.csv", mapping)
        self.assertEqual((again["created"], again["updated"]), (0, 2))
        self.assertEqual(len(orders.list_orders()), 2)

    def test_semicolon_files_are_understood(self):
        data = b"Order No;Customer;Value\nSO-9;Helios Energy Partners;1500\n"
        preview = importer.preview(data, "export.csv")
        self.assertEqual(preview["headers"][0], "Order No")
        self.assertEqual(preview["total"], 1)

    def test_xlsx_import(self):
        path = fixtures.make_xlsx([
            ["Order No", "Customer", "Status", "Promise Date"],
            ["SO-X1", "Pinnacle Aerospace", "confirmed", "2026-11-14"],
        ], _TMP / "import.xlsx", date_columns={3})

        result = importer.run_import(path.read_bytes(), "import.xlsx",
                                     {"order_no": 0, "company": 1, "status": 2,
                                      "promise_date": 3})
        self.assertEqual(result["created"], 1)
        order = orders.list_orders()[0]
        self.assertEqual(order["status"], "CONFIRMED")
        self.assertEqual(order["promise_date"], "2026-11-14")

    def test_import_without_an_order_number_column_is_refused(self):
        result = importer.run_import(b"A,B\n1,2\n", "x.csv", {"company": 0})
        self.assertEqual(result["created"], 0)
        self.assertTrue(result["errors"])

    def test_one_bad_row_does_not_stop_the_rest(self):
        data = b"Order No,Customer\nSO-1,Acme\n,MissingNumber\nSO-3,Acme\n"
        result = importer.run_import(data, "x.csv", {"order_no": 0, "company": 1})
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["skipped"], 1)

    def test_an_update_does_not_blank_columns_the_file_omits(self):
        orders.create_order({"order_no": "SO-1", "company": "Acme",
                             "owner": "R. Kim", "description": "brackets"})
        importer.run_import(b"Order No,Status\nSO-1,shipped\n", "x.csv",
                            {"order_no": 0, "status": 1})
        order = orders.list_orders()[0]
        self.assertEqual(order["status"], "SHIPPED")
        self.assertEqual(order["owner"], "R. Kim")
        self.assertEqual(order["description"], "brackets")


# ---------------------------------------------------------------------- api

class TestHttpApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        fresh_db()
        from ordertracker import server
        cls.httpd = server.serve("127.0.0.1", 8811)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:8811"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as response:
            return response.status, response.read()

    def post(self, path, payload):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_the_page_and_its_assets_are_served(self):
        for path in ("/", "/app.js", "/style.css"):
            with self.subTest(path=path):
                code, body = self.get(path)
                self.assertEqual(code, 200)
                self.assertTrue(body)

    def test_bootstrap_describes_the_configuration(self):
        code, body = self.get("/api/bootstrap")
        data = json.loads(body)
        self.assertEqual(code, 200)
        self.assertIn("IN PRODUCTION", data["pipeline"])
        self.assertIn("dashboard", data)

    def test_create_read_and_update_over_http(self):
        code, created = self.post("/api/orders", {
            "order_no": "SO-HTTP-1", "company": "Vantage Medical Supply",
            "value": "2,500", "status": "CONFIRMED"})
        self.assertEqual(code, 200)
        order_id = created["id"]

        code, detail = self.get(f"/api/orders/{order_id}")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(detail)["value"], 2500.0)

        code, updated = self.post(f"/api/orders/{order_id}", {"status": "SHIPPED"})
        self.assertEqual(updated["order"]["status"], "SHIPPED")

    def test_errors_come_back_as_json_not_a_stack_trace(self):
        code, body = self.post("/api/orders", {"company": "No Number Co"})
        self.assertEqual(code, 400)
        self.assertIn("order number", body["error"])

    def test_a_missing_order_is_a_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/orders/999999")
        self.assertEqual(caught.exception.code, 404)

    def test_static_paths_cannot_escape_the_web_folder(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/../ordertracker/config.py")
        self.assertIn(caught.exception.code, (403, 404))

    def test_requests_under_another_hostname_are_refused(self):
        request = urllib.request.Request(self.base + "/api/bootstrap",
                                         headers={"Host": "attacker.example"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)

    def test_upload_over_http_indexes_the_file(self):
        code, created = self.post("/api/orders", {
            "order_no": "SO-HTTP-2", "company": "Acme Components Ltd"})
        order_id = created["id"]

        pdf = fixtures.make_pdf(["INVOICE", "Reference QX-55219"],
                                _TMP / "upload.pdf").read_bytes()
        boundary = "----T1"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="order_id"\r\n\r\n{order_id}\r\n'
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="invoice.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode() + pdf + f"\r\n--{boundary}--\r\n".encode()

        request = urllib.request.Request(
            self.base + "/api/documents/upload", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read())

        self.assertEqual(len(result["saved"]), 1)
        self.assertEqual(result["saved"][0]["kind"], "INVOICE")

        code, body = self.get("/api/search?q=QX-55219")
        self.assertEqual(len(json.loads(body)["documents"]), 1)

    def test_csv_export(self):
        code, body = self.get("/api/export/orders.csv")
        self.assertEqual(code, 200)
        self.assertIn(b"order_no", body)


class TestStorageFailures(unittest.TestCase):
    """A locked-down data folder must explain itself, not raise a traceback."""

    def test_unopenable_database_raises_a_readable_error(self):
        import sqlite3

        real_connect = sqlite3.connect
        sqlite3.connect = lambda *a, **k: (_ for _ in ()).throw(
            sqlite3.OperationalError("unable to open database file"))
        db._local.__dict__.clear()
        try:
            with self.assertRaises(db.StorageError) as caught:
                db.connect()
        finally:
            sqlite3.connect = real_connect
            db._local.__dict__.clear()

        message = str(caught.exception)
        self.assertIn(str(config.DB_PATH), message)
        self.assertIn("doctor.py", message)
        self.assertIn("--data", message)

    def test_the_database_folder_is_created_if_missing(self):
        db._local.__dict__.clear()
        target = _TMP / "made-on-demand"
        original = config.DB_PATH
        config.DB_PATH = target / "orders.db"
        try:
            db.connect()
            self.assertTrue(target.exists())
        finally:
            config.DB_PATH = original
            db._local.__dict__.clear()


# ----------------------------------------------------------------- settings

class TestSettings(unittest.TestCase):
    """Where the data lives is remembered outside the app folder."""

    def setUp(self):
        from ordertracker import settings
        self.settings = settings
        self.home = Path(tempfile.mkdtemp(prefix="ot-settings-"))
        self._env = {k: os.environ.get(k) for k in
                     ("XDG_CONFIG_HOME", "LOCALAPPDATA", "HOME")}
        os.environ["XDG_CONFIG_HOME"] = str(self.home)
        os.environ["LOCALAPPDATA"] = str(self.home)
        os.environ["HOME"] = str(self.home)

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.home, ignore_errors=True)

    def test_defaults_apply_when_nothing_is_saved(self):
        values = self.settings.load()
        self.assertEqual(values["workspace"], "")
        self.assertTrue(values["show_welcome"])

    def test_saved_values_come_back(self):
        self.settings.save(workspace=str(self.home / "drive"), welcome_name="Rachel")
        values = self.settings.load()
        self.assertEqual(values["welcome_name"], "Rachel")
        self.assertEqual(self.settings.workspace(), (self.home / "drive").resolve())

    def test_a_damaged_settings_file_falls_back_to_defaults(self):
        path = self.settings.settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json at all", encoding="utf-8")
        self.assertEqual(self.settings.load()["workspace"], "")

    def test_unknown_keys_are_ignored(self):
        path = self.settings.settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"workspace": "/x", "nonsense": 1}), encoding="utf-8")
        self.assertNotIn("nonsense", self.settings.load())


class TestShortcut(unittest.TestCase):

    @unittest.skipIf(sys.platform == "win32", "the .lnk path needs PowerShell")
    def test_a_launcher_is_written_to_the_desktop(self):
        from ordertracker import shortcut

        desktop = Path(tempfile.mkdtemp(prefix="ot-desktop-"))
        previous_desktop = os.environ.get("XDG_DESKTOP_DIR")
        previous_home = os.environ.get("HOME")
        os.environ["XDG_DESKTOP_DIR"] = str(desktop)
        os.environ["HOME"] = str(desktop.parent)
        try:
            link = shortcut.create()
            self.assertTrue(link.exists())
            body = link.read_text()
            self.assertIn("run.py", body)
            self.assertIn(str(config.BASE_DIR), body)
        finally:
            for key, value in (("XDG_DESKTOP_DIR", previous_desktop),
                               ("HOME", previous_home)):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(desktop, ignore_errors=True)


# ------------------------------------------------------------------ samples

class TestDemoData(unittest.TestCase):

    def test_demo_data_loads_and_raises_realistic_flags(self):
        fresh_db()
        counts = sampledata.load()
        self.assertGreater(counts["orders"], 20)
        self.assertGreater(counts["documents"], 20)

        board = orders.dashboard()
        self.assertGreater(board["open_orders"], 0)
        self.assertGreater(board["alerts"]["OVERDUE"], 0)
        self.assertTrue(orders.search("northwind")["orders"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
