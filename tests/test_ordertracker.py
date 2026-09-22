"""Tests for Order Tracker. Run with: python3 -m unittest discover tests"""

import datetime
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
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
from ordertracker import (backup, cases, db, documents, geo,  # noqa: E402
                          importer, mail, multipart, orders, outlook, pcb,
                          prefs, printsheet, sampledata)
from ordertracker.extract import extract_text  # noqa: E402


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


def fresh_db():
    """Empty every table so each test starts from a known state."""
    db.init_db()
    conn = db.connect()
    with conn:
        for table in ("status_history", "documents", "order_specs",
                      "case_entries", "cases", "emails", "orders",
                      "companies", "orders_fts", "documents_fts"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM meta WHERE key = 'prefs'")
    prefs.forget_cache()
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

    def test_non_latin_filenames_keep_their_name_and_extension(self):
        """A Korean or accented filename must survive being stored.

        Losing the extension would also lose the text extraction, because
        the reader is chosen by extension.
        """
        cases = {
            "주문서 PO-2026-44817.pdf": "주문서 PO-2026-44817.pdf",
            "김영진 견적서.xlsx": "김영진 견적서.xlsx",
            "발주서.eml": "발주서.eml",
            "ünïcödé fïle.docx": "ünïcödé fïle.docx",
        }
        for given, expected in cases.items():
            with self.subTest(given=given):
                self.assertEqual(documents.safe_name(given), expected)

    def test_awkward_filenames_are_made_safe(self):
        self.assertEqual(documents.safe_name("../../etc/passwd"), "passwd")
        self.assertEqual(documents.safe_name(r"C:\evil\path.pdf"), "path.pdf")
        self.assertEqual(documents.safe_name("CON.txt"), "_CON.txt")
        self.assertEqual(documents.safe_name(""), "file")
        self.assertNotIn("?", documents.safe_name("weird<>:|?.pdf"))

    def test_a_very_long_name_is_trimmed_without_splitting_a_character(self):
        name = documents.safe_name("한" * 400 + ".pdf")
        self.assertTrue(name.endswith(".pdf"))
        self.assertLessEqual(len(name.encode("utf-8")), 200)
        name.encode("utf-8").decode("utf-8")   # no half character at the end

    def test_a_korean_named_pdf_is_indexed_and_searchable(self):
        order_id = orders.create_order({"order_no": "SO-9001",
                                        "company": "대한정밀 주식회사"})
        pdf = fixtures.make_pdf(["PURCHASE ORDER", "Meridian Freight MF-88213"],
                                _TMP / "korean.pdf")
        doc = documents.store("주문서 PO-2026-44817.pdf", pdf.read_bytes(),
                              order_id=order_id)

        self.assertTrue(doc["stored_name"].endswith(".pdf"))
        self.assertIn("Meridian", doc["content_text"])
        self.assertEqual(doc["kind"], "PO")

        found = orders.search("meridian")["documents"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["filename"], "주문서 PO-2026-44817.pdf")
        self.assertTrue(orders.search("대한정밀")["orders"])

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

    def test_a_write_from_another_site_is_refused(self):
        """A page on some other site must not be able to change anything."""
        request = urllib.request.Request(
            self.base + "/api/orders",
            data=json.dumps({"order_no": "SO-EVIL", "company": "Evil"}).encode(),
            headers={"Content-Type": "application/json",
                     "Origin": "http://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)

    def test_a_write_from_our_own_page_is_allowed(self):
        request = urllib.request.Request(
            self.base + "/api/orders",
            data=json.dumps({"order_no": "SO-OWN", "company": "Acme"}).encode(),
            headers={"Content-Type": "application/json",
                     "Origin": self.base})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)

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
        self.assertIn("setup.py --folder", message)

    def test_the_message_says_which_of_the_causes_it_actually_is(self):
        """"Unable to open database file" covers several different problems.
        The folder is probed at the moment it fails so the message can name
        the one in front of you instead of listing all of them."""
        import sqlite3

        folder = Path(tempfile.mkdtemp(prefix="ot-locked-"))
        saved = (config.DATA_DIR, config.DOCS_DIR, config.DB_PATH)
        config.DATA_DIR = folder
        config.DOCS_DIR = folder / "documents"
        config.DB_PATH = folder / "orders.db"
        real_connect = sqlite3.connect
        db._local.__dict__.clear()
        try:
            # Plain files are fine; only the database is refused. That is
            # ransomware protection or antivirus, and nothing else.
            sqlite3.connect = lambda *a, **k: (_ for _ in ()).throw(
                sqlite3.OperationalError("unable to open database file"))
            with self.assertRaises(db.StorageError) as caught:
                db.connect()
            message = str(caught.exception)
            self.assertIn("Ordinary files can be written there", message)
            self.assertIn("Controlled folder access", message)
            self.assertNotIn("permission on the folder", message)
        finally:
            sqlite3.connect = real_connect
            (config.DATA_DIR, config.DOCS_DIR, config.DB_PATH) = saved
            db._local.__dict__.clear()
            shutil.rmtree(folder, ignore_errors=True)

    def test_a_folder_that_takes_no_files_at_all_is_named_as_such(self):
        blocker = Path(tempfile.mkdtemp(prefix="ot-blocked-")) / "in the way"
        blocker.write_text("a file, not a folder", encoding="utf-8")
        found = db.probe_folder(blocker / "inside")
        self.assertFalse(found["exists"])
        self.assertTrue(found["made"], "creating the folder should have failed")
        shutil.rmtree(blocker.parent, ignore_errors=True)

    def test_a_healthy_folder_probes_clean(self):
        found = db.probe_folder(config.DATA_DIR)
        self.assertTrue(found["exists"])
        self.assertTrue(found["file_ok"])
        self.assertTrue(found["db_ok"])
        self.assertFalse(found["network"])

    def test_a_network_data_folder_is_mentioned_in_the_failure(self):
        import sqlite3
        from ordertracker import drives

        real_describe = drives.describe
        real_connect = sqlite3.connect
        drives.describe = lambda path: {"network": True,
                                        "where": r"\\EstInternetDisk\2-yjkim"}
        sqlite3.connect = lambda *a, **k: (_ for _ in ()).throw(
            sqlite3.OperationalError("unable to open database file"))
        db._local.__dict__.clear()
        db.forget_network()
        try:
            with self.assertRaises(db.StorageError) as caught:
                db.connect()
            self.assertIn("EstInternetDisk", str(caught.exception))
            self.assertIn("network drive", str(caught.exception))
        finally:
            drives.describe = real_describe
            sqlite3.connect = real_connect
            db.forget_network()
            db._local.__dict__.clear()

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


class TestQuitting(unittest.TestCase):
    """The app can be stopped from the browser, so no console is needed."""

    def test_quit_stops_the_server(self):
        from ordertracker import server

        fresh_db()
        httpd = server.serve("127.0.0.1", 8813)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:8813"

        with urllib.request.urlopen(base + "/api/ping", timeout=5) as response:
            self.assertEqual(json.loads(response.read())["app"], "order-tracker")

        request = urllib.request.Request(base + "/api/quit", data=b"{}",
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertTrue(json.loads(response.read())["stopped"])

        thread.join(timeout=10)
        self.assertFalse(thread.is_alive(), "the server kept running after quit")
        httpd.server_close()

        with self.assertRaises((urllib.error.URLError, OSError)):
            urllib.request.urlopen(base + "/api/ping", timeout=3)


class TestMoveToAnotherDrive(unittest.TestCase):
    """Copying the app to another drive must bring the data and stay portable."""

    def setUp(self):
        self.holder = Path(tempfile.mkdtemp(prefix="ot-drive-"))
        self.target = self.holder / "Order Tracker"

        # Stand the current data somewhere of its own, named as it really is,
        # so the test measures the data move rather than whatever the working
        # copy happens to have lying around in data/.
        self.live = self.holder / "current-data"
        self.saved = (config.DATA_DIR, config.DOCS_DIR, config.DB_PATH)
        config.DATA_DIR = self.live
        config.DOCS_DIR = self.live / "documents"
        config.DB_PATH = self.live / "orders.db"
        db._local.__dict__.clear()
        fresh_db()

    def tearDown(self):
        config.DATA_DIR, config.DOCS_DIR, config.DB_PATH = self.saved
        db._local.__dict__.clear()
        shutil.rmtree(self.holder, ignore_errors=True)

    def test_the_copy_is_complete_portable_and_keeps_the_data(self):
        import move_to

        orders.create_order({"order_no": "SO-1000", "company": "대한정밀 주식회사"})
        documents.store("주문서.pdf", b"%PDF-1.4 test", order_id=1)

        code = move_to.main([str(self.target), "--no-git", "--no-shortcut"])
        self.assertEqual(code, 0)

        for needed in ("run.py", "setup.py", "ordertracker", "web", "assets"):
            self.assertTrue((self.target / needed).exists(), needed)

        # The marker is what keeps it working on a different drive letter.
        self.assertTrue((self.target / "portable.txt").exists())

        moved_db = self.target / "data" / "orders.db"
        self.assertTrue(moved_db.exists(), "the orders did not come across")
        conn = sqlite3.connect(f"file:{moved_db}?mode=ro", uri=True)
        names = [row[0] for row in conn.execute("SELECT order_no FROM orders")]
        conn.close()
        self.assertIn("SO-1000", names)

        documents_moved = list((self.target / "data" / "documents").iterdir())
        self.assertTrue(documents_moved, "the documents did not come across")
        self.assertTrue(any(f.name.endswith("주문서.pdf") for f in documents_moved))

    def test_uncommitted_wal_contents_survive_the_copy(self):
        """The database runs in WAL mode, so recent writes sit beside the .db.

        Copying the .db file alone silently loses them, which would move
        someone's order book across as an empty database.
        """
        import move_to

        orders.create_order({"order_no": "SO-WAL", "company": "Acme"})

        # Prove the point: the .db file on its own is missing the write.
        raw_copy = self.holder / "raw-copy.db"
        shutil.copyfile(config.DB_PATH, raw_copy)
        conn = sqlite3.connect(raw_copy)
        try:
            rows = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        except sqlite3.OperationalError:
            rows = 0          # not even the schema made it into the .db file
        finally:
            conn.close()
        self.assertEqual(rows, 0, "this test no longer proves anything")

        # The backup call gets it.
        proper = self.holder / "proper-copy.db"
        move_to.copy_database(config.DB_PATH, proper)
        conn = sqlite3.connect(proper)
        names = [r[0] for r in conn.execute("SELECT order_no FROM orders")]
        conn.close()
        self.assertIn("SO-WAL", names)

    def test_copying_a_folder_into_itself_is_refused(self):
        import move_to

        self.assertEqual(move_to.main([str(config.BASE_DIR / "inner"),
                                       "--no-shortcut"]), 1)
        self.assertEqual(move_to.main([str(config.BASE_DIR), "--no-shortcut"]), 1)

    def test_a_second_copy_over_read_only_files_still_works(self):
        """Git keeps its objects read-only, and Windows refuses to overwrite
        one. Copying twice — or into a folder that held a copy before — must
        not fail with "access is denied"."""
        import move_to

        orders.create_order({"order_no": "SO-TWICE", "company": "Acme"})
        self.assertEqual(
            move_to.main([str(self.target), "--no-git", "--no-shortcut"]), 0)

        # Make a copied file read-only, as git's object files are.
        stubborn = self.target / "run.py"
        stubborn.chmod(0o444)

        self.assertEqual(
            move_to.main([str(self.target), "--no-git", "--no-shortcut",
                          "--replace-data"]), 0,
            "a repeat copy was refused")
        self.assertTrue(stubborn.exists())

    def test_the_settings_travel_with_the_copy(self):
        import move_to
        from ordertracker import settings

        home = Path(tempfile.mkdtemp(prefix="ot-home-"))
        previous = {k: os.environ.get(k) for k in
                    ("XDG_CONFIG_HOME", "LOCALAPPDATA", "HOME")}
        os.environ.update({"XDG_CONFIG_HOME": str(home),
                           "LOCALAPPDATA": str(home), "HOME": str(home)})
        try:
            settings.save(welcome_name="김영진", show_welcome=True,
                          workspace=str(self.live))
            self.assertEqual(
                move_to.main([str(self.target), "--no-git", "--no-shortcut"]), 0)

            carried = settings.read_file(self.target / "settings.json")
            self.assertIsNotNone(carried, "no settings file in the copy")
            self.assertEqual(carried["welcome_name"], "김영진")
            # Portable keeps its data in its own folder, so the old path
            # must not follow it onto the new drive.
            self.assertEqual(carried["workspace"], "")
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(home, ignore_errors=True)

    def test_check_reports_without_copying_anything(self):
        import move_to

        code = move_to.main([str(self.target), "--check", "--no-shortcut"])
        self.assertEqual(code, 0)
        self.assertFalse((self.target / "run.py").exists(),
                         "--check copied something")

    def test_copying_while_the_app_is_running_is_refused(self):
        """A live database copied mid-write is the one way this can leave
        someone worse off than they started."""
        import move_to

        from ordertracker import relocate

        real = relocate.running_copy
        relocate.running_copy = lambda: "/somewhere/data"
        try:
            self.assertEqual(
                move_to.main([str(self.target), "--no-git", "--no-shortcut"]), 1)
            self.assertFalse((self.target / "run.py").exists())
            # --force is the way past it, for someone who knows better.
            self.assertEqual(
                move_to.main([str(self.target), "--no-git", "--no-shortcut",
                              "--force"]), 0)
        finally:
            relocate.running_copy = real

    def test_it_will_not_quietly_replace_orders_already_there(self):
        """Updating the app by copying it over an installed one is exactly
        how someone would wipe the order book they were trying to keep."""
        import move_to
        from ordertracker import relocate

        orders.create_order({"order_no": "SO-SOURCE", "company": "Acme"})
        self.assertEqual(
            move_to.main([str(self.target), "--no-git", "--no-shortcut"]), 0)

        # The destination now has orders of its own. Pretend the source has
        # since been emptied, as a fresh clone would be.
        conn = db.connect()
        with conn:
            conn.execute("DELETE FROM orders")

        with self.assertRaises(relocate.MoveError) as caught:
            relocate.run(self.target, keep_git=False, shortcut=False)
        self.assertIn("already holds", str(caught.exception))

        # And they are still there.
        moved = sqlite3.connect(
            f"file:{self.target / 'data' / 'orders.db'}?mode=ro", uri=True)
        names = [r[0] for r in moved.execute("SELECT order_no FROM orders")]
        moved.close()
        self.assertEqual(names, ["SO-SOURCE"])

    def test_saying_so_explicitly_does_replace_them(self):
        import move_to
        from ordertracker import relocate

        orders.create_order({"order_no": "SO-OLD", "company": "Acme"})
        move_to.main([str(self.target), "--no-git", "--no-shortcut"])

        conn = db.connect()
        with conn:
            conn.execute("UPDATE orders SET order_no = 'SO-NEW'")
            db.reindex_order(conn, 1)

        result = relocate.run(self.target, keep_git=False, shortcut=False,
                              replace_data=True)
        self.assertIn("1 orders", result["orders"])

        moved = sqlite3.connect(
            f"file:{self.target / 'data' / 'orders.db'}?mode=ro", uri=True)
        names = [r[0] for r in moved.execute("SELECT order_no FROM orders")]
        moved.close()
        self.assertEqual(names, ["SO-NEW"])

    def test_a_copy_onto_a_share_arrives_in_a_journal_mode_it_can_use(self):
        """Write-ahead logging does not work over a network filesystem. The
        copy is the one moment the mode can be changed with certainty, so it
        has to happen there rather than on first use."""
        from ordertracker import drives, relocate

        orders.create_order({"order_no": "SO-NET", "company": "Acme"})
        real = drives.describe
        drives.describe = lambda path: {"network": True, "where": r"\\srv\share"}
        try:
            relocate.run(self.target, keep_git=False, shortcut=False)
        finally:
            drives.describe = real

        copy = sqlite3.connect(self.target / "data" / "orders.db")
        mode = copy.execute("PRAGMA journal_mode").fetchone()[0]
        copy.close()
        self.assertEqual(mode.lower(), "delete")

    def test_a_copy_onto_a_local_disk_keeps_write_ahead_logging(self):
        from ordertracker import relocate

        orders.create_order({"order_no": "SO-LOCAL", "company": "Acme"})
        relocate.run(self.target, keep_git=False, shortcut=False)

        copy = sqlite3.connect(self.target / "data" / "orders.db")
        mode = copy.execute("PRAGMA journal_mode").fetchone()[0]
        copy.close()
        self.assertEqual(mode.lower(), "wal")

    def test_a_journal_mode_that_cannot_be_set_does_not_stop_the_app(self):
        """A busy or networked database can refuse the change. Asking is
        worth it; failing to start over it is not."""
        from ordertracker import drives

        holder = sqlite3.connect(config.DB_PATH, timeout=1)
        holder.execute("BEGIN EXCLUSIVE")
        real = drives.describe
        drives.describe = lambda path: {"network": True, "where": "share"}
        db.forget_network()
        db._local.__dict__.clear()
        try:
            conn = db.connect()          # must not raise
            self.assertIsNotNone(conn)
        finally:
            drives.describe = real
            db.forget_network()
            holder.rollback()
            holder.close()
            db._local.__dict__.clear()

    def test_the_plan_says_what_is_already_in_the_destination(self):
        import move_to
        from ordertracker import relocate

        orders.create_order({"order_no": "SO-THERE", "company": "Acme"})
        move_to.main([str(self.target), "--no-git", "--no-shortcut"])

        report = relocate.plan(self.target, probe=False)
        self.assertIn("1 orders", report["destination_stored"])

    def test_the_manual_plan_copies_nothing_and_names_the_data_folder(self):
        """When the drive refuses Python, the plan has to be followable in
        File Explorer — including the data folder, which is easy to miss
        because it is usually not inside the app folder."""
        import io
        import contextlib
        import move_to

        orders.create_order({"order_no": "SO-MANUAL", "company": "Acme"})
        documents.store("spec.txt", b"x", order_id=1)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = move_to.main([str(self.target), "--manual"])
        printed = out.getvalue()

        self.assertEqual(code, 0)
        self.assertFalse(self.target.exists(), "--manual copied something")
        self.assertIn(str(self.live), printed, "the data folder was not named")
        self.assertIn("1 orders and 1 documents", printed)
        self.assertIn(str(self.target / "data"), printed)
        self.assertIn("--finish", printed)

    def test_finish_completes_a_copy_made_by_hand(self):
        import move_to
        from ordertracker import relocate, settings

        home = Path(tempfile.mkdtemp(prefix="ot-home-"))
        previous = {k: os.environ.get(k) for k in
                    ("XDG_CONFIG_HOME", "LOCALAPPDATA", "HOME")}
        os.environ.update({"XDG_CONFIG_HOME": str(home),
                           "LOCALAPPDATA": str(home), "HOME": str(home)})
        real_base = config.BASE_DIR
        real_marker = settings.PORTABLE_MARKER
        try:
            settings.save(welcome_name="김영진", workspace=str(self.live))
            orders.create_order({"order_no": "SO-HAND", "company": "Acme"})

            # Stand in for the Explorer copy: the app, then the data folder.
            shutil.copytree(real_base, self.target,
                            ignore=move_to.SKIP_NO_GIT, dirs_exist_ok=True)
            shutil.copytree(self.live, self.target / "data", dirs_exist_ok=True)

            config.BASE_DIR = self.target
            settings.PORTABLE_MARKER = self.target / "portable.txt"
            self.assertTrue(relocate.finish_here(shortcut=False)["ok"])

            self.assertTrue((self.target / "portable.txt").exists())
            carried = settings.read_file(self.target / "settings.json")
            self.assertEqual(carried["welcome_name"], "김영진")
            self.assertEqual(carried["workspace"], "")
            # The folder it was copied from is left exactly as it was.
            self.assertFalse((real_base / "portable.txt").exists())
            self.assertTrue((self.live / "orders.db").exists())
        finally:
            config.BASE_DIR = real_base
            settings.PORTABLE_MARKER = real_marker
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(home, ignore_errors=True)

    def test_finish_in_the_wrong_folder_says_so(self):
        from ordertracker import relocate

        empty = self.holder / "not the app"
        empty.mkdir()
        real_base = config.BASE_DIR
        config.BASE_DIR = empty
        try:
            with self.assertRaises(relocate.MoveError) as caught:
                relocate.finish_here(shortcut=False)
            self.assertIn("run.py", str(caught.exception))
            self.assertFalse((empty / "portable.txt").exists())
        finally:
            config.BASE_DIR = real_base

    def test_a_refused_file_is_named_rather_than_dumped(self):
        import move_to

        failure = shutil.Error([("G:/x/run.py", "G:/y/run.py",
                                 "[Errno 13] Permission denied")])
        lines = "\n".join(move_to.describe_copy_failure(failure))
        self.assertIn("G:/x/run.py", lines)
        self.assertIn("Permission denied", lines)


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

    def test_a_portable_folder_keeps_its_settings_beside_run_py(self):
        """Unplug the drive, plug it into another machine, and your name on
        the welcome screen comes with it."""
        folder = self.home / "portable app"
        (folder / "ordertracker").mkdir(parents=True)
        marker = folder / "portable.txt"
        marker.write_text("portable", encoding="utf-8")

        real_marker = self.settings.PORTABLE_MARKER
        self.settings.PORTABLE_MARKER = marker
        try:
            self.assertTrue(self.settings.portable())
            self.assertEqual(self.settings.settings_path(),
                             folder / "settings.json")
            self.settings.save(welcome_name="Ji-ho")
            self.assertTrue((folder / "settings.json").exists())
            self.assertEqual(self.settings.load()["welcome_name"], "Ji-ho")
            # Nothing was written to this machine's own settings folder.
            self.assertFalse((self.settings.machine_dir() / "settings.json").exists())
        finally:
            self.settings.PORTABLE_MARKER = real_marker

    def test_going_portable_carries_this_machine_settings_over(self):
        self.settings.save(welcome_name="Rachel")

        folder = self.home / "newly portable"
        folder.mkdir(parents=True)
        marker = folder / "portable.txt"
        marker.write_text("portable", encoding="utf-8")

        real_marker = self.settings.PORTABLE_MARKER
        self.settings.PORTABLE_MARKER = marker
        try:
            # No settings of its own yet, so this machine's are read instead.
            self.assertEqual(self.settings.load()["welcome_name"], "Rachel")
            self.settings.save(welcome_name="Rachel")
            self.assertEqual(
                self.settings.read_file(folder / "settings.json")["welcome_name"],
                "Rachel")
        finally:
            self.settings.PORTABLE_MARKER = real_marker

    def test_unknown_keys_are_ignored(self):
        path = self.settings.settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"workspace": "/x", "nonsense": 1}), encoding="utf-8")
        self.assertNotIn("nonsense", self.settings.load())


