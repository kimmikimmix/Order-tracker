"""Demo data, so the terminal has something in it before your real data does.

Everything here is invented. `python3 run.py --demo` loads it into a separate
database file, which keeps it well away from anything real.
"""

import datetime
import email.message
import email.policy
import random
import zlib

from . import cases, db, documents, mail as mailbox, orders, threads

COMPANIES = [
    # name, code, contact, email, country, city
    ("Northwind Industrial GmbH", "NWI", "Marta Lindqvist",
     "procurement@northwind-ind.example", "DE", "Stuttgart"),
    ("Acme Components Ltd", "ACME", "Danny Osei",
     "purchasing@acme-components.example", "GB", "London"),
    ("Kestrel Marine Systems", "KMS", "Priya Raghavan",
     "supply@kestrelmarine.example", "US", "Boston"),
    ("Vantage Medical Supply", "VMS", "Tom Bergeron",
     "orders@vantagemed.example", "US", "San Jose"),
    ("Pinnacle Aerospace", "PNA", "Sofia Marchetti",
     "scm@pinnacle-aero.example", "FR", "Paris"),
    ("Redwood Packaging Co", "RWP", "Alicia Vance",
     "buying@redwoodpack.example", "AU", "Canberra"),
    ("Helios Energy Partners", "HEP", "Jonas Weber",
     "procure@helios-energy.example", "JP", "Osaka"),
    ("Brightline Retail Group", "BRG", "Chen Wei",
     "vendors@brightline-retail.example", "SG", "Singapore"),
    ("Hanwoo Electronics", "HWE", "Park Ji-ho",
     "buy@hanwoo-elec.example", "KR", "Ansan"),
    ("Andes Instrumentos", "ANI", "Luciana Ferraz",
     "compras@andes-inst.example", "BR", "Brasilia"),
]

