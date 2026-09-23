"""Saved email: read it, work out what it is about, and file it.

There is no mailbox connection here and there never will be — this machine
cannot reach the mail server, and nothing is sent anywhere. Email arrives
the way everything else does: you save it out of Outlook and drop it on the
page. What happens next is all local.

Three questions get answered about every mail, in this order:

  who sent it     from the headers, or from the .msg properties
  what it says    a short extract, made by scoring the sentences
  where it goes   matched against your orders, PO numbers and customers

The matching is deliberately cautious. A mail filed against the wrong
customer is worse than one left in the tray, so anything short of a clear
match is held for you to confirm, and the reason for every guess is kept
and shown.
"""

import email
import email.policy
import email.utils
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import db, documents, outlook, prefs

# --- reading the file ------------------------------------------------------

MAIL_SUFFIXES = {".eml", ".msg", ".mht", ".mhtml", ".txt"}

# Attachments worth keeping as documents of their own. A mail signature is
# mostly small inline images, which are noise in a document list.
SKIP_ATTACHMENT_SUFFIXES = {".p7s", ".p7m", ".asc", ".ics", ".vcf"}
SMALL_IMAGE_BYTES = 64 * 1024
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def looks_like_mail(filename: str, data: bytes = b"") -> bool:
    """Is this file worth sending through the mail reader?"""
    suffix = Path(filename).suffix.lower()
    if suffix in (".eml", ".msg", ".mht", ".mhtml"):
        return True
    if data[:8] == outlook.SIGNATURE:
        return True
    head = data[:2000].decode("utf-8", "replace").lower()
    return bool(re.search(r"^(from|subject|date):", head, re.M))


def _utc(when) -> str:
    if when is None:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _addresses(value) -> str:
    """A header full of recipients, flattened to a readable list."""
    pairs = email.utils.getaddresses([str(value or "")])
    out = [address or name for name, address in pairs if (address or name)]
    return ", ".join(out[:12])


def _keep_attachment(name: str, data: bytes) -> bool:
    suffix = Path(name).suffix.lower()
    if not data or suffix in SKIP_ATTACHMENT_SUFFIXES:
        return False
    if suffix in IMAGE_SUFFIXES and len(data) < SMALL_IMAGE_BYTES:
        return False          # a logo out of somebody's signature
    return True


def _from_mime(data: bytes) -> dict:
    message = email.message_from_bytes(data, policy=email.policy.default)
    name, address = email.utils.parseaddr(str(message.get("From") or ""))

    sent = ""
    try:
        parsed = email.utils.parsedate_to_datetime(str(message.get("Date")))
        sent = _utc(parsed)
    except (TypeError, ValueError):
        pass

    body = ""
    try:
        part = message.get_body(preferencelist=("plain",))
        if part is not None:
            body = part.get_content()
        else:
            part = message.get_body(preferencelist=("html",))
            if part is not None:
                from .extract.html import strip_tags
                body = strip_tags(part.get_content())
    except Exception:
        body = ""

    attachments = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        if not filename:
            continue
        try:
            payload = part.get_payload(decode=True) or b""
        except Exception:
            continue
        if _keep_attachment(filename, payload):
            attachments.append({"filename": filename, "data": payload})

    return {
        "subject": str(message.get("Subject") or ""),
        "from_name": name,
        "from_email": address,
        "to": _addresses(message.get("To")),
        "cc": _addresses(message.get("Cc")),
        "sent_at": sent,
        "body": body,
        "message_id": str(message.get("Message-ID") or ""),
        "attachments": attachments,
    }


def _from_outlook(data: bytes) -> dict:
    found = outlook.read(data)

    # Outlook keeps the original internet headers when the mail came from
    # outside; they are more trustworthy than its own copy of the fields.
    if found.get("headers"):
        try:
            header_view = _from_mime(found["headers"].encode("utf-8", "replace"))
        except Exception:
            header_view = {}
        for key in ("from_name", "from_email", "to", "cc", "sent_at",
                    "message_id"):
            if header_view.get(key) and not found.get(key):
                found[key] = header_view[key]
        if header_view.get("sent_at"):
            found["sent_at"] = header_view["sent_at"]
        if header_view.get("from_email"):
            found["from_email"] = header_view["from_email"]

    found["attachments"] = [
        a for a in found.get("attachments", [])
        if _keep_attachment(a["filename"], a.get("data") or b"")
    ]
    found.setdefault("message_id", "")
    return found