class TestWindowsShortcut(unittest.TestCase):
    """The Windows path, exercised on any platform.

    It was previously broken by string formatting over a PowerShell script
    containing literal braces, and nothing caught it because only the Linux
    path had a test.
    """

    def setUp(self):
        from ordertracker import shortcut

        self.shortcut = shortcut
        self.desktop = Path(tempfile.mkdtemp(prefix="ot-win-desktop-"))
        self._real_desktop = shortcut.windows_desktop
        shortcut.windows_desktop = lambda: self.desktop

    def tearDown(self):
        self.shortcut.windows_desktop = self._real_desktop
        shutil.rmtree(self.desktop, ignore_errors=True)

    def _run_with(self, fake_run):
        import subprocess as sp

        real = sp.run
        sp.run = fake_run
        try:
            return self.shortcut._windows_shortcut(self.shortcut.default_icon())
        finally:
            sp.run = real

    def test_powershell_is_given_every_value_as_a_parameter(self):
        seen = {}

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(command, **kwargs):
            seen["command"] = command
            # PowerShell would create the file; stand in for it.
            Path(command[command.index("-LinkPath") + 1]).write_text("lnk")
            return Result()

        link = self._run_with(fake_run)

        self.assertTrue(link.exists())
        self.assertEqual(link.suffix, ".lnk")
        command = seen["command"]
        for flag in ("-LinkPath", "-Target", "-Arguments", "-WorkDir", "-Description"):
            self.assertIn(flag, command)
        self.assertIn("run.py", command[command.index("-Arguments") + 1])
        self.assertEqual(command[command.index("-WorkDir") + 1], str(config.BASE_DIR))

    def test_a_bat_launcher_is_written_when_powershell_refuses(self):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "cannot be loaded because running scripts is disabled"

        link = self._run_with(lambda command, **kwargs: Result())

        self.assertEqual(link.suffix, ".bat")
        body = link.read_text()
        self.assertIn("run.py", body)
        self.assertIn(str(config.BASE_DIR), body)

    def test_a_bat_launcher_is_written_when_powershell_is_missing(self):
        def fake_run(command, **kwargs):
            raise OSError("powershell not found")

        link = self._run_with(fake_run)
        self.assertEqual(link.suffix, ".bat")
        self.assertIn("run.py", link.read_text())

    def test_a_bat_for_a_korean_path_is_written_in_the_console_code_page(self):
        """cmd reads a .bat in the console code page, not UTF-8."""
        korean_folder = Path("G:/김영진/관리/TT")
        real_base, real_encoding = config.BASE_DIR, self.shortcut._console_encoding
        config.BASE_DIR = korean_folder
        self.shortcut._console_encoding = lambda: "cp949"
        try:
            link = self.shortcut._windows_bat(self.desktop)
            data = link.read_bytes()
        finally:
            config.BASE_DIR = real_base
            self.shortcut._console_encoding = real_encoding

        self.assertIn("김영진", data.decode("cp949"))
        self.assertNotIn(b"chcp", data)

    def test_a_bat_falls_back_to_utf8_when_the_code_page_cannot_cope(self):
        korean_folder = Path("G:/김영진/관리/TT")
        real_base, real_encoding = config.BASE_DIR, self.shortcut._console_encoding
        config.BASE_DIR = korean_folder
        self.shortcut._console_encoding = lambda: "cp1252"   # cannot hold Hangul
        try:
            link = self.shortcut._windows_bat(self.desktop)
            data = link.read_bytes()
        finally:
            config.BASE_DIR = real_base
            self.shortcut._console_encoding = real_encoding

        self.assertIn(b"chcp 65001", data)
        self.assertIn("김영진", data.decode("utf-8"))

    def test_a_path_with_awkward_characters_is_not_pasted_into_the_script(self):
        """Braces and quotes in a path must never reach the script text."""
        self.assertNotIn("{name}", self.shortcut._PS_SCRIPT)
        self.assertIn("param(", self.shortcut._PS_SCRIPT)


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