PRODUCTS = [
    "6L rigid FR-4, ENIG, 1.6T - motor controller",
    "4L rigid 185 HR, OSP, 1.0T - power stage",
    "2L flex polyimide, ENIG, 0.2T - sensor tail",
    "8L flex-rigid, ENIG, 1.2T - camera head",
    "4L rigid Rogers 4350B, immersion silver - RF front end",
    "10L rigid FR-4 TG170, ENEPIG, 2.0T - backplane",
    "6L rigid FR-4, HASL, 1.6T - I/O breakout",
    "4L rigid FR-4, ENIG, 0.8T - battery management",
    "12L rigid FR-4 TG170, ENIG, 2.4T - switch fabric",
    "2L rigid aluminium, HASL - LED bar",
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
    body = "\n".join(parts).encode("latin-1", "replace")
    content = zlib.compress(body)

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


def _eml(sender, sender_name, subject, body, attachment=None, when=None) -> bytes:
    msg = email.message.EmailMessage()
    msg["From"] = f"{sender_name} <{sender}>"
    msg["To"] = "sales@yourcompany.example"
    msg["Subject"] = subject
    # Demo mail is spread over the weeks the orders ran, so the tray sorts
    # like a real one instead of arriving all at the same second.
    if when is None:
        msg["Date"] = email.utils.formatdate(localtime=True)
    else:
        msg["Date"] = email.utils.format_datetime(
            datetime.datetime.combine(when, datetime.time(9, 20)))
    msg.set_content(body)
    if attachment:
        name, data = attachment
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    return msg.as_bytes()


# Working panels, layer counts and finishes a fabricator would actually quote.
_PANELS = ["J(6)", "J(4)", "AJ(6)", "R(8)", "R(6)", "R(4)"]
_FINISH = [("ENIG", '2-3µ" Au'), ("HASL", "—"), ("OSP", "0.3µm"),
           ("IMMERSION SILVER", "0.2µm"), ("ENEPIG", '1-2µ" Au')]
_MATERIAL = ["FR-4 TG150", "FR-4 TG170", "185 HR", "ROGERS 4350B",
             "POLYIMIDE", "IT-180A"]


def _spec(index, rng, value, order_date, po_number) -> dict:
    """A plausible build specification and cost sheet for a demo order."""
    layers = [2, 4, 4, 6, 6, 8, 10, 12][index % 8]
    thickness = {2: 1.0, 4: 1.0, 6: 1.6, 8: 1.6, 10: 2.0, 12: 2.4}[layers]
    finish, finish_thickness = _FINISH[index % len(_FINISH)]
    product_type = ["RIGID", "RIGID", "FLEX", "FLEX-RIGID"][index % 4]

    pcb_x = round(rng.uniform(22, 140), 1)
    pcb_y = round(rng.uniform(18, 110), 1)
    ups = rng.choice([1, 2, 2, 4, 6])
    qty = rng.choice([500, 1000, 2000, 3000, 5000])

    turnkey = index % 3 == 0
    # Won per piece, loosely following layer count and area.
    unit = round(layers * 340 + pcb_x * pcb_y * 0.28, -1)

    return {
        "quote_date": (order_date - datetime.timedelta(days=rng.randint(3, 15))
                       ).isoformat(),
        "quote_ref": f"Q-{order_date.year}-{1200 + index}",
        "contact_person": "",
        "product_type": product_type,
        "ipc_class": "CLASS 3" if value > 50000 else "CLASS 2",
        "ccl_material": _MATERIAL[index % len(_MATERIAL)],
        "pcb_x_mm": pcb_x,
        "pcb_y_mm": pcb_y,
        "array_x_mm": round(pcb_x * (2 if ups > 1 else 1) + 10, 1),
        "array_y_mm": round(pcb_y * (ups // 2 if ups > 2 else 1) + 10, 1),
        "ups": ups,
        "panel_code": _PANELS[index % len(_PANELS)],
        "surface_finish": finish,
        "finish_thickness": finish_thickness,
        "layers": layers,
        "thickness_mm": thickness,
        "thickness_tol_pct": 10,
        "copper_outer_oz": rng.choice([1, 1, 2]),
        "copper_inner_oz": rng.choice([0.5, 1]),
        "impedance": 1 if layers >= 6 else 0,
        "impedance_note": "50Ω single-ended, 100Ω differential"
                          if layers >= 6 else "",
        "min_drill_mm": rng.choice([0.2, 0.25, 0.3]),
        "min_drill_count": rng.randint(40, 600),
        "total_drill_count": rng.randint(800, 9000),
        "bvh": 1 if layers >= 8 else 0,
        "bvh_layers": "1-2, %d-%d" % (layers - 1, layers) if layers >= 8 else "",
        "options": "V-cut, E-test, UL mark",
        "qty": qty,
        "lots": 1,
        "pcb_unit_krw": unit,
        "turnkey": 1 if turnkey else 0,
        "smt_unit_krw": round(unit * 0.55, -1) if turnkey else None,
        "stencil_count": 2 if turnkey else 0,
        "stencil_unit_krw": 140000 if turnkey else None,
        "parts_unit_krw": round(unit * 1.4, -1) if turnkey else None,
        "inflation_on": 1 if index % 4 == 0 else 0,
        "markup_on": 1,
        "markup_pct": rng.choice([20, 25, 30]),
    }


def load(seed: int = 7) -> dict:
    """Create the demo companies, orders and documents. Returns a count."""
    rng = random.Random(seed)
    today = datetime.date.today()

    for name, code, contact, mail, country, city in COMPANIES:
        orders.save_company({
            "name": name, "code": code, "contact_name": contact,
            "contact_email": mail, "country": country, "city": city,
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
        ("Hanwoo Electronics", "IN PRODUCTION", -22, 8, 31500, True),
        ("Hanwoo Electronics", "QUOTE", -2, 40, 7600, False),
        ("Andes Instrumentos", "CONFIRMED", -14, 19, 11250, True),
        ("Andes Instrumentos", "SHIPPED", -48, -6, 26400, True),
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

        # Most orders carry a full build spec, so the SPEC and COST tabs and
        # the printable sheet have something real to show straight away.
        if status != "CANCELLED":
            orders.save_spec(order_id, _spec(index, rng, value,
                                             order_date, po_number))

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
            # Put it through the mail reader rather than storing it as a
            # file, so the demo inbox shows real matching and real summaries
            # rather than a list of filenames.
            letter = _eml(
                contact[3], contact[2],
                f"{po_number} — delivery schedule for {order_no}",
                f"Hello,\n\nCould you confirm the delivery date on {order_no} "
                f"({po_number})? Our production plan currently assumes "
                f"{promise_date.isoformat()}.\n\nThe item is {product}.\n"
                f"If the date has moved, please tell us this week so we can "
                f"replan the line.\n\n"
                f"Best regards,\n{contact[2]}\n{company}\n",
                when=order_date + datetime.timedelta(days=rng.randint(1, 6)),
            )
            mailbox.intake(f"RE {po_number} delivery schedule.eml", letter)
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

    emails = _demo_inbox()
    disputes = _demo_cases(today)
    folders = _demo_folders(today)

    return {"companies": len(COMPANIES), "orders": created, "documents": docs,
            "emails": emails, "cases": disputes, "folders": folders}


def _demo_inbox() -> int:
    """A few mails that do not file themselves, so the tray has work in it."""
    stray = [
        ("procurement@newcomer-ems.example", "Procurement",
         "Introduction and capability request",
         "Good afternoon,\n\nWe are a contract manufacturer looking for a new "
         "PCB supplier for small and medium volumes.\nCould you send your "
         "capability sheet, minimum trace and space, and your standard lead "
         "times?\nWe would start with a trial order of around 100 pieces.\n\n"
         "Regards,\nProcurement\n"),
        ("k.sato@northwind-industrial.example", "Kenji Sato",
         "Quality escalation — repeated solder mask chipping",
         "Dear supplier,\n\nWe have now seen solder mask chipping on three "
         "consecutive deliveries.\nThe chipping is along the board edge on "
         "the routed side, about 0.5mm in.\nPlease investigate the routing "
         "step and tell us what you will change.\nWe need an 8D report by "
         "the end of next week.\n\nRegards,\nKenji Sato\n"),
    ]
    today = datetime.date.today()
    for days, (sender, name, subject, body) in zip((2, 5), stray):
        mailbox.intake(f"{subject[:40]}.eml",
                       _eml(sender, name, subject, body,
                            when=today - datetime.timedelta(days=days)))
    return len(mailbox.list_mail())


def _demo_cases(today) -> int:
    """Two disputes, one being worked and one settled, each with its log."""
    conn = db.connect()
    live = conn.execute(
        """SELECT id, order_no FROM orders
           WHERE status = 'IN PRODUCTION' ORDER BY id LIMIT 1""").fetchone()
    done = conn.execute(
        """SELECT id, order_no FROM orders
           WHERE status IN ('DELIVERED', 'PAID') ORDER BY id LIMIT 1""").fetchone()
    if live is None:
        return 0

    day = datetime.timedelta(days=1)
    open_case = cases.open_case({
        "order_id": live["id"],
        "title": "12 boards with open circuits on layer 4",
        "kind": "DEFECT", "severity": "HIGH", "qty_affected": 12,
        "claim_krw": 1250000, "lot_ref": "lot 3, working panel AJ(6)",
        "opened_at": (today - 3 * day).isoformat(),
        "due_at": (today + 2 * day).isoformat(),
        "owner": "YJ",
        "detail": "Customer AOI found 12 opens out of 500 delivered, all from "
                  "one working panel — most likely a single etch or drill "
                  "issue rather than a process drift.",
    }, actor="demo")
    cases.add_entry(open_case, {
        "kind": "EMAIL IN", "happened_at": (today - 3 * day).isoformat(),
        "who": "Quality, customer side",
        "summary": "Defect report received with AOI images",
        "detail": "12 pcs, layer 4 opens. Asked for rework or a credit note."})
    cases.add_entry(open_case, {
        "kind": "CALL", "happened_at": (today - 2 * day).isoformat(),
        "who": "Factory — Mr Cho",
        "summary": "Asked the factory for the cross-section report",
        "detail": "Cho will pull the drill log for that panel.",
        "follow_up_at": (today - 1 * day).isoformat()})
    cases.add_entry(open_case, {
        "kind": "DECISION", "happened_at": (today - 1 * day).isoformat(),
        "who": "YJ", "summary": "Offer rework of 12 pcs plus 5 spares",
        "detail": "Cheaper than a credit note and keeps their line running.",
        "follow_up_at": (today + 1 * day).isoformat()})

    made = 1
    if done is not None:
        settled = cases.open_case({
            "order_id": done["id"],
            "title": "Short shipment — 40 pcs missing from lot 2",
            "kind": "SHORTAGE", "severity": "MEDIUM", "qty_affected": 40,
            "claim_krw": 320000, "owner": "YJ",
            "opened_at": (today - 30 * day).isoformat(),
            "detail": "Packing list said 500, carton count was 460.",
        }, actor="demo")
        cases.add_entry(settled, {
            "kind": "MEETING", "happened_at": (today - 28 * day).isoformat(),
            "who": "Warehouse", "summary": "Recount confirmed 460 pieces"})
        cases.update_case(settled, {
            "status": "RESOLVED",
            "root_cause": "One carton left on the packing bench.",
            "resolution": "40 pcs shipped free of charge on the next flight.",
        }, actor="demo")
        made += 1
    return made


def _demo_folders(today) -> int:
    """Conversations that are not orders yet, in the state they are found in:
    one waiting on us, one waiting on them, one already won."""
    day = datetime.timedelta(days=1)
    plan = [
        {
            "company": "Acme Components Ltd",
            "topic": "RFQ — 6 layer 1.6mm ENIG, 2000 pcs per lot",
            "summary": "Price and lead time for a new 6L board, three lots "
                       "expected this year. Impedance controlled.",
            "situation": "Waiting on the factory for panel utilisation before "
                         "the price can be finalised.",
            "kind": "QUOTE REQUEST", "status": "WAITING ON US",
            "value_usd": 24000, "opened": 4, "due": 0,
            "log": [("EMAIL IN", 4, "RFQ received with gerbers", None),
                    ("CALL", 2, "Asked whether 1.55mm is acceptable", None),
                    ("ACTION", 1, "Get the panel count from the factory", 0)],
        },
        {
            "company": "Kestrel Marine Systems",
            "topic": "Sample request — 4 layer flex, 10 pcs",
            "summary": "Wants ten samples before committing to the production "
                       "order. Asked about bend radius.",
            "situation": "Samples shipped; waiting to hear how they tested.",
            "kind": "SAMPLE", "status": "WAITING ON THEM",
            "value_usd": 1800, "opened": 12, "due": 2,
            "log": [("EMAIL IN", 12, "Sample request with drawing", None),
                    ("EMAIL OUT", 9, "Quoted the samples and the tooling", None),
                    ("NOTE", 5, "Samples shipped, tracking MF-88213", None),
                    ("ACTION", 5, "Chase their test result", 2)],
        },
        {
            "company": "Hanwoo Electronics",
            "topic": "Stack-up question — 8 layer, controlled impedance 50Ω",
            "summary": "Engineering asked whether our standard stack-up meets "
                       "50Ω single-ended with 3 mil traces.",
            "situation": "Answered with the proposed stack-up; they confirmed "
                         "and placed the order.",
            "kind": "SPEC QUESTION", "status": "WON",
            "value_usd": 31500, "opened": 26, "due": None,
            "log": [("EMAIL IN", 26, "Impedance question from their engineer", None),
                    ("EMAIL OUT", 24, "Sent the proposed stack-up", None),
                    ("DECISION", 21, "They accepted and raised the PO", None)],
        },
    ]

    made = 0
    for item in plan:
        folder_id = threads.open_folder({
            "company": item["company"], "topic": item["topic"],
            "summary": item["summary"], "situation": item["situation"],
            "kind": item["kind"], "value_usd": item["value_usd"],
            "opened_at": (today - item["opened"] * day).isoformat(),
            "follow_up_at": ((today + item["due"] * day).isoformat()
                             if item["due"] is not None else ""),
            "owner": "YJ",
        }, actor="demo")
        for kind, days_ago, summary, follow_up in item["log"]:
            threads.add_entry(folder_id, {
                "kind": kind, "who": "YJ",
                "happened_at": (today - days_ago * day).isoformat(),
                "summary": summary,
                "follow_up_at": ((today + follow_up * day).isoformat()
                                 if follow_up is not None else "")})
        if item["status"] != "OPEN":
            threads.update_folder(folder_id, {"status": item["status"]},
                                  actor="demo")
        made += 1
    return made
