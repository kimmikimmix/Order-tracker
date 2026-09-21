"""Read .eml / .msg email files, including any attachments worth indexing.

Saved emails are how a lot of purchase orders actually arrive, so the body
text, the subject line and the sender all need to be searchable — and any PDF
attached to the mail needs to be pulled out and read too.
"""

import email
import email.policy
import tempfile
from pathlib import Path

# Attachments worth pulling text out of. Everything else is noted but skipped.
_READABLE = {".pdf", ".txt", ".csv", ".xlsx", ".docx"}


def extract(path) -> tuple[str, str]:
    try:
        msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    except Exception as exc:  # malformed mail is common enough to expect
        return "", f"could not parse email: {exc}"

    lines = []
    for header in ("From", "To", "Cc", "Date", "Subject"):
        value = msg.get(header)
        if value:
            lines.append(f"{header}: {value}")
    lines.append("")

    body = _best_body(msg)
    if body:
        lines.append(body)

    attach_notes = []
    for part in msg.walk():
        name = part.get_filename()
        if not name or part.get_content_maintype() == "multipart":
            continue
        suffix = Path(name).suffix.lower()
        lines.append(f"\n[attachment: {name}]")
        if suffix not in _READABLE:
            attach_notes.append(f"{name} (not indexed)")
            continue
        try:
            payload = part.get_payload(decode=True) or b""
        except Exception:
            continue
        text = _text_from_attachment(payload, suffix)
        if text:
            lines.append(text)

    note = ""
    if attach_notes:
        note = "attachments stored but not text-indexed: " + ", ".join(attach_notes)
    return "\n".join(lines).strip(), note


def _best_body(msg) -> str:
    """Prefer the plain-text body; fall back to stripping the HTML one."""
    try:
        part = msg.get_body(preferencelist=("plain",))
        if part is not None:
            return part.get_content()
        part = msg.get_body(preferencelist=("html",))
        if part is not None:
            from .html import strip_tags
            return strip_tags(part.get_content())
    except Exception:
        pass
    return ""


def _text_from_attachment(payload: bytes, suffix: str) -> str:
    """Write the attachment somewhere temporary and run the right extractor."""
    if suffix in (".txt", ".csv"):
        return payload.decode("utf-8", "replace")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    try:
        if suffix == ".pdf":
            from .pdf import extract as pdf_extract
            return pdf_extract(tmp_path)[0]
        from .office import extract as office_extract
        return office_extract(tmp_path)[0]
    except Exception:
        return ""
    finally:
        tmp_path.unlink(missing_ok=True)