def parse(filename: str, data: bytes) -> dict:
    """Pull one saved email apart, whatever form it was saved in."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".msg" or data[:8] == outlook.SIGNATURE:
        found = _from_outlook(data)
    else:
        found = _from_mime(data)

    found["filename"] = filename
    found["from_domain"] = (found.get("from_email") or "").rpartition("@")[2].lower()
    found["subject"] = (found.get("subject") or "").strip()
    found["body"] = (found.get("body") or "").replace("\r\n", "\n")
    if not found.get("sent_at"):
        found["sent_at"] = ""
    return found


# --- reading what it says --------------------------------------------------

# Where a reply stops being new writing and starts being the mail it is
# replying to. Korean Outlook writes its own version of each of these.
_HISTORY = re.compile(
    r"^\s*(?:-{2,}\s*(?:original message|forwarded message|원본 메시지)"
    r"|from:\s|보낸\s*사람\s*:|de\s*:|von\s*:"
    r"|on .{0,120}\bwrote:\s*$"
    r"|.{0,80}님이\s*(?:작성|씀))",
    re.I | re.M)

_SIGNATURE = re.compile(r"^\s*(?:--\s*$|—\s*$|보내는 사람\s*$)", re.M)

_DISCLAIMER = re.compile(
    r"(this (?:e-?mail|message)[^\n]{0,80}(?:confidential|intended)"
    r"|본 (?:메일|이메일)[^\n]{0,40}(?:기밀|수신))", re.I)


def clean_body(text: str) -> str:
    """The part of a mail the sender actually typed this time.

    Replies carry the whole conversation underneath them. Summarising that
    gives you last week's news, so everything from the first quote marker
    down is cut away before anything else is done.
    """
    text = (text or "").replace("\r\n", "\n")

    match = _HISTORY.search(text)
    if match and match.start() > 0:
        text = text[:match.start()]

    lines = [line for line in text.split("\n") if not line.lstrip().startswith(">")]
    text = "\n".join(lines)

    match = _SIGNATURE.search(text)
    if match and match.start() > 40:
        text = text[:match.start()]

    match = _DISCLAIMER.search(text)
    if match and match.start() > 40:
        text = text[:match.start()]

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


STOP = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "at", "by", "from", "up", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "shall", "should", "can", "could", "may", "might", "must",
    "this", "that", "these", "those", "it", "its", "we", "you", "your", "our",
    "us", "they", "them", "their", "he", "she", "his", "her", "i", "me", "my",
    "not", "no", "so", "than", "then", "there", "here", "when", "which",
    "who", "what", "how", "all", "any", "each", "please", "kind", "regards",
    "thanks", "thank", "dear", "hello", "hi", "best", "sincerely", "mail",
    "email", "sent", "sincerly", "also", "about", "into", "over", "just",
    "감사합니다", "안녕하세요", "수고하세요", "드립니다", "합니다", "입니다",
    "있습니다", "관련", "확인", "부탁", "부탁드립니다", "회신",
}

# Words that mean something in this business. A sentence carrying one is
# worth more than its word counts alone suggest.
WEIGHTY = {
    "defect", "defective", "faulty", "reject", "rejected", "claim", "scrap",
    "rework", "delay", "delayed", "urgent", "asap", "deadline", "due",
    "delivery", "deliver", "ship", "shipped", "shipment", "quantity", "qty",
    "price", "cost", "quote", "quotation", "order", "invoice", "payment",
    "impedance", "gerber", "stackup", "panel", "layer", "drill", "tooling",
    "sample", "approval", "approve", "confirm", "confirmed", "hold",
    "불량", "클레임", "납기", "지연", "견적", "발주", "출하", "수량", "단가",
}

_SENTENCE = re.compile(r"(?<=[.!?。])\s+|\n+")
_WORD = re.compile(r"[0-9A-Za-z가-힣][0-9A-Za-z가-힣._/-]*")

MAX_SUMMARY_CHARS = 420


def sentences(text: str) -> list[str]:
    out = []
    for piece in _SENTENCE.split(text or ""):
        piece = piece.strip(" \t•-–*·")
        if len(piece) >= 12:
            out.append(re.sub(r"\s+", " ", piece))
    return out


def summarise(subject: str, body: str) -> tuple[str, list[str]]:
    """A few sentences worth reading, and the words the mail keeps using.

    Nothing clever and nothing trained: the words that repeat are taken to
    be what the mail is about, and the sentences carrying most of them are
    handed back in the order they were written. It runs in a blink, needs
    no network, and — unlike anything that writes new prose — it cannot
    invent a fact that was never in the mail.
    """
    text = clean_body(body)
    parts = sentences(text)
    if not parts:
        return "", []

    counts = Counter()
    for word in _WORD.findall(text.lower()):
        if len(word) > 1 and word not in STOP:
            counts[word] += 1
    for word in _WORD.findall((subject or "").lower()):
        if len(word) > 1 and word not in STOP:
            counts[word] += 2          # the subject line is a summary already

    if not counts:
        return parts[0][:MAX_SUMMARY_CHARS], []
    top = counts.most_common(1)[0][1]

    scored = []
    for position, sentence in enumerate(parts):
        words = {w for w in _WORD.findall(sentence.lower())
                 if len(w) > 1 and w not in STOP}
        if not words:
            continue
        score = sum(counts[w] for w in words) / (len(words) ** 0.5) / top
        if position == 0:
            score += 0.8               # openers usually state the business
        elif position <= 2:
            score += 0.3
        if words & WEIGHTY:
            score += 0.6
        if re.search(r"\d", sentence):
            score += 0.25              # quantities, dates and references
        if re.search(r"\?", sentence):
            score += 0.3               # a question needs answering
        scored.append((score, position, sentence))

    scored.sort(reverse=True)
    picked, used = [], 0
    for score, position, sentence in scored:
        if used + len(sentence) > MAX_SUMMARY_CHARS and picked:
            continue
        picked.append((position, sentence))
        used += len(sentence)
        if len(picked) >= 3 or used >= MAX_SUMMARY_CHARS:
            break
    picked.sort()

    summary = " ".join(sentence for _, sentence in picked)[:MAX_SUMMARY_CHARS]
    keywords = [word for word, _ in counts.most_common(8)
                if not word.isdigit()][:6]
    return summary.strip(), keywords


CATEGORIES = [
    ("DEFECT", ("defect", "defective", "faulty", "fault", "reject", "rejected",
                "claim", "complaint", "ncr", "scrap", "rework", "short circuit",
                "open circuit", "delamination", "warpage", "chipping",
                "peeling", "contamination", "escalation", "8d report",
                "corrective action", "non-conformance", "nonconformance",
                "quality issue", "out of spec", "불량",
                "클레임", "하자", "반품", "재작업", "품질")),
    ("DELIVERY", ("delivery", "lead time", "leadtime", "eta", "delay",
                  "delayed", "ship date", "shipment", "expedite", "dispatch",
                  "납기", "출하", "지연", "배송", "선적")),
    ("PURCHASE ORDER", ("purchase order", "p/o", "po number", "new order",
                        "order confirmation", "발주", "주문", "오더")),
    ("QUOTE", ("quotation", "quote", "rfq", "pricing", "price list",
               "견적", "단가", "견적서")),
    ("PAYMENT", ("invoice", "payment", "remittance", "overdue", "credit note",
                 "tax invoice", "입금", "세금계산서", "결제", "송금")),
    ("SPEC", ("gerber", "stack-up", "stackup", "impedance", "drawing",
              "datasheet", "artwork", "bom", "사양", "도면", "스펙")),
]


def categorise(subject: str, body: str) -> str:
    """One word for what the mail is about, used to sort the tray."""
    haystack = f"{subject or ''}\n{(body or '')[:4000]}".lower()
    best, best_score = "GENERAL", 0
    for name, words in CATEGORIES:
        score = 0
        for word in words:
            if word in haystack:
                # The subject line is where people say what they mean.
                score += len(word) * (3 if word in (subject or "").lower() else 1)
        if score > best_score:
            best, best_score = name, score
    return best


# --- what it refers to -----------------------------------------------------

_REFERENCE = r"([A-Z0-9][A-Z0-9/_-]{2,24}[A-Z0-9])"
PO_PATTERN = re.compile(
    r"(?:\bP\.?\s?O\.?\b|purchase\s+order|발주\s*번호|발주번호)[\s#:.\-]*" + _REFERENCE,
    re.I)
QUOTE_PATTERN = re.compile(
    r"(?:\bquotation\b|\bquote\b|\bqtn\b|\brfq\b|견적\s*번호|견적번호)[\s#:.\-]*"
    + _REFERENCE, re.I)
CODE_PATTERN = re.compile(r"\b[A-Z]{1,5}[-/]?\d{3,}(?:[-/][A-Z0-9]{1,6})?\b")

_NOT_A_REFERENCE = {"RE", "FW", "FWD", "PCB", "SMT", "PDF", "USD", "KRW"}


def find_references(text: str) -> dict:
    """Reference numbers written in the mail, whether or not we know them."""
    text = text or ""
    found = {"po": [], "quote": [], "codes": []}

    def add(bucket, value):
        value = value.strip(" .,:;-/").upper()
        if (value and value not in _NOT_A_REFERENCE
                and any(ch.isdigit() for ch in value)
                and value not in found[bucket]):
            found[bucket].append(value)

    def whole(match):
        """Prefer the full reference over the tail the label pattern left.

        "PO-2026-1188" is written as its own reference, so the label and
        the number are the same word; taking the capture alone would file
        it as "2026-1188" and match nothing.
        """
        code = CODE_PATTERN.search(match.group(0).upper())
        return code.group(0) if code else match.group(1)

    for match in PO_PATTERN.finditer(text):
        add("po", whole(match))
    for match in QUOTE_PATTERN.finditer(text):
        add("quote", whole(match))
    for match in CODE_PATTERN.finditer(text.upper()):
        add("codes", match.group(0))
    found["codes"] = [c for c in found["codes"]
                      if c not in found["po"] and c not in found["quote"]][:12]
    return found


# --- where it belongs ------------------------------------------------------

def _flat(text: str) -> str:
    """Upper case with the punctuation taken out, for loose comparison."""
    return re.sub(r"[^A-Z0-9가-힣]+", " ", (text or "").upper())


# A match at or above this files the mail by itself; below it, the mail
# waits in the tray for a person to agree.
AUTO_FILE = 0.8


def match(parsed: dict, conn=None) -> dict:
    """Decide which order and customer a mail belongs to, and how sure we are.

    Every signal that fired is recorded, because a filing decision you
    cannot explain is one you cannot trust.
    """
    conn = conn or db.connect()
    subject = _flat(parsed.get("subject"))
    attachment_names = " ".join(a["filename"] for a in parsed.get("attachments", []))
    body = _flat(f"{parsed.get('body', '')}\n{attachment_names}")
    sender = (parsed.get("from_email") or "").strip().lower()
    domain = (parsed.get("from_domain") or "").strip().lower()

    order_id = company_id = None
    confidence = 0.0
    reasons = []
    # Set when the mail names more than one order we know. Being sure of
    # the customer is then not enough: which order it is about changes what
    # anyone does next, so a person looks.
    ambiguous = False

    def claim(kind, value, score, reason):
        nonlocal order_id, company_id, confidence
        if kind == "order" and order_id is None:
            order_id = value
        if kind == "company" and company_id is None:
            company_id = value
        if score > confidence:
            confidence = score
        reasons.append(reason)

    # 1. A reference we already hold. Nothing beats this.
    rows = conn.execute(
        """SELECT o.id, o.order_no, o.po_number, o.company_id,
                  s.quote_ref
           FROM orders o LEFT JOIN order_specs s ON s.order_id = o.id"""
    ).fetchall()
    in_subject, in_body = {}, {}
    for row in rows:
        for label, reference in (("order number", row["order_no"]),
                                 ("PO number", row["po_number"]),
                                 ("quote reference", row["quote_ref"])):
            text = _flat(reference).strip()
            if not text or len(text) < 4:
                continue
            if f" {text} " in f" {subject} ":
                in_subject[row["id"]] = (label, reference, row["company_id"])
            elif f" {text} " in f" {body} ":
                in_body[row["id"]] = (label, reference, row["company_id"])

    for found, score, where in ((in_subject, 0.95, "the subject line"),
                                (in_body, 0.85, "the message")):
        if len(found) == 1:
            order, (label, reference, company) = next(iter(found.items()))
            claim("order", order, score,
                  f"{label} {reference} appears in {where}")
            claim("company", company, score, "customer taken from that order")
            break
        if len(found) > 1:
            ambiguous = True
            reasons.append(f"{len(found)} different orders are mentioned in "
                           f"{where}, so none was chosen")
            break

    # 2. The sender. An address that has been filed before is the strongest
    #    signal there is, because a person agreed to it last time.
    if sender and company_id is None:
        learned = conn.execute(
            """SELECT company_id, COUNT(*) AS n FROM emails
               WHERE from_email = ? AND company_id IS NOT NULL
                 AND needs_review = 0
               GROUP BY company_id ORDER BY n DESC""",
            (sender,)).fetchall()
        if len(learned) == 1:
            claim("company", learned[0]["company_id"], 0.9,
                  f"mail from {sender} has been filed to this customer "
                  f"{learned[0]['n']} time(s) before")

    if sender and company_id is None:
        exact = conn.execute(
            "SELECT id FROM companies WHERE LOWER(contact_email) = ?",
            (sender,)).fetchall()
        if len(exact) == 1:
            claim("company", exact[0]["id"], 0.9,
                  f"{sender} is the contact address on file")

    if domain and company_id is None:
        by_domain = conn.execute(
            "SELECT id, name, contact_email FROM companies "
            "WHERE contact_email LIKE ?", ("%@" + domain,)).fetchall()
        if len(by_domain) == 1:
            claim("company", by_domain[0]["id"], 0.75,
                  f"{domain} is the mail domain of {by_domain[0]['name']}")
        elif len(by_domain) > 1:
            reasons.append(f"{domain} matches {len(by_domain)} customers")

    # 3. The customer's name, written out in the mail.
    if company_id is None:
        named = []
        for row in conn.execute("SELECT id, name, code FROM companies"):
            name = _flat(row["name"]).strip()
            if len(name) >= 4 and name in f"{subject} {body}":
                named.append((row["id"], row["name"]))
        if len(named) == 1:
            claim("company", named[0][0], 0.7,
                  f"{named[0][1]} is named in the mail")

    # 4. With the customer known but no order named, offer the one open
    #    order if there is exactly one. Never filed automatically.
    if company_id is not None and order_id is None:
        open_orders = conn.execute(
            """SELECT id, order_no FROM orders
               WHERE company_id = ? AND status NOT IN ('PAID', 'CANCELLED')
               ORDER BY updated_at DESC""", (company_id,)).fetchall()
        if len(open_orders) == 1:
            order_id = open_orders[0]["id"]
            confidence = min(confidence, 0.6)
            reasons.append(f"{open_orders[0]['order_no']} is the only open "
                           f"order for this customer — please confirm")
        elif len(open_orders) > 1:
            reasons.append(f"this customer has {len(open_orders)} open orders, "
                           f"so none was chosen")

    if not reasons:
        reasons.append("nothing in the mail matched a customer or an order")

    threshold = float(prefs.get("auto_file_confidence") or AUTO_FILE)
    return {
        "order_id": order_id,
        "company_id": company_id,
        "confidence": round(confidence, 2),
        "reasons": reasons,
        "needs_review": 0 if (confidence >= threshold and company_id
                              and not ambiguous) else 1,
    }


# --- filing it -------------------------------------------------------------

def _direction(parsed: dict) -> str:
    """Did this come in, or did we send it?"""
    sender = (parsed.get("from_email") or "").lower()
    mine = [str(a).strip().lower() for a in (prefs.get("my_addresses") or [])
            if str(a).strip()]
    for entry in mine:
        if sender == entry or sender.endswith("@" + entry.lstrip("@")):
            return "OUT"
    return "IN"


def intake(filename: str, data: bytes, order_id=None, actor="") -> dict:
    """Read one saved email, file it, and keep what was worked out about it.

    The mail itself is stored as a document so it stays searchable and can
    be opened again; its attachments are stored as documents in their own
    right, because the PO everyone actually wants is usually the PDF inside
    rather than the mail around it.
    """
    parsed = parse(filename, data)
    conn = db.connect()

    key = hashlib.sha256(data).hexdigest()
    seen = conn.execute("SELECT * FROM emails WHERE message_key = ?",
                        (key,)).fetchone()
    if seen:
        return dict(seen) | {"duplicate": True}

    summary, keywords = summarise(parsed["subject"], parsed["body"])
    category = categorise(parsed["subject"], parsed["body"])
    refs = find_references(f"{parsed['subject']}\n{parsed['body']}")

    if order_id:
        row = conn.execute("SELECT company_id FROM orders WHERE id = ?",
                           (order_id,)).fetchone()
        decision = {
            "order_id": order_id,
            "company_id": row["company_id"] if row else None,
            "confidence": 1.0,
            "reasons": ["filed by hand" + (f" by {actor}" if actor else "")],
            "needs_review": 0,
        }
    else:
        decision = match(parsed, conn)

    document = documents.store(
        filename, data,
        order_id=decision["order_id"],
        company_id=decision["company_id"],
        kind="EMAIL")

    stored_attachments = 0
    for attachment in parsed.get("attachments", []):
        if not attachment.get("data"):
            continue
        try:
            documents.store(attachment["filename"], attachment["data"],
                            order_id=decision["order_id"],
                            company_id=decision["company_id"])
            stored_attachments += 1
        except (ValueError, OSError):
            continue          # one oversized attachment must not lose the mail

    with conn:
        cursor = conn.execute(
            """INSERT INTO emails(doc_id, order_id, company_id, direction,
                                  message_key, sent_at, from_name, from_email,
                                  from_domain, to_addrs, subject, summary,
                                  keywords, category, refs, confidence,
                                  matched_on, needs_review, attachments,
                                  filed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (document["id"], decision["order_id"], decision["company_id"],
             _direction(parsed), key, parsed["sent_at"] or None,
             parsed.get("from_name"), (parsed.get("from_email") or "").lower(),
             parsed.get("from_domain"), parsed.get("to"), parsed["subject"],
             summary, ", ".join(keywords), category, json.dumps(refs),
             decision["confidence"], " · ".join(decision["reasons"]),
             decision["needs_review"], stored_attachments, db.now()))
        db.touch(conn)

    return get(cursor.lastrowid)