# ------------------------------------------------------- PCB specifications

class TestPcbCalculations(unittest.TestCase):

    def test_copper_weight_converts_to_microns_and_millimetres(self):
        one_ounce = pcb.copper(1)
        self.assertAlmostEqual(one_ounce["um"], 34.79, places=2)
        self.assertAlmostEqual(one_ounce["mm"], 0.0348, places=4)
        # Two ounces is twice as thick, and half an ounce half as thick.
        self.assertAlmostEqual(pcb.copper(2)["um"], 69.58, places=2)
        self.assertAlmostEqual(pcb.copper(0.5)["um"], 17.40, places=1)
        self.assertIsNone(pcb.copper(None))

    def test_thickness_tolerance_becomes_a_millimetre_range(self):
        derived = pcb.derive({"thickness_mm": 1.6, "thickness_tol_pct": 10})
        self.assertAlmostEqual(derived["thickness_tol_mm"], 0.16)
        self.assertAlmostEqual(derived["thickness_min_mm"], 1.44)
        self.assertAlmostEqual(derived["thickness_max_mm"], 1.76)

    def test_panel_yield_counts_arrays_both_ways_round(self):
        # AJ(6) is 532 x 607; with a 10 mm margin the usable area is 512 x 587.
        # A 210 x 170 array fits 2 x 3 one way and 3 x 2 the other: six either way.
        derived = pcb.derive({
            "panel_code": "AJ(6)", "array_x_mm": 210, "array_y_mm": 170,
            "ups": 4, "qty": 2000, "lots": 1,
        })
        self.assertEqual(derived["arrays_per_panel"], 6)
        self.assertEqual(derived["pcs_per_panel"], 24)
        self.assertEqual(derived["panels_needed"], 84)     # 2000 / 24, rounded up
        self.assertAlmostEqual(derived["panel_use_pct"], 66.3, places=1)

    def test_a_long_thin_array_is_turned_to_fit_more_on(self):
        # J(4) is 507 x 607, so 487 x 587 of it is usable. A 570 x 100 array
        # is too long to lie across the panel but fits four times up it.
        derived = pcb.derive({"panel_code": "J(4)", "array_x_mm": 570,
                              "array_y_mm": 100, "ups": 1})
        self.assertEqual(derived["arrays_per_panel"], 4)

    def test_lots_multiply_the_quantity(self):
        derived = pcb.derive({"qty": 500, "lots": 4})
        self.assertEqual(derived["total_qty"], 2000)
        self.assertEqual(pcb.derive({"qty": 500})["total_qty"], 500)

    def test_a_total_is_worked_out_from_the_piece_price_and_back_again(self):
        from_unit = pcb.cost_sheet({"qty": 1000, "pcb_unit_krw": 1200})
        self.assertEqual(from_unit["entered"]["pcb_total_krw"], 1200000)
        from_total = pcb.cost_sheet({"qty": 1000, "pcb_total_krw": 1200000})
        self.assertEqual(from_total["entered"]["pcb_unit_krw"], 1200)

    def test_inflation_and_markup_apply_to_every_total(self):
        sheet = pcb.cost_sheet({
            "qty": 100, "pcb_total_krw": 1000000,
            "inflation_on": 1, "inflation_rate": 1.25,
            "markup_on": 1, "markup_pct": 20, "fx_rate": 1000,
        })
        section = sheet["sections"][0]
        self.assertEqual(section["base_krw"], 1000000)
        self.assertEqual(section["inflated_krw"], 1250000)
        self.assertEqual(section["quoted_krw"], 1500000)     # 1.25 then +20%
        self.assertEqual(section["quoted_usd"], 1500.0)
        self.assertEqual(section["unit_usd"], 15.0)

    def test_rates_left_off_change_nothing(self):
        sheet = pcb.cost_sheet({"qty": 10, "pcb_total_krw": 100000,
                                "fx_rate": 1000})
        self.assertEqual(sheet["total"]["quoted_krw"], 100000)

    def test_two_stencils_are_added_to_the_smt_total(self):
        sheet = pcb.cost_sheet({
            "qty": 1000, "turnkey": 1, "smt_unit_krw": 500,
            "stencil_count": 2, "stencil_unit_krw": 140000, "fx_rate": 1000,
        })
        smt = next(s for s in sheet["sections"] if s["label"] == "SMT ASSEMBLY")
        self.assertEqual(smt["base_krw"], 500 * 1000 + 2 * 140000)
        self.assertIn("2 stencils", smt["note"])

    def test_without_turnkey_only_the_boards_are_charged(self):
        sheet = pcb.cost_sheet({
            "qty": 100, "pcb_total_krw": 50000, "turnkey": 0,
            "smt_total_krw": 999999, "parts_total_krw": 999999,
            "stencil_count": 2, "fx_rate": 1000,
        })
        self.assertEqual([s["label"] for s in sheet["sections"]],
                         ["PCB MANUFACTURING"])
        self.assertEqual(sheet["total"]["base_krw"], 50000)

    def test_the_grand_total_is_the_three_parts_added_up(self):
        sheet = pcb.cost_sheet({
            "qty": 100, "turnkey": 1, "pcb_total_krw": 100000,
            "smt_total_krw": 60000, "stencil_count": 1,
            "stencil_unit_krw": 130000, "parts_total_krw": 200000,
            "fx_rate": 1000,
        })
        self.assertEqual(sheet["total"]["base_krw"],
                         100000 + 60000 + 130000 + 200000)

    def test_prices_typed_with_commas_and_symbols_are_understood(self):
        cleaned = pcb.clean({"pcb_total_krw": "1,250,000", "qty": "2,000",
                             "impedance": "yes", "layers": "6"})
        self.assertEqual(cleaned["pcb_total_krw"], 1250000.0)
        self.assertEqual(cleaned["qty"], 2000)
        self.assertEqual(cleaned["impedance"], 1)
        self.assertEqual(cleaned["layers"], 6)

    def test_a_blank_spec_is_recognised_as_blank(self):
        self.assertTrue(pcb.is_empty(pcb.clean({"quote_ref": "", "layers": ""})))
        self.assertFalse(pcb.is_empty(pcb.clean({"layers": "4"})))


