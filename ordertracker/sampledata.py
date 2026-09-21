"""Demo data, so the terminal has something in it before your real data does.

Everything here is invented. `python3 run.py --demo` loads it into a separate
database file, which keeps it well away from anything real.
"""

import datetime
import email.message
import email.policy
import random
import zlib

from . import db, documents, orders

COMPANIES = [
    ("Northwind Industrial GmbH", "NWI", "Marta Lindqvist", "procurement@northwind-ind.example"),
    ("Acme Components Ltd", "ACME", "Danny Osei", "purchasing@acme-components.example"),
    ("Kestrel Marine Systems", "KMS", "Priya Raghavan", "supply@kestrelmarine.example"),
    ("Vantage Medical Supply", "VMS", "Tom Bergeron", "orders@vantagemed.example"),
    ("Pinnacle Aerospace", "PNA", "Sofia Marchetti", "scm@pinnacle-aero.example"),
    ("Redwood Packaging Co", "RWP", "Alicia Vance", "buying@redwoodpack.example"),
    ("Helios Energy Partners", "HEP", "Jonas Weber", "procure@helios-energy.example"),
    ("Brightline Retail Group", "BRG", "Chen Wei", "vendors@brightline-retail.example"),
]

PRODUCTS = [
    "BRK-8841-SS stainless mounting brackets",
    "FST-1190 fastener kit, zinc",
    "HX-440 heat exchanger core",
    "PMP-77 centrifugal pump assembly",
    "SEN-2210 pressure sensor array",
    "CBL-905 shielded cable, 500 m drum",
    "VLV-318 ball valve, 2 inch",
    "ENC-640 IP66 control enclosure",
    "GSK-112 gasket set, viton",
    "MTR-450 servo motor, 3 kW",
]

OWNERS = ["R. Kim", "J. Alvarez", "S. Doyle", "M. Okafor"]


def _pdf(lines) -> bytes:
    """A small, valid one-page PDF holding the given lines of text."""
    parts = ["BT", "/F1 11 Tf", "1 0 0 1 56 760 Tm"]
    for i, line in enumerate(lines):
        if i:
            parts.append("0 -15 Td")
        safe = str(line).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        parts.append(f"({safe}) Tj")
    parts.append("ET")
    content = zlib.compress("\n".join(parts).encode("latin-1"))

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n%s\nendstream"
        % (len(content), content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref_at)
    return bytes(out)


def _eml(sender, sender_name, subject, body, attachment=None) -> bytes:
    msg = email.message.EmailMessage()
    msg["From"] = f"{sender_name} <{sender}>"
    msg["To"] = "sales@yourcompany.example"
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg.set_content(body)
    if attachment:
        name, data = attachment
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    return msg.as_bytes()