DIRECTIONS = ("IN", "OUT")


def set_direction(mail_id: int, direction: str) -> dict:
    """Say by hand whether a mail came in or went out.

    The guess is made from your own addresses, which cannot know about a
    mail a colleague forwarded on, or one saved from the Sent folder of
    somebody else's mailbox. A person saying so settles it — and the
    folders and cases it has been logged in are corrected with it, so the
    log never says "received" about something you sent.
    """
    wanted = str(direction or "").strip().upper()
    if wanted in ("SENT", "OUTGOING"):
        wanted = "OUT"
    if wanted in ("RECEIVED", "INCOMING"):
        wanted = "IN"
    if wanted not in DIRECTIONS:
        raise ValueError("A mail is either IN or OUT.")

    conn = db.connect()
    row = conn.execute("SELECT id FROM emails WHERE id = ?",
                       (mail_id,)).fetchone()
    if row is None:
        raise ValueError("That email is not on file.")

    entry_kind = f"EMAIL {wanted}"
    with conn:
        conn.execute("UPDATE emails SET direction = ? WHERE id = ?",
                     (wanted, mail_id))
        for table in ("thread_entries", "case_entries"):
            conn.execute(
                f"""UPDATE {table} SET kind = ?
                    WHERE email_id = ? AND kind IN ('EMAIL IN', 'EMAIL OUT')""",
                (entry_kind, mail_id))
        db.touch(conn)
    return get(mail_id)