class TestSpecStorage(unittest.TestCase):

    def setUp(self):
        fresh_db()
        self.order_id = orders.create_order(
            {"order_no": "SO-1", "company": "Hanwoo Electronics",
             "status": "QUOTE"})

    def test_every_spec_field_has_a_column_to_live_in(self):
        """The form, the maths and the table must agree on the field list."""
        columns = {row["name"] for row in
                   db.connect().execute("PRAGMA table_info(order_specs)")}
        missing = [name for name in pcb.FIELD_NAMES if name not in columns]
        self.assertEqual(missing, [], f"order_specs is missing {missing}")

    def test_a_spec_survives_a_round_trip(self):
        orders.save_spec(self.order_id, {
            "product_type": "FLEX-RIGID", "layers": "8", "qty": "1500",
            "panel_code": "R(6)", "impedance": "1", "copper_outer_oz": "2",
            "pcb_unit_krw": "2400", "markup_on": "1", "markup_pct": "25",
        })
        spec = orders.get_spec(self.order_id)
        self.assertTrue(spec["has_spec"])
        self.assertEqual(spec["values"]["product_type"], "FLEX-RIGID")
        self.assertEqual(spec["values"]["layers"], 8)
        self.assertEqual(spec["values"]["impedance"], 1)
        self.assertAlmostEqual(spec["derived"]["copper_outer"]["um"], 69.58, 2)
        self.assertEqual(spec["cost"]["total"]["base_krw"], 2400 * 1500)

    def test_an_order_with_no_spec_still_answers(self):
        spec = orders.get_spec(self.order_id)
        self.assertFalse(spec["has_spec"])
        self.assertIsNone(spec["values"]["layers"])
        self.assertEqual(spec["cost"]["total"]["base_krw"], 0)

    def test_saving_twice_updates_rather_than_duplicates(self):
        orders.save_spec(self.order_id, {"layers": "4"})
        orders.save_spec(self.order_id, {"layers": "6"})
        rows = db.connect().execute(
            "SELECT COUNT(*) AS n FROM order_specs WHERE order_id = ?",
            (self.order_id,)).fetchone()["n"]
        self.assertEqual(rows, 1)
        self.assertEqual(orders.get_spec(self.order_id)["values"]["layers"], 6)

    def test_a_quote_keeps_the_rates_it_was_priced_at(self):
        prefs.save({"fx_rate": 1050})
        orders.save_spec(self.order_id, {"pcb_total_krw": "1050000"})
        self.assertEqual(orders.get_spec(self.order_id)["cost"]["fx_rate"], 1050)

        prefs.save({"fx_rate": 1400})          # the rate moves later on
        again = orders.get_spec(self.order_id)
        self.assertEqual(again["cost"]["fx_rate"], 1050,
                         "an old quote must not be repriced behind your back")
        self.assertEqual(again["cost"]["total"]["quoted_usd"], 1000.0)

    def test_a_new_order_can_carry_its_spec_with_it(self):
        order_id = orders.create_order({
            "order_no": "SO-2", "company": "Hanwoo Electronics",
            "spec": {"layers": "12", "qty": "800", "pcb_unit_krw": "5000"},
        })
        spec = orders.get_spec(order_id)
        self.assertEqual(spec["values"]["layers"], 12)
        self.assertEqual(spec["cost"]["total"]["base_krw"], 4000000)

    def test_deleting_an_order_takes_its_spec_with_it(self):
        orders.save_spec(self.order_id, {"layers": "4"})
        orders.delete_order(self.order_id)
        left = db.connect().execute(
            "SELECT COUNT(*) AS n FROM order_specs").fetchone()["n"]
        self.assertEqual(left, 0)

    def test_earlier_orders_are_offered_for_a_repeat(self):
        orders.save_spec(self.order_id, {"layers": "4", "quote_ref": "Q-1"})
        other = orders.create_order({"order_no": "SO-3", "company": "Acme Ltd"})
        orders.save_spec(other, {"layers": "6"})

        everyone = orders.reorder_sources()
        self.assertEqual(len(everyone), 2)

        company_id = next(c["id"] for c in orders.list_companies()
                          if c["name"] == "Hanwoo Electronics")
        just_theirs = orders.reorder_sources(company_id=company_id)
        self.assertEqual([o["order_no"] for o in just_theirs], ["SO-1"])
        self.assertEqual(just_theirs[0]["quote_ref"], "Q-1")

    def test_an_order_with_no_spec_is_not_offered_for_a_repeat(self):
        self.assertEqual(orders.reorder_sources(), [])

    def test_saving_a_spec_against_a_gone_order_is_refused(self):
        with self.assertRaises(orders.OrderError):
            orders.save_spec(999999, {"layers": "4"})


# ------------------------------------------------------------------- prefs

class TestPrefs(unittest.TestCase):

    def setUp(self):
        fresh_db()

    def test_defaults_are_used_until_something_is_saved(self):
        self.assertEqual(prefs.get("fx_rate"), 1050.0)
        self.assertIn("ENIG", prefs.get("surface_finishes"))

    def test_saved_settings_come_back(self):
        prefs.save({"fx_rate": "1,385", "markup_pct": "22",
                    "surface_finishes": ["ENIG", "HARD GOLD"]})
        prefs.forget_cache()
        self.assertEqual(prefs.get("fx_rate"), 1385.0)
        self.assertEqual(prefs.get("markup_pct"), 22.0)
        self.assertEqual(prefs.get("surface_finishes"), ["ENIG", "HARD GOLD"])

    def test_nonsense_is_ignored_rather_than_stored(self):
        prefs.save({"fx_rate": "not a number", "unknown_key": "x"})
        self.assertEqual(prefs.get("fx_rate"), 1050.0)
        self.assertNotIn("unknown_key", prefs.load())

    def test_reset_puts_everything_back(self):
        prefs.save({"fx_rate": 1400})
        prefs.reset()
        self.assertEqual(prefs.get("fx_rate"), 1050.0)

    def test_the_due_soon_window_follows_the_setting(self):
        order_id = orders.create_order({
            "order_no": "SO-DUE", "company": "Acme Ltd", "status": "CONFIRMED",
            "promise_date": (orders.today()
                             + datetime.timedelta(days=20)).isoformat()})
        self.assertNotIn("DUE SOON", orders.get_order(order_id)["alerts"])

        prefs.save({"due_soon_days": 30})
        self.assertIn("DUE SOON", orders.get_order(order_id)["alerts"])

    def test_a_panel_added_in_settings_can_be_quoted_against(self):
        prefs.save({"panel_sizes": [{"code": "CUSTOM", "x": 300, "y": 200}]})
        derived = pcb.derive({"panel_code": "CUSTOM", "array_x_mm": 100,
                              "array_y_mm": 100, "ups": 1})
        self.assertEqual(derived["panel"]["x"], 300)
        self.assertEqual(derived["arrays_per_panel"], 2)   # 280 x 180 usable


# ------------------------------------------------------- customers on a map

class TestCustomerLocations(unittest.TestCase):

    def setUp(self):
        fresh_db()

    def test_a_country_is_enough_to_place_a_customer(self):
        orders.save_company({"name": "Hanwoo", "country": "KR"})
        company = orders.list_companies()[0]
        self.assertAlmostEqual(company["lat"], 37.57, places=1)
        self.assertEqual(company["timezone"], "Asia/Seoul")
        self.assertEqual(company["city"], "Seoul")

    def test_a_known_city_beats_the_capital(self):
        orders.save_company({"name": "Valley Co", "country": "US",
                             "city": "San Jose"})
        company = orders.list_companies()[0]
        self.assertEqual(company["timezone"], "America/Los_Angeles")
        self.assertLess(company["lon"], -100)

    def test_a_position_typed_by_hand_is_kept(self):
        orders.save_company({"name": "Exact Ltd", "country": "DE",
                             "lat": 48.14, "lon": 11.58,
                             "timezone": "Europe/Berlin"})
        company = orders.list_companies()[0]
        self.assertAlmostEqual(company["lat"], 48.14)
        self.assertAlmostEqual(company["lon"], 11.58)

    def test_the_map_carries_workload_and_leaves_out_the_unplaced(self):
        orders.save_company({"name": "Placed", "country": "JP"})
        orders.save_company({"name": "Nowhere"})
        orders.create_order({"order_no": "SO-L", "company": "Placed",
                             "status": "CONFIRMED", "value": 1000,
                             "promise_date": (orders.today()
                                              - datetime.timedelta(days=5)).isoformat()})
        data = orders.map_points()
        names = [p["name"] for p in data["points"]]
        self.assertIn("Placed", names)
        self.assertNotIn("Nowhere", names)
        self.assertIn("Nowhere", data["unplaced"])

        placed = next(p for p in data["points"] if p["name"] == "Placed")
        self.assertEqual(placed["open"], 1)
        self.assertEqual(placed["alerts"], 1)          # it is overdue
        self.assertEqual(placed["timezone"], "Asia/Tokyo")

    def test_changing_the_country_moves_the_customer(self):
        company_id = orders.save_company({"name": "Movers", "country": "KR"})
        orders.save_company({"id": company_id, "name": "Movers",
                             "country": "BR", "city": "", "lat": "", "lon": "",
                             "timezone": ""})
        company = orders.list_companies()[0]
        self.assertEqual(company["timezone"], "America/Sao_Paulo")
        self.assertLess(company["lon"], 0)

    def test_every_country_carries_a_position_and_a_zone(self):
        for country in geo.country_list():
            with self.subTest(country=country["code"]):
                self.assertTrue(-90 <= country["lat"] <= 90)
                self.assertTrue(-180 <= country["lon"] <= 180)
                self.assertIn("/", country["timezone"])


# ------------------------------------------------------------------ backups

class TestBackups(unittest.TestCase):

    def setUp(self):
        fresh_db()
        self.folder = Path(tempfile.mkdtemp(prefix="ot-backup-"))
        prefs.save({"backup_dir": str(self.folder)})

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_a_backup_holds_the_very_latest_changes(self):
        """The write-ahead log means a plain file copy can arrive empty."""
        orders.create_order({"order_no": "SO-FRESH", "company": "Acme Ltd"})
        report = backup.run()
        self.assertTrue(report["ok"])

        copy = sqlite3.connect(report["path"])
        found = copy.execute("SELECT order_no FROM orders").fetchall()
        copy.close()
        self.assertEqual(found, [("SO-FRESH",)])

    def test_documents_are_mirrored_and_not_copied_twice(self):
        order_id = orders.create_order({"order_no": "SO-D", "company": "Acme Ltd"})
        documents.store("spec.txt", b"impedance controlled", order_id=order_id)

        first = backup.run()
        self.assertEqual(first["documents_copied"], 1)
        second = backup.run()
        self.assertEqual(second["documents_copied"], 0)

    def test_only_the_most_recent_copies_are_kept(self):
        prefs.save({"backup_keep": 2})
        root = backup.destination()
        root.mkdir(parents=True, exist_ok=True)
        for stamp in ("20200101-000000", "20200102-000000", "20200103-000000"):
            (root / f"orders-{stamp}.db").write_bytes(b"old")
        backup.run()
        left = sorted(p.name for p in root.glob("orders-*.db"))
        self.assertEqual(len(left), 2)
        self.assertNotIn("orders-20200101-000000.db", left)

    def test_without_a_folder_the_reason_is_explained(self):
        prefs.save({"backup_dir": ""})
        with self.assertRaises(backup.BackupError) as caught:
            backup.run()
        self.assertIn("SETUP", str(caught.exception))

    def test_a_startup_backup_never_stops_the_app(self):
        # A folder cannot be made inside a file, so this is a location that
        # genuinely cannot be written to, whoever is running the app.
        blocker = self.folder / "not-a-folder"
        blocker.write_text("in the way", encoding="utf-8")
        prefs.save({"backup_dir": str(blocker / "inside"),
                    "backup_on_start": True})
        report = backup.run_quietly()
        self.assertFalse(report["ok"])
        self.assertIn("backup folder", report["error"])

    def test_the_status_says_when_things_were_last_saved(self):
        orders.create_order({"order_no": "SO-S", "company": "Acme Ltd"})
        status = backup.status()
        self.assertTrue(status["saved_at"])
        self.assertTrue(status["configured"])
        backup.run()
        self.assertTrue(backup.status()["last_backup_at"])
        self.assertEqual(len(backup.status()["snapshots"]), 1)


# ------------------------------------------------------- the printable sheet