def load(seed: int = 7) -> dict:
    """Create the demo companies, orders and documents. Returns a count."""
    rng = random.Random(seed)
    today = datetime.date.today()

    for name, code, contact, mail in COMPANIES:
        orders.save_company({
            "name": name, "code": code, "contact_name": contact,
            "contact_email": mail,
        })

    companies = {c["name"]: c["id"] for c in orders.list_companies()}

    # A spread of stages, deliberately including orders that are late, quiet,
    # or missing their paperwork, so the alert panel has something to show.
    plan = [
        # (company, status, order offset days, promise offset days, value, make PO doc)
        ("Northwind Industrial GmbH", "IN PRODUCTION", -38, -4, 10780, True),
        ("Northwind Industrial GmbH", "CONFIRMED", -12, 21, 24500, False),
        ("Northwind Industrial GmbH", "PAID", -95, -60, 8300, True),
        ("Acme Components Ltd", "SHIPPED", -26, 3, 4250, True),
        ("Acme Components Ltd", "ORDER RECEIVED", -3, 45, 16750, False),
        ("Acme Components Ltd", "QUOTE", -1, 60, 31200, False),
        ("Kestrel Marine Systems", "IN PRODUCTION", -52, -11, 68400, True),
        ("Kestrel Marine Systems", "READY TO SHIP", -30, 2, 12950, True),
        ("Kestrel Marine Systems", "ON HOLD", -44, 9, 5400, True),
        ("Vantage Medical Supply", "CONFIRMED", -20, 6, 9800, True),
        ("Vantage Medical Supply", "INVOICED", -70, -40, 21300, True),
        ("Vantage Medical Supply", "DELIVERED", -33, -12, 7450, True),
        ("Pinnacle Aerospace", "IN PRODUCTION", -61, 30, 143000, True),
        ("Pinnacle Aerospace", "CONFIRMED", -25, 14, 56700, False),
        ("Pinnacle Aerospace", "QUOTE", -6, 90, 88000, False),
        ("Redwood Packaging Co", "SHIPPED", -18, -1, 3100, True),
        ("Redwood Packaging Co", "ORDER RECEIVED", -9, 28, 6750, False),
        ("Redwood Packaging Co", "PAID", -120, -88, 4900, True),
        ("Helios Energy Partners", "IN PRODUCTION", -47, 5, 97500, True),
        ("Helios Energy Partners", "READY TO SHIP", -36, -2, 34200, True),
        ("Helios Energy Partners", "CANCELLED", -55, 12, 15000, False),
        ("Brightline Retail Group", "ORDER RECEIVED", -2, 17, 12400, False),
        ("Brightline Retail Group", "DELIVERED", -40, -19, 28900, True),
        ("Brightline Retail Group", "CONFIRMED", -29, 4, 19600, True),
        ("Brightline Retail Group", "QUOTE", -4, 75, 42000, False),
        ("Acme Components Ltd", "IN PRODUCTION", -41, -7, 22800, False),
        ("Kestrel Marine Systems", "CONFIRMED", -16, 11, 15750, True),
        ("Vantage Medical Supply", "ORDER RECEIVED", -5, 33, 5200, False),
    ]

    created = 0
    docs = 0
    for index, (company, status, order_off, promise_off, value, with_po) in enumerate(plan):
        order_no = f"SO-{2600 + index}"
        po_number = f"PO-2026-{rng.randint(10000, 99999)}"
        product = PRODUCTS[index % len(PRODUCTS)]
        order_date = today + datetime.timedelta(days=order_off)
        promise_date = today + datetime.timedelta(days=promise_off)

        ship_date = ""
        if status in ("SHIPPED", "DELIVERED", "INVOICED", "PAID"):
            ship_date = (promise_date - datetime.timedelta(days=rng.randint(0, 4))).isoformat()

        order_id = orders.create_order({
            "order_no": order_no,
            "company": company,
            "po_number": po_number if with_po or rng.random() > 0.4 else "",
            "description": product,
            "status": status,
            "value": value,
            "currency": "EUR" if "GmbH" in company else "USD",
            "order_date": order_date.isoformat(),
            "promise_date": promise_date.isoformat(),
            "ship_date": ship_date,
            "owner": OWNERS[index % len(OWNERS)],
            "priority": "HIGH" if value > 50000 else "NORMAL",
            "notes": "",
        }, actor="demo")
        created += 1

        # Make some orders look untouched for a while, so "stalled" is visible.
        if index % 5 == 0:
            stale = (today - datetime.timedelta(days=rng.randint(15, 40)))
            conn = db.connect()
            with conn:
                conn.execute("UPDATE orders SET updated_at = ? WHERE id = ?",
                             (stale.isoformat() + " 09:00:00", order_id))

        contact = next(c for c in COMPANIES if c[0] == company)

        if with_po:
            pdf = _pdf([
                "PURCHASE ORDER",
                "",
                f"PO Number: {po_number}",
                f"Buyer: {company}",
                f"Supplier reference: {order_no}",
                f"Contact: {contact[2]} <{contact[3]}>",
                "",
                f"Item: {product}",
                f"Order value: {value:,.2f}",
                f"Required delivery: {promise_date.isoformat()}",
                "Incoterms: DAP. Payment terms: net 30 days.",
            ])
            documents.store(f"{po_number} purchase order.pdf", pdf, order_id=order_id)
            docs += 1

        if index % 3 == 0:
            mail = _eml(
                contact[3], contact[2],
                f"{po_number} — delivery schedule for {order_no}",
                f"Hello,\n\nCould you confirm the delivery date on {order_no} "
                f"({po_number})? Our production plan currently assumes "
                f"{promise_date.isoformat()}.\n\nThe item is {product}.\n\n"
                f"Best regards,\n{contact[2]}\n{company}\n",
            )
            documents.store(f"RE {po_number} delivery schedule.eml", mail,
                            order_id=order_id)
            docs += 1

        if status in ("INVOICED", "PAID"):
            invoice = _pdf([
                "INVOICE",
                "",
                f"Invoice against: {order_no}",
                f"Customer PO: {po_number}",
                f"Bill to: {company}",
                f"Amount due: {value:,.2f}",
                "Terms: net 30 days",
            ])
            documents.store(f"Invoice {order_no}.pdf", invoice, order_id=order_id)
            docs += 1

    # One loose file with no order attached, to show the unfiled tray and
    # how auto-filing picks the order up.
    loose = _pdf([
        "PACKING LIST",
        "",
        "Against sales order SO-2603",
        "Cartons: 14   Gross weight: 268 kg",
        "Carrier: Meridian Freight, tracking MF-88213",
    ])
    documents.store("packing list scan.pdf", loose)
    docs += 1

    return {"companies": len(COMPANIES), "orders": created, "documents": docs}