def get(mail_id: int) -> dict | None:
    row = db.connect().execute(
        """SELECT e.*, o.order_no, o.product_code, o.product_name,
                  c.name AS company,
                  t.ref AS folder_ref, t.topic AS folder_topic
           FROM emails e
           LEFT JOIN orders o ON o.id = e.order_id
           LEFT JOIN companies c ON c.id = e.company_id
           LEFT JOIN threads t ON t.id = e.thread_id
           WHERE e.id = ?""", (mail_id,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["refs"] = json.loads(item.get("refs") or "{}")
    item["reasons"] = [r for r in (item.get("matched_on") or "").split(" · ") if r]
    return item


def list_mail(needs_review=None, order_id=None, company_id=None,
              category=None, direction=None, query=None,
              limit=300) -> list[dict]:
    sql = ["""SELECT e.*, o.order_no, o.product_code, o.product_name,
                     c.name AS company,
                     t.ref AS folder_ref, t.topic AS folder_topic
              FROM emails e
              LEFT JOIN orders o ON o.id = e.order_id
              LEFT JOIN companies c ON c.id = e.company_id
              LEFT JOIN threads t ON t.id = e.thread_id"""]
    where, params = [], []
    if needs_review is not None:
        where.append("e.needs_review = ?")
        params.append(1 if needs_review else 0)
    if order_id:
        where.append("e.order_id = ?")
        params.append(order_id)
    if company_id:
        where.append("e.company_id = ?")
        params.append(company_id)
    if category:
        where.append("e.category = ?")
        params.append(category)
    if direction:
        where.append("e.direction = ?")
        params.append(str(direction).upper())
    if query:
        where.append("(e.subject LIKE ? OR e.from_email LIKE ? "
                     "OR e.summary LIKE ? OR e.from_name LIKE ?)")
        params += [f"%{query}%"] * 4
    if where:
        sql.append("WHERE " + " AND ".join(where))
    sql.append("ORDER BY COALESCE(e.sent_at, e.filed_at) DESC, e.id DESC LIMIT ?")
    params.append(limit)

    out = []
    for row in db.connect().execute(" ".join(sql), params):
        item = dict(row)
        item["refs"] = json.loads(item.get("refs") or "{}")
        out.append(item)
    return out


def assign(mail_id: int, order_id=None, company_id=None, confirmed=True) -> dict:
    """Put a mail where a person says it goes, and take it as settled."""
    conn = db.connect()
    mail = conn.execute("SELECT * FROM emails WHERE id = ?", (mail_id,)).fetchone()
    if mail is None:
        raise ValueError("That email is not in the tray.")

    if order_id:
        row = conn.execute("SELECT company_id FROM orders WHERE id = ?",
                           (order_id,)).fetchone()
        if row is None:
            raise ValueError("That order no longer exists.")
        company_id = row["company_id"]

    with conn:
        conn.execute(
            """UPDATE emails SET order_id = ?, company_id = ?,
                                 needs_review = ?, confidence = ?,
                                 matched_on = ?
               WHERE id = ?""",
            (order_id, company_id, 0 if confirmed else 1,
             1.0 if confirmed else mail["confidence"],
             "filed by hand" if confirmed else mail["matched_on"], mail_id))
        db.touch(conn)

    if mail["doc_id"]:
        try:
            documents.attach(mail["doc_id"], order_id, company_id)
        except ValueError:
            pass
    return get(mail_id)


def delete(mail_id: int, with_document=True) -> None:
    conn = db.connect()
    mail = conn.execute("SELECT doc_id FROM emails WHERE id = ?",
                        (mail_id,)).fetchone()
    with conn:
        conn.execute("DELETE FROM emails WHERE id = ?", (mail_id,))
    if mail and mail["doc_id"] and with_document:
        documents.delete(mail["doc_id"])


def tray() -> dict:
    """What the inbox looks like at a glance, for the dashboard."""
    conn = db.connect()
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN needs_review = 1 THEN 1 ELSE 0 END) AS review,
                  SUM(CASE WHEN order_id IS NULL THEN 1 ELSE 0 END) AS unfiled
           FROM emails""").fetchone()
    by_category = {r["category"]: r["n"] for r in conn.execute(
        "SELECT category, COUNT(*) AS n FROM emails GROUP BY category")}
    return {
        "total": row["total"] or 0,
        "needs_review": row["review"] or 0,
        "unfiled": row["unfiled"] or 0,
        "by_category": by_category,
    }