class TestPrintSheet(unittest.TestCase):

    def setUp(self):
        fresh_db()
        self.order_id = orders.create_order({
            "order_no": "SO-PRINT", "company": "Hanwoo Electronics",
            "description": "6L rigid FR-4", "status": "CONFIRMED"})
        orders.save_spec(self.order_id, {
            "layers": "6", "qty": "1000", "thickness_mm": "1.6",
            "thickness_tol_pct": "10", "copper_outer_oz": "1",
            "surface_finish": "ENIG", "panel_code": "J(6)",
            "array_x_mm": "150", "array_y_mm": "100", "ups": "2",
            "pcb_unit_krw": "3000", "markup_on": "1", "markup_pct": "25",
            "fx_rate": "1000",
        })

    def test_the_sheet_carries_the_spec_and_the_money(self):
        page = printsheet.render(self.order_id)
        self.assertIn("SO-PRINT", page)
        self.assertIn("Hanwoo Electronics", page)
        self.assertIn("34.8", page)                 # 1 oz in microns
        self.assertIn("1.440", page)                # thickness lower bound
        self.assertIn("3,750,000 KRW", page)        # 3,000,000 plus 25%
        self.assertIn("$3,750.00", page)
        self.assertIn("1,000 pcs", page)

    def test_a_missing_order_returns_nothing(self):
        self.assertIsNone(printsheet.render(999999))

    def test_an_order_with_no_prices_says_so_instead_of_totalling_zero(self):
        bare = orders.create_order({"order_no": "SO-BARE", "company": "Acme Ltd"})
        page = printsheet.render(bare)
        self.assertIn("No prices have been entered", page)

    def test_customer_text_cannot_inject_markup(self):
        orders.update_order(self.order_id,
                            {"description": '<script>alert("x")</script>'})
        page = printsheet.render(self.order_id)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)


class TestSpecAndSettingsOverHttp(unittest.TestCase):
    """The routes the spec form, the map and the settings page depend on."""

    @classmethod
    def setUpClass(cls):
        fresh_db()
        from ordertracker import server
        cls.httpd = server.serve("127.0.0.1", 8813)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:8813"
        cls.order_id = orders.create_order(
            {"order_no": "SO-HTTP", "company": "Hanwoo Electronics",
             "status": "QUOTE"})
        orders.save_company({"name": "Hanwoo Electronics", "country": "KR",
                             "id": next(c["id"] for c in orders.list_companies())})

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as response:
            return response.status, response.read()

    def get_json(self, path):
        code, body = self.get(path)
        return code, json.loads(body)

    def post(self, path, payload):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_the_front_end_scripts_are_served(self):
        for path in ("/world.js", "/map.js", "/spec.js", "/setup.js"):
            with self.subTest(path=path):
                code, body = self.get(path)
                self.assertEqual(code, 200)
                self.assertGreater(len(body), 500)

    def test_bootstrap_carries_what_the_spec_form_needs(self):
        code, data = self.get_json("/api/bootstrap")
        self.assertEqual(code, 200)
        names = [field["name"] for field in data["spec_fields"]]
        self.assertIn("panel_code", names)
        self.assertIn("copper_outer_oz", names)
        self.assertIn("fx_rate", [f["name"] for f in data["cost_fields"]])
        self.assertIn("panel_sizes", data["prefs"])
        self.assertTrue(data["countries"])

    def test_a_spec_can_be_saved_and_read_back(self):
        code, saved = self.post(f"/api/orders/{self.order_id}/spec",
                                {"layers": "6", "qty": "500",
                                 "pcb_unit_krw": "2000", "fx_rate": "1000"})
        self.assertEqual(code, 200)
        self.assertEqual(saved["cost"]["total"]["quoted_usd"], 1000.0)

        code, read = self.get_json(f"/api/orders/{self.order_id}/spec")
        self.assertEqual(read["values"]["layers"], 6)

    def test_a_price_can_be_worked_out_without_saving_anything(self):
        self.post(f"/api/orders/{self.order_id}/spec", {"qty": "500"})
        code, quoted = self.post("/api/quote", {
            "qty": "100", "pcb_unit_krw": "1000", "fx_rate": "1000",
            "panel_code": "R(6)", "array_x_mm": "200", "array_y_mm": "150",
            "ups": "2"})
        self.assertEqual(code, 200)
        self.assertEqual(quoted["cost"]["total"]["quoted_usd"], 100.0)
        # R(6) is 454 x 404: four 200 x 150 arrays fit, two boards on each.
        self.assertEqual(quoted["derived"]["arrays_per_panel"], 4)
        self.assertEqual(quoted["derived"]["pcs_per_panel"], 8)
        # Nothing was written: the saved spec still says what it said before.
        code, read = self.get_json(f"/api/orders/{self.order_id}/spec")
        self.assertEqual(read["values"]["qty"], 500)

    def test_the_map_lists_customers_with_their_zone(self):
        code, data = self.get_json("/api/map")
        self.assertEqual(code, 200)
        self.assertEqual(data["points"][0]["timezone"], "Asia/Seoul")

    def test_settings_can_be_read_and_written(self):
        code, before = self.get_json("/api/prefs")
        self.assertEqual(code, 200)
        self.assertIn("data", before["paths"])

        code, saved = self.post("/api/prefs", {"markup_pct": "27",
                                               "welcome": {"name": "Kim",
                                                           "show": True}})
        self.assertEqual(code, 200)
        self.assertEqual(saved["prefs"]["markup_pct"], 27.0)
        code, after = self.get_json("/api/prefs")
        self.assertEqual(after["welcome"]["name"], "Kim")

    def test_the_status_route_reports_saving_and_backup(self):
        code, status = self.get_json("/api/status")
        self.assertEqual(code, 200)
        self.assertIn("saved_at", status)
        self.assertIn("configured", status)

    def test_a_backup_without_a_folder_explains_itself(self):
        code, body = self.post("/api/backup", {"folder": ""})
        self.assertEqual(code, 400)
        self.assertIn("SETUP", body["error"])

    def test_the_printable_sheet_is_served_as_a_page(self):
        code, body = self.get(f"/print/order/{self.order_id}")
        self.assertEqual(code, 200)
        page = body.decode("utf-8")
        self.assertIn("<!DOCTYPE html>", page)
        self.assertIn("SO-HTTP", page)
        self.assertIn("BUILD SPECIFICATION", page.upper())

    def test_printing_an_order_that_is_gone_is_a_clean_404(self):
        try:
            self.get("/print/order/999999")
            self.fail("expected a 404")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)

    def test_the_move_can_be_checked_from_the_app(self):
        """The whole point of the button: no command prompt, no wrong
        folder. A check must report without writing the app anywhere."""
        target = Path(tempfile.mkdtemp(prefix="ot-move-http-")) / "Order Tracker"
        code, report = self.post("/api/move/check", {"folder": str(target)})
        try:
            self.assertEqual(code, 200)
            self.assertEqual(report["problem"], "")
            self.assertTrue(report["writable"])
            self.assertIn("orders", report["stored"])
            self.assertEqual(report["data_destination"], str(target / "data"))
            self.assertFalse((target / "run.py").exists())
        finally:
            shutil.rmtree(target.parent, ignore_errors=True)

    def test_a_folder_that_will_not_work_is_explained_not_thrown(self):
        blocker = Path(tempfile.mkdtemp(prefix="ot-move-bad-")) / "in the way"
        blocker.write_text("a file, not a folder", encoding="utf-8")
        try:
            code, report = self.post("/api/move/check",
                                     {"folder": str(blocker / "inside")})
            self.assertEqual(code, 200)
            self.assertTrue(report["problem"])
        finally:
            shutil.rmtree(blocker.parent, ignore_errors=True)

    def test_an_empty_folder_is_refused_with_something_readable(self):
        code, body = self.post("/api/move/check", {"folder": "   "})
        self.assertEqual(code, 400)
        self.assertIn("folder", body["error"])

    def test_the_app_can_copy_itself_while_it_is_running(self):
        """The app moving itself is safe — it reads its own database through
        SQLite's backup call and writes only to the new folder."""
        holder = Path(tempfile.mkdtemp(prefix="ot-move-live-"))
        target = holder / "Order Tracker"
        try:
            code, result = self.post("/api/move", {
                "folder": str(target), "keep_git": False, "shortcut": False})
            self.assertEqual(code, 200, result)
            self.assertTrue(result["ok"])
            self.assertTrue((target / "run.py").exists())
            self.assertTrue((target / "portable.txt").exists())
            self.assertIn("orders", result["orders"])

            moved = sqlite3.connect(
                f"file:{target / 'data' / 'orders.db'}?mode=ro", uri=True)
            names = [r[0] for r in moved.execute("SELECT order_no FROM orders")]
            moved.close()
            self.assertIn("SO-HTTP", names)
        finally:
            shutil.rmtree(holder, ignore_errors=True)

    def test_another_site_cannot_change_the_settings(self):
        request = urllib.request.Request(
            self.base + "/api/prefs", data=json.dumps({"fx_rate": 1}).encode(),
            headers={"Content-Type": "application/json",
                     "Origin": "http://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)


# ------------------------------------------------------------- uninstalling

class TestUninstall(unittest.TestCase):
    """Removing it must find the pieces that are not in the app folder, and
    must not remove anything without being told to twice."""

    def setUp(self):
        import uninstall

        self.uninstall = uninstall
        self.holder = Path(tempfile.mkdtemp(prefix="ot-uninstall-"))
        self.live = self.holder / "workspace" / "data"
        self.demo = self.holder / "workspace" / "demo-data"

        self.saved = (config.DATA_DIR, config.DOCS_DIR, config.DB_PATH,
                      config.DEMO_DIR)
        config.DATA_DIR = self.live
        config.DOCS_DIR = self.live / "documents"
        config.DB_PATH = self.live / "orders.db"
        config.DEMO_DIR = self.demo
        self.demo.mkdir(parents=True)
        db._local.__dict__.clear()
        fresh_db()

        self._env = {k: os.environ.get(k) for k in
                     ("XDG_CONFIG_HOME", "LOCALAPPDATA", "HOME",
                      "XDG_DESKTOP_DIR")}
        home = self.holder / "home"
        (home / "Desktop").mkdir(parents=True)
        os.environ.update({"XDG_CONFIG_HOME": str(home / "conf"),
                           "LOCALAPPDATA": str(home / "conf"),
                           "HOME": str(home),
                           "XDG_DESKTOP_DIR": str(home / "Desktop")})

    def tearDown(self):
        (config.DATA_DIR, config.DOCS_DIR, config.DB_PATH,
         config.DEMO_DIR) = self.saved
        db._local.__dict__.clear()
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.holder, ignore_errors=True)

    def test_it_finds_the_data_folder_even_though_it_is_elsewhere(self):
        from ordertracker import settings

        orders.create_order({"order_no": "SO-BYE", "company": "Acme"})
        documents.store("spec.txt", b"x", order_id=1)
        settings.save(welcome_name="김영진", workspace=str(self.live.parent))

        found = self.uninstall.find_everything()
        kinds = {item["kind"]: item for item in found["items"]}

        self.assertIn("data", kinds)
        self.assertEqual(kinds["data"]["path"], self.live.resolve())
        self.assertIn("1 orders and 1 documents", kinds["data"]["note"])
        self.assertTrue(kinds["data"]["precious"])
        self.assertIn("demo", kinds)
        self.assertIn("settings", kinds)

    def test_listing_removes_nothing(self):
        orders.create_order({"order_no": "SO-STAY", "company": "Acme"})
        self.assertEqual(self.uninstall.main([]), 0)
        self.assertTrue(config.DB_PATH.exists(), "listing deleted the orders")

    def test_the_wrong_answer_removes_nothing(self):
        import io
        import contextlib

        orders.create_order({"order_no": "SO-STAY", "company": "Acme"})
        real_stdin = sys.stdin
        sys.stdin = io.StringIO("yes\n")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = self.uninstall.main(["--delete"])
        finally:
            sys.stdin = real_stdin
        self.assertEqual(code, 1)
        self.assertTrue(config.DB_PATH.exists(), "'yes' was enough to delete")

    def test_a_saved_copy_is_complete_before_anything_goes(self):
        import io
        import contextlib

        orders.create_order({"order_no": "SO-RESCUE", "company": "대한정밀"})
        documents.store("주문서.pdf", b"%PDF-1.4 x", order_id=1)
        rescue = self.holder / "rescued"

        with contextlib.redirect_stdout(io.StringIO()):
            code = self.uninstall.main(["--delete", "--yes",
                                        "--save-to", str(rescue)])
        self.assertEqual(code, 0)

        self.assertFalse(self.live.exists(), "the data folder is still there")
        self.assertFalse(self.demo.exists())

        conn = sqlite3.connect(f"file:{rescue / 'orders.db'}?mode=ro", uri=True)
        names = [r[0] for r in conn.execute("SELECT order_no FROM orders")]
        conn.close()
        self.assertEqual(names, ["SO-RESCUE"])
        self.assertTrue(any((rescue / "documents").iterdir()))

    def test_the_settings_folder_goes_too_when_it_is_left_empty(self):
        """Taking the file and leaving its folder is not "removed" — and it
        makes a later portable install look like something is still here."""
        import io
        import contextlib
        from ordertracker import settings

        settings.save(welcome_name="김영진")
        folder = settings.settings_path().parent
        self.assertTrue(folder.exists())

        with contextlib.redirect_stdout(io.StringIO()):
            self.uninstall.main(["--delete", "--yes"])
        self.assertFalse(folder.exists(), "an empty settings folder was left")

    def test_a_settings_folder_holding_something_else_is_left_alone(self):
        import io
        import contextlib
        from ordertracker import settings

        settings.save(welcome_name="김영진")
        folder = settings.settings_path().parent
        (folder / "something-else.txt").write_text("not ours", encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            self.uninstall.main(["--delete", "--yes"])
        self.assertTrue(folder.exists())
        self.assertFalse(settings.settings_path().exists())

    def test_a_backup_folder_is_reported_but_never_removed(self):
        from ordertracker import prefs

        elsewhere = self.holder / "my backups"
        elsewhere.mkdir()
        prefs.save({"backup_dir": str(elsewhere)})

        found = self.uninstall.find_everything()
        self.assertIn(str(elsewhere), found["backup_dir"])
        self.assertNotIn(elsewhere.resolve(),
                         [item["path"] for item in found["items"]])

        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            self.uninstall.main(["--delete", "--yes"])
        self.assertTrue(elsewhere.exists(), "a backup folder was deleted")

    def test_the_app_folder_is_left_for_file_explorer(self):
        import io
        import contextlib

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.uninstall.main(["--delete", "--yes"])
        self.assertTrue(config.BASE_DIR.exists())
        self.assertIn(str(config.BASE_DIR.resolve()), out.getvalue())


# ------------------------------------------------------------ network drives

class TestNetworkDrives(unittest.TestCase):
    """A mapped drive pointing at a file server is not a disk with a
    different letter. SQLite's locking cannot be relied on over a share and
    its write-ahead log does not work there at all, and git cannot do the
    atomic renames a clone needs — so the app has to spot one and say so.

    The Windows calls are stubbed, so the logic is exercised everywhere.
    """

    def setUp(self):
        from ordertracker import drives

        self.drives = drives
        self.real = (drives._drive_type, drives._unc_for)

    def tearDown(self):
        self.drives._drive_type, self.drives._unc_for = self.real

    def pretend(self, kind, unc=""):
        self.drives._drive_type = lambda root: kind
        self.drives._unc_for = lambda letter: unc

    def test_a_unc_path_says_so_by_itself(self):
        found = self.drives.describe(r"\\EstInternetDisk\2-yjkim\Prog\TT")
        self.assertTrue(found["network"])
        self.assertEqual(found["where"], r"\\EstInternetDisk\2-yjkim")

    def test_forward_slashes_are_understood_too(self):
        """Git reports the path this way in its error messages."""
        found = self.drives.describe("//EstInternetDisk/2-yjkim/Prog/TT")
        self.assertTrue(found["network"])
        self.assertEqual(found["where"], r"\\EstInternetDisk\2-yjkim")

    def test_a_mapped_letter_is_resolved_to_what_it_points_at(self):
        self.pretend(self.drives.DRIVE_REMOTE, r"\\EstInternetDisk\2-yjkim")
        found = self.drives.describe(r"G:\김영진\Prog\TT")
        self.assertTrue(found["network"])
        self.assertIn("EstInternetDisk", found["where"])

    def test_a_mapped_letter_with_no_name_still_warns(self):
        self.pretend(self.drives.DRIVE_REMOTE, "")
        found = self.drives.describe(r"G:\Order Tracker")
        self.assertTrue(found["network"])
        self.assertIn("G:", found["where"])

    def test_an_ordinary_disk_is_left_alone(self):
        self.pretend(3)                      # DRIVE_FIXED
        self.assertFalse(self.drives.describe(r"C:\Users\eos")["network"])
        self.assertEqual(self.drives.warning_for(r"C:\Users\eos"), "")

    def test_a_removable_disk_is_not_a_network_drive(self):
        """A USB stick is a perfectly good home for a portable copy."""
        self.pretend(2)                      # DRIVE_REMOVABLE
        self.assertFalse(self.drives.describe(r"E:\Order Tracker")["network"])

    def test_anything_unexpected_is_treated_as_local(self):
        """A wrong warning is worse than none, so surprises mean local."""
        def explode(_):
            raise OSError("no such call on this platform")

        self.drives._drive_type = explode
        self.assertFalse(self.drives.describe(r"G:\folder")["network"])

    def test_the_warning_names_the_share_and_what_to_do(self):
        text = self.drives.warning_for("//EstInternetDisk/2-yjkim/Prog")
        self.assertIn("EstInternetDisk", text)
        self.assertIn("backup folder", text)
        self.assertIn("write-ahead log", text)

    def test_the_move_plan_carries_the_warning(self):
        from ordertracker import relocate

        self.pretend(self.drives.DRIVE_REMOTE, r"\\server\share")
        target = Path(tempfile.mkdtemp(prefix="ot-net-")) / "TT"
        try:
            report = relocate.plan(target, probe=False)
            # The stub answers for any drive letter, and a temp path has
            # none, so drive detection is exercised through the UNC branch.
            self.assertIn("warning", report)
            self.assertIn("network", report)
        finally:
            shutil.rmtree(target.parent, ignore_errors=True)

    def test_a_unc_destination_is_flagged_in_the_plan(self):
        from ordertracker import relocate

        real = self.drives.warning_for
        self.drives.warning_for = lambda path: "pretend warning"
        try:
            target = Path(tempfile.mkdtemp(prefix="ot-net2-")) / "TT"
            report = relocate.plan(target, probe=False)
            self.assertEqual(report["warning"], "pretend warning")
            shutil.rmtree(target.parent, ignore_errors=True)
        finally:
            self.drives.warning_for = real


# -------------------------------------------------- two machines, one folder

class TestInUseNote(unittest.TestCase):
    """SQLite's locking cannot be relied on over a share, so two machines
    writing to one order book is how it gets corrupted. A note in the data
    folder catches the honest version of that mistake."""

    def setUp(self):
        from ordertracker import inuse

        self.inuse = inuse
        self.holder = Path(tempfile.mkdtemp(prefix="ot-inuse-"))
        self.saved = config.DATA_DIR
        config.DATA_DIR = self.holder

    def tearDown(self):
        config.DATA_DIR = self.saved
        shutil.rmtree(self.holder, ignore_errors=True)

    def write_note(self, host, minutes_ago=0):
        import json
        from datetime import datetime, timedelta, timezone

        when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        self.inuse.note_path().write_text(json.dumps({
            "host": host, "pid": 1, "data": str(self.holder),
            "at": when.isoformat(timespec="seconds"),
        }), encoding="utf-8")

    def test_an_empty_folder_is_free(self):
        self.assertIsNone(self.inuse.held_elsewhere())

    def test_our_own_note_is_not_in_the_way(self):
        self.inuse.claim()
        self.assertIsNone(self.inuse.held_elsewhere())

    def test_another_machine_holds_it(self):
        self.write_note("EOS-DESKTOP")
        held = self.inuse.held_elsewhere()
        self.assertIsNotNone(held)
        self.assertEqual(held["host"], "EOS-DESKTOP")
        self.assertIn("EOS-DESKTOP", self.inuse.describe(held))
        self.assertIn("corrupted", self.inuse.describe(held))

    def test_a_note_from_a_session_that_died_clears_itself(self):
        self.write_note("EOS-DESKTOP", minutes_ago=30)
        self.assertIsNone(self.inuse.held_elsewhere(),
                          "a stale note locked everyone out")

    def test_a_damaged_note_does_not_lock_anyone_out(self):
        self.inuse.note_path().write_text("{ not json", encoding="utf-8")
        self.assertIsNone(self.inuse.held_elsewhere())

    def test_releasing_leaves_someone_else_note_alone(self):
        self.write_note("EOS-DESKTOP")
        self.inuse.release()
        self.assertTrue(self.inuse.note_path().exists())

    def test_releasing_clears_our_own(self):
        self.inuse.claim()
        self.inuse.release()
        self.assertFalse(self.inuse.note_path().exists())

    def test_a_folder_that_cannot_be_written_is_not_a_reason_to_refuse(self):
        config.DATA_DIR = self.holder / "not-a-folder" / "inside"
        (self.holder / "not-a-folder").write_text("a file", encoding="utf-8")
        self.assertIsNone(self.inuse.claim())
        self.assertIsNone(self.inuse.held_elsewhere())


# ------------------------------------------------------------- the diagnosis

class TestDoctor(unittest.TestCase):
    """When a folder refuses to hold the order book, the check has to find
    one that will and hand over the command that switches to it."""

    def setUp(self):
        import doctor

        self.doctor = doctor
        self.holder = Path(tempfile.mkdtemp(prefix="ot-doctor-"))

    def tearDown(self):
        shutil.rmtree(self.holder, ignore_errors=True)

    def test_a_usable_folder_reports_no_problem(self):
        self.assertEqual(self.doctor.folder_works(self.holder / "fine"), "")

    def test_a_folder_that_cannot_be_made_says_why(self):
        blocker = self.holder / "in the way"
        blocker.write_text("a file", encoding="utf-8")
        problem = self.doctor.folder_works(blocker / "inside")
        self.assertTrue(problem)
        self.assertIn("Error", problem)

    def test_the_candidates_leave_out_the_folder_that_just_failed(self):
        saved = config.DATA_DIR
        config.DATA_DIR = Path(tempfile.gettempdir()) / "order-tracker-data"
        try:
            places = self.doctor.candidate_folders()
            self.assertNotIn(config.DATA_DIR, places)
            self.assertTrue(places, "nothing was offered as an alternative")
        finally:
            config.DATA_DIR = saved

    def test_ransomware_protection_is_only_asked_about_on_windows(self):
        if sys.platform != "win32":
            self.assertEqual(self.doctor.controlled_folder_access(), "")
        else:                                     # pragma: no cover
            self.assertIn(self.doctor.controlled_folder_access(),
                          ("off", "ON", "audit only", "could not be read"))


# ------------------------------------------------------------ Outlook .msg

class TestOutlookMessages(unittest.TestCase):
    """The .msg reader, against files written by the fixture builder."""

    def make(self, **kwargs):
        path = _TMP / f"msg-{abs(hash(tuple(sorted(map(str, kwargs)))))}.msg"
        fixtures.make_msg(path, **kwargs)
        return outlook.read(path.read_bytes())

    def test_the_headline_fields_come_back(self):
        found = self.make(
            subject="Defect report PO-2026-1188",
            sender_name="Ha-eun Park", sender_email="haeun@northwind.example",
            to="sales@ourpcb.example", body="Twelve boards have open circuits.",
            sent=datetime.datetime(2026, 3, 14, 9, 30,
                                   tzinfo=datetime.timezone.utc))
        self.assertEqual(found["subject"], "Defect report PO-2026-1188")
        self.assertEqual(found["from_name"], "Ha-eun Park")
        self.assertEqual(found["from_email"], "haeun@northwind.example")
        self.assertEqual(found["to"], "sales@ourpcb.example")
        self.assertEqual(found["sent_at"], "2026-03-14 09:30:00")
        self.assertIn("open circuits", found["body"])

    def test_korean_survives_the_round_trip(self):
        found = self.make(subject="납기 문의 - SD-77140",
                          sender_name="김영진", body="출하 일정을 확인 부탁드립니다.")
        self.assertEqual(found["subject"], "납기 문의 - SD-77140")
        self.assertEqual(found["from_name"], "김영진")
        self.assertIn("출하", found["body"])

    def test_a_small_attachment_is_read_from_the_mini_stream(self):
        """Anything under 4 KB is packed into the mini stream, not sectors."""
        found = self.make(subject="with a note", body="see attached",
                          attachments=[{"filename": "note.txt",
                                        "data": b"lot 1 ships Monday"}])
        self.assertEqual(len(found["attachments"]), 1)
        self.assertEqual(found["attachments"][0]["filename"], "note.txt")
        self.assertEqual(found["attachments"][0]["data"], b"lot 1 ships Monday")

    def test_a_large_attachment_is_read_from_its_own_sectors(self):
        payload = b"%PDF-1.4 " + b"x" * 20_000
        found = self.make(subject="with a drawing", body="see attached",
                          attachments=[{"filename": "drawing.pdf",
                                        "data": payload}])
        self.assertEqual(found["attachments"][0]["data"], payload)

    def test_something_that_is_not_a_msg_is_refused_clearly(self):
        with self.assertRaises(outlook.NotAnOutlookFile):
            outlook.read(b"From: someone\r\nSubject: this is an eml\r\n\r\nhi")


# ------------------------------------------------------------- email intake

class TestReadingMail(unittest.TestCase):
    """Parsing, summarising and sorting, with nothing to connect to."""

    REPLY = (
        "From: Ha-eun Park <haeun@northwind.example>\r\n"
        "To: sales@ourpcb.example\r\n"
        "Subject: Defect report - PO-2026-1188 - 12 boards with open circuits\r\n"
        "Date: Mon, 21 Sep 2026 09:30:00 +0200\r\n"
        "Content-Type: text/plain; charset=\"utf-8\"\r\n\r\n"
        "Dear Young-jin,\r\n\r\n"
        "We received lot 3 of PO-2026-1188 and our AOI found 12 boards with "
        "open circuits on layer 4.\r\n"
        "Could you confirm by Friday whether you will rework them or issue a "
        "credit note?\r\n\r\n"
        "Best regards,\r\nHa-eun\r\n"
        "--\r\nHa-eun Park | Quality | Northwind\r\n\r\n"
        "> On 10 March, you wrote:\r\n"
        "> The shipment left on Monday and arrives Thursday.\r\n"
    ).encode()

    def test_the_headers_are_read(self):
        found = mail.parse("reply.eml", self.REPLY)
        self.assertEqual(found["from_email"], "haeun@northwind.example")
        self.assertEqual(found["from_name"], "Ha-eun Park")
        self.assertEqual(found["from_domain"], "northwind.example")
        self.assertEqual(found["sent_at"], "2026-09-21 07:30:00")  # in UTC

    def test_the_conversation_underneath_is_left_out(self):
        body = mail.clean_body(mail.parse("reply.eml", self.REPLY)["body"])
        self.assertIn("open circuits", body)
        self.assertNotIn("arrives Thursday", body)
        self.assertNotIn("Quality | Northwind", body)

    def test_the_summary_keeps_to_what_the_mail_says(self):
        found = mail.parse("reply.eml", self.REPLY)
        summary, keywords = mail.summarise(found["subject"], found["body"])
        self.assertIn("12 boards", summary)
        self.assertLessEqual(len(summary), mail.MAX_SUMMARY_CHARS)
        # Every word of the summary has to have been in the mail: this is an
        # extract, and it must never invent anything.
        haystack = (found["subject"] + " " + found["body"]).lower()
        for word in summary.lower().split():
            self.assertIn(word.strip(".,:;?"), haystack)
        self.assertTrue(keywords)

    def test_the_subject_decides_what_it_is_about(self):
        self.assertEqual(
            mail.categorise("Defect report - 12 boards rejected", "hello"),
            "DEFECT")
        self.assertEqual(mail.categorise("견적 요청 - 6 layer", ""), "QUOTE")
        self.assertEqual(mail.categorise("Lunch on Thursday?", "see you"),
                         "GENERAL")

    def test_reference_numbers_are_picked_out_whole(self):
        found = mail.find_references(
            "Re: PO-2026-1188 and quotation QTN-4471, also P.O. 9912")
        self.assertIn("PO-2026-1188", found["po"])
        self.assertIn("9912", found["po"])
        self.assertIn("QTN-4471", found["quote"])

    def test_an_empty_body_does_not_break_the_summary(self):
        self.assertEqual(mail.summarise("subject only", ""), ("", []))


class TestFilingMail(unittest.TestCase):
    """Where a mail is filed, and how sure the app says it is."""

    def setUp(self):
        fresh_db()
        self.company = orders.save_company({
            "name": "Northwind Industrial GmbH",
            "contact_email": "haeun@northwind.example"})
        self.order = orders.create_order({
            "company": "Northwind Industrial GmbH", "order_no": "OT-2026-0042",
            "po_number": "PO-2026-1188", "status": "IN PRODUCTION"})
        self.other = orders.create_order({
            "company": "Northwind Industrial GmbH", "order_no": "OT-2026-0033",
            "po_number": "PO-2026-1101", "status": "CONFIRMED"})

    def letter(self, subject, body="Nothing much.", sender=None):
        sender = sender or "Ha-eun Park <haeun@northwind.example>"
        return (f"From: {sender}\r\nTo: sales@ourpcb.example\r\n"
                f"Subject: {subject}\r\n"
                "Date: Mon, 21 Sep 2026 09:30:00 +0200\r\n"
                "Content-Type: text/plain; charset=\"utf-8\"\r\n\r\n"
                f"{body}\r\n").encode()

    def test_a_po_number_in_the_subject_files_it(self):
        item = mail.intake("a.eml", self.letter("Re: PO-2026-1188 delivery"))
        self.assertEqual(item["order_id"], self.order)
        self.assertEqual(item["needs_review"], 0)
        self.assertGreaterEqual(item["confidence"], 0.9)
        self.assertIn("PO-2026-1188", item["matched_on"])

    def test_two_orders_named_at_once_files_neither(self):
        item = mail.intake(
            "b.eml", self.letter("PO-2026-1188 and PO-2026-1101 both late"))
        self.assertIsNone(item["order_id"])
        self.assertEqual(item["needs_review"], 1)
        self.assertIn("2 different orders", item["matched_on"])

    def test_a_known_sender_finds_the_customer(self):
        item = mail.intake("c.eml", self.letter("General question"))
        self.assertEqual(item["company_id"], self.company)
        self.assertIn("contact address on file", item["matched_on"])

    def test_a_stranger_is_left_in_the_tray(self):
        item = mail.intake("d.eml", self.letter(
            "Introduction", sender="someone@unrelated.example"))
        self.assertIsNone(item["company_id"])
        self.assertEqual(item["needs_review"], 1)
        self.assertEqual(item["confidence"], 0.0)

    def test_the_same_mail_twice_is_not_filed_twice(self):
        raw = self.letter("Re: PO-2026-1188 delivery")
        first = mail.intake("e.eml", raw)
        again = mail.intake("e.eml", raw)
        self.assertTrue(again.get("duplicate"))
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(len(mail.list_mail()), 1)

    def test_the_mail_is_kept_as_a_document_and_can_be_searched(self):
        item = mail.intake("f.eml", self.letter(
            "Re: PO-2026-1188", "The impedance coupon failed at 48 ohms."))
        document = documents.get(item["doc_id"])
        self.assertEqual(document["kind"], "EMAIL")
        self.assertEqual(document["order_id"], self.order)
        hits = orders.search("impedance coupon")
        self.assertTrue(any(h["id"] == item["doc_id"]
                            for h in hits.get("documents", [])))

    def test_attachments_are_stored_as_documents_of_their_own(self):
        path = _TMP / "with-po.msg"
        fixtures.make_msg(
            path, subject="Re: PO-2026-1188 - purchase order attached",
            sender_name="Ha-eun Park", sender_email="haeun@northwind.example",
            body="Please find the order form attached.",
            attachments=[{"filename": "purchase order.pdf",
                          "data": fixtures.make_pdf(
                              ["PURCHASE ORDER", "PO-2026-1188"],
                              _TMP / "po-in-mail.pdf").read_bytes()}])
        item = mail.intake("with-po.msg", path.read_bytes())
        self.assertEqual(item["attachments"], 1)
        filed = [d["filename"] for d in documents.list_documents(
            order_id=self.order)]
        self.assertIn("purchase order.pdf", filed)

    def test_filing_it_by_hand_teaches_the_next_one(self):
        stranger = "kenji@sakura-denshi.example"
        first = mail.intake("g.eml", self.letter(
            "Nothing recognisable here", sender=stranger))
        self.assertEqual(first["needs_review"], 1)
        mail.assign(first["id"], order_id=self.order)

        second = mail.intake("h.eml", self.letter(
            "Another one, still nothing recognisable", sender=stranger))
        self.assertEqual(second["company_id"], self.company)
        self.assertIn("has been filed to this customer", second["matched_on"])

    def test_a_mail_dropped_on_an_order_goes_straight_there(self):
        item = mail.intake("i.eml", self.letter("No reference at all"),
                           order_id=self.other, actor="YJ")
        self.assertEqual(item["order_id"], self.other)
        self.assertEqual(item["needs_review"], 0)
        self.assertIn("filed by hand", item["matched_on"])

    def test_deleting_a_mail_takes_its_stored_copy_with_it(self):
        item = mail.intake("j.eml", self.letter("Re: PO-2026-1188"))
        doc_id = item["doc_id"]
        mail.delete(item["id"])
        self.assertIsNone(documents.get(doc_id))
        self.assertEqual(mail.tray()["total"], 0)


# ------------------------------------------------------- disputes and cases

class TestCases(unittest.TestCase):

    def setUp(self):
        fresh_db()
        self.order = orders.create_order({
            "company": "Northwind Industrial GmbH", "order_no": "OT-2026-0042",
            "po_number": "PO-2026-1188", "status": "IN PRODUCTION"})

    def open_one(self, **extra):
        data = {"order_id": self.order, "title": "12 boards, open circuits",
                "kind": "DEFECT", "severity": "HIGH", "qty_affected": 12,
                "claim_krw": "1,250,000"}
        data.update(extra)
        return cases.open_case(data, actor="YJ")

    def test_a_case_needs_an_order_and_a_title(self):
        with self.assertRaises(cases.CaseError):
            cases.open_case({"title": "no order"})
        with self.assertRaises(cases.CaseError):
            cases.open_case({"order_id": self.order, "title": "   "})

    def test_opening_one_records_the_position_and_starts_the_log(self):
        case = cases.get_case(self.open_one())
        self.assertTrue(case["ref"].startswith("C-"))
        self.assertEqual(case["qty_affected"], 12)
        self.assertEqual(case["claim_krw"], 1250000.0)
        self.assertEqual(case["status"], "OPEN")
        self.assertTrue(case["open"])
        self.assertEqual(len(case["entries"]), 1)
        self.assertIn("Case opened", case["entries"][0]["summary"])
        self.assertTrue(case["due_at"], "a case should come with a date to "
                                        "answer by")

    def test_references_count_up_within_the_year(self):
        first = cases.get_case(self.open_one())["ref"]
        second = cases.get_case(self.open_one(title="another"))["ref"]
        self.assertEqual(int(second[-3:]), int(first[-3:]) + 1)

    def test_the_log_keeps_what_was_said_and_when(self):
        case_id = self.open_one()
        cases.add_entry(case_id, {
            "kind": "CALL", "happened_at": "2026-09-21", "who": "Ha-eun Park",
            "summary": "Customer wants rework or a credit note",
            "detail": "Asked for an answer by Friday.",
            "follow_up_at": "2026-09-23"})
        case = cases.get_case(case_id)
        entry = [e for e in case["entries"] if e["kind"] == "CALL"][0]
        self.assertEqual(entry["happened_at"], "2026-09-21")
        self.assertEqual(entry["who"], "Ha-eun Park")
        self.assertEqual(entry["follow_up_at"], "2026-09-23")
        self.assertEqual(case["open_actions"], 1)

    def test_an_entry_has_to_say_something(self):
        case_id = self.open_one()
        with self.assertRaises(cases.CaseError):
            cases.add_entry(case_id, {"kind": "NOTE", "summary": ""})

    def test_settling_a_case_dates_it_and_logs_the_move(self):
        case_id = self.open_one()
        case = cases.update_case(case_id, {"status": "RESOLVED",
                                           "resolution": "Credit note issued"},
                                 actor="YJ")
        self.assertFalse(case["open"])
        self.assertTrue(case["closed_at"])
        self.assertTrue(any("Status moved from OPEN to RESOLVED" in e["summary"]
                            for e in case["entries"]))

    def test_reopening_clears_the_closing_date(self):
        case_id = self.open_one()
        cases.update_case(case_id, {"status": "CLOSED"})
        case = cases.update_case(case_id, {"status": "INVESTIGATING"})
        self.assertIsNone(case["closed_at"])
        self.assertTrue(case["open"])

    def test_overdue_follow_ups_are_listed_first_and_marked(self):
        case_id = self.open_one()
        yesterday = (datetime.date.today()
                     - datetime.timedelta(days=1)).isoformat()
        tomorrow = (datetime.date.today()
                    + datetime.timedelta(days=1)).isoformat()
        cases.add_entry(case_id, {"summary": "chase the factory",
                                  "follow_up_at": tomorrow})
        cases.add_entry(case_id, {"summary": "send the proposal",
                                  "follow_up_at": yesterday})
        due = cases.follow_ups(7)
        self.assertEqual([f["summary"] for f in due],
                         ["send the proposal", "chase the factory"])
        self.assertTrue(due[0]["late"])
        self.assertFalse(due[1]["late"])

    def test_ticking_an_action_off_takes_it_out_of_the_list(self):
        case_id = self.open_one()
        entry_id = cases.add_entry(case_id, {
            "summary": "send the proposal",
            "follow_up_at": datetime.date.today().isoformat()})
        self.assertEqual(len(cases.follow_ups(7)), 1)
        cases.complete_follow_up(entry_id)
        self.assertEqual(cases.follow_ups(7), [])

    def test_a_closed_case_stops_nagging(self):
        case_id = self.open_one()
        cases.add_entry(case_id, {"summary": "chase",
                                  "follow_up_at": datetime.date.today().isoformat()})
        self.assertEqual(cases.summary()["open_actions"], 1)
        cases.update_case(case_id, {"status": "CLOSED"})
        self.assertEqual(cases.summary()["open_actions"], 0)
        self.assertEqual(cases.summary()["open"], 0)

    def test_the_money_at_stake_adds_up_across_open_cases(self):
        self.open_one()
        self.open_one(title="short shipment", claim_krw=320000)
        self.assertEqual(cases.summary()["claim_krw"], 1570000.0)

    def test_deleting_an_order_takes_its_cases_with_it(self):
        case_id = self.open_one()
        orders.delete_order(self.order)
        self.assertIsNone(cases.get_case(case_id))

    def test_the_printed_report_carries_the_whole_log(self):
        case_id = self.open_one()
        cases.add_entry(case_id, {"kind": "CALL", "who": "Mr Cho",
                                  "summary": "Factory will cross-section it",
                                  "detail": "Report due Wednesday."})
        page = printsheet.case_sheet(case_id)
        self.assertIn("Factory will cross-section it", page)
        self.assertIn("Report due Wednesday.", page)
        self.assertIn("1,250,000 KRW", page)
        self.assertIn("LOG OF COMMUNICATIONS AND ACTIONS".title().upper(),
                      page.upper())

    def test_a_case_for_a_missing_order_is_refused(self):
        with self.assertRaises(cases.CaseError):
            cases.open_case({"order_id": 999999, "title": "nowhere"})


# --------------------------------------------------------- the front end

class TestFrontEndScripts(unittest.TestCase):
    """Guards for the things a no-build, many-script front end gets wrong."""

    def scripts(self):
        return sorted((ROOT / "web").glob("*.js"))

    def test_no_two_scripts_declare_the_same_name(self):
        """Classic scripts share one global scope.

        A second `const krw` anywhere on the page throws before a line of
        that file runs, which silently takes out a whole view. It costs
        nothing to check and is invisible when it happens.
        """
        import re
        declared = {}
        clashes = []
        pattern = re.compile(r"^(?:function|const|let|var|class)\s+"
                             r"([A-Za-z_$][\w$]*)", re.M)
        for script in self.scripts():
            for name in pattern.findall(script.read_text(encoding="utf-8")):
                if name in declared and declared[name] != script.name:
                    clashes.append(f"{name}: {declared[name]} and {script.name}")
                declared[name] = script.name
        self.assertEqual(clashes, [], "two scripts declare the same name")

    def test_every_script_the_page_asks_for_exists(self):
        import re
        page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for src in re.findall(r'<script src="/([^"]+)"', page):
            self.assertTrue((ROOT / "web" / src).is_file(), f"missing {src}")

    def test_the_views_in_the_page_match_the_ones_in_the_code(self):
        import re
        page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        buttons = set(re.findall(r'data-view="(\w+)"', page))
        sections = set(re.findall(r'id="view-(\w+)"', page))
        self.assertTrue(buttons <= sections,
                        "a nav button has no section to show")
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        listed = set(re.findall(r"'(\w+)'",
                                re.search(r"const NAV_VIEWS = \[(.*?)\]", app,
                                          re.S).group(1)))
        self.assertEqual(listed, buttons)


# -------------------------------------------- a machine that refuses writes

class TestLockedDownMachine(unittest.TestCase):
    """Some work computers let only approved programs write files.

    Python is then refused the per-user settings folder and the system
    temporary folder, while the app's own folder — on a personal drive —
    takes files perfectly well. Nothing about that should stop the app.
    """

    def setUp(self):
        from ordertracker import settings
        self.settings = settings
        self.home = Path(tempfile.mkdtemp(prefix="ot-locked-"))
        self.app = self.home / "app"
        self.app.mkdir()
        self.blocked = self.home / "blocked"
        # A file where a folder should be: nothing can be written inside it,
        # which is what a refused folder looks like from here.
        self.blocked.write_text("not a folder", encoding="utf-8")

        self._env = {k: os.environ.get(k) for k in
                     ("XDG_CONFIG_HOME", "LOCALAPPDATA", "HOME")}
        os.environ["XDG_CONFIG_HOME"] = str(self.blocked)
        os.environ["LOCALAPPDATA"] = str(self.blocked)
        os.environ["HOME"] = str(self.blocked)
        self._marker = settings.PORTABLE_MARKER
        settings.PORTABLE_MARKER = self.app / "portable.txt"

    def tearDown(self):
        self.settings.PORTABLE_MARKER = self._marker
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.home, ignore_errors=True)

    def test_settings_fall_back_to_the_app_folder(self):
        written = self.settings.save(welcome_name="김영진")
        self.assertEqual(written, self.app / "settings.json")
        self.assertEqual(self.settings.load()["welcome_name"], "김영진")

    def test_the_usual_place_is_still_preferred(self):
        os.environ["XDG_CONFIG_HOME"] = str(self.home / "ok")
        os.environ["LOCALAPPDATA"] = str(self.home / "ok")
        written = self.settings.save(welcome_name="Rachel")
        self.assertTrue(str(written).startswith(str(self.home / "ok")))

    def test_the_scratch_folder_moves_next_to_the_data(self):
        import tempfile as tempfile_module
        saved_dir = tempfile_module.tempdir
        try:
            scratch = config.use_own_temp(self.home / "data" / ".scratch")
            self.assertEqual(scratch, self.home / "data" / ".scratch")
            self.assertEqual(tempfile_module.tempdir, str(scratch))
            with tempfile_module.NamedTemporaryFile(suffix=".pdf") as handle:
                self.assertTrue(str(handle.name).startswith(str(scratch)))
        finally:
            tempfile_module.tempdir = saved_dir

    def test_a_scratch_folder_that_cannot_be_made_is_left_alone(self):
        import tempfile as tempfile_module
        saved_dir = tempfile_module.tempdir
        try:
            self.assertIsNone(config.use_own_temp(self.blocked / "scratch"))
            self.assertEqual(tempfile_module.tempdir, saved_dir)
        finally:
            tempfile_module.tempdir = saved_dir

    def test_old_scratch_files_are_cleared_away(self):
        scratch = self.home / "data" / ".scratch"
        scratch.mkdir(parents=True)
        stale = scratch / "old.pdf"
        stale.write_bytes(b"%PDF")
        fresh = scratch / "new.pdf"
        fresh.write_bytes(b"%PDF")
        two_days = time.time() - 2 * 86400
        os.utime(stale, (two_days, two_days))
        import tempfile as tempfile_module
        saved_dir = tempfile_module.tempdir
        try:
            config.use_own_temp(scratch)
        finally:
            tempfile_module.tempdir = saved_dir
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())
