"""Configuration: paths, the order pipeline, and alert thresholds.

Everything here is meant to be edited by hand. The pipeline in particular
should be renamed to match how your business actually talks about orders.
"""

import os
from pathlib import Path

from . import settings

# --- Paths -----------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

# Portable mode: a file called portable.txt next to run.py means "keep
# everything in this folder and ignore any saved setting". That makes the
# whole app self-contained, so it can live on a removable or personal drive
# and still work when the drive letter changes between machines.
PORTABLE_MARKER = BASE_DIR / "portable.txt"
PORTABLE = PORTABLE_MARKER.exists()

# Where your orders and documents are kept. Pick this once with `setup.py`
# — it is remembered outside the app folder, so re-downloading or updating
# the app never moves your data.
WORKSPACE = BASE_DIR if PORTABLE else (settings.workspace() or BASE_DIR)

DATA_DIR = Path(os.environ.get("ORDER_TRACKER_DATA", WORKSPACE / "data"))
DEMO_DIR = WORKSPACE / "demo-data"
DOCS_DIR = DATA_DIR / "documents"
DB_PATH = DATA_DIR / "orders.db"
WEB_DIR = BASE_DIR / "web"
ASSETS_DIR = BASE_DIR / "assets"

HOST = os.environ.get("ORDER_TRACKER_HOST", "127.0.0.1")
PORT = int(os.environ.get("ORDER_TRACKER_PORT", "8787"))

# Largest single upload accepted, in bytes.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

# --- What the numbers on an order are called -------------------------------
# The office works in Korean, so the Korean name leads and the English one
# sits under it in small type. Change either word here and every screen,
# the printed sheet and the spreadsheet import all follow.

FIELD_LABELS = {
    "product_name":  ("모델 이름", "PRODUCT NAME"),
    "product_code":  ("관리번호", "CONTROL NO"),
    "order_no":      ("주문번호", "ORDER NO"),
    "work_order_no": ("작지번호", "WORK ORDER NO"),
}


def label(field: str, joiner: str = " ") -> str:
    """Both names of a field as one piece of plain text."""
    return joiner.join(FIELD_LABELS.get(field, (field,)))


# --- Pipeline --------------------------------------------------------------
# Ordered list of the stages an order moves through. Rename freely; the UI,
# the board view and the "stalled" logic all read from this list.

PIPELINE = [
    "QUOTE",
    "ORDER RECEIVED",
    "CONFIRMED",
    "IN PRODUCTION",
    "READY TO SHIP",
    "SHIPPED",
    "DELIVERED",
    "INVOICED",
    "PAID",
]

# Stages that mean "nothing more to chase". Orders here never raise alerts.
TERMINAL_STATUSES = {"PAID", "CANCELLED"}

# Off-pipeline stages, always available.
SPECIAL_STATUSES = ["ON HOLD", "CANCELLED"]

ALL_STATUSES = PIPELINE + SPECIAL_STATUSES

# --- Dates -----------------------------------------------------------------
# How to read an ambiguous slash date like 03/12/2026 when it arrives from a
# spreadsheet or a typed field.
#   "MDY" -> 3 December 2026 is written 12/03/2026   (US convention)
#   "DMY" -> 3 December 2026 is written 03/12/2026   (most of the rest)
# Unambiguous forms (2026-12-03, 3-Dec-2026) are always understood either way.
DATE_INPUT_ORDER = "MDY"

# --- Alert thresholds ------------------------------------------------------

# An open order whose promise date is this many days out (or fewer) is "due soon".
DUE_SOON_DAYS = 7

# An open order untouched for this many days is "stalled".
STALLED_DAYS = 14

# Once an order reaches this stage it is expected to have a customer PO on file.
PO_REQUIRED_FROM = "CONFIRMED"

# Document kinds recognised at upload time. Entries beginning with a dot are
# file extensions and are decided first; otherwise the longest keyword that
# matches wins, so "purchase order" beats a stray "po" elsewhere in the name.
DOC_KINDS = {
    "PO": ("po", "purchase order", "purchaseorder", "order form"),
    "QUOTE": ("quote", "quotation", "proposal", "estimate"),
    "INVOICE": ("invoice", "bill", "rechnung"),
    "PACKING LIST": ("packing", "packlist", "delivery note", "despatch"),
    "CONTRACT": ("contract", "agreement", "terms", "msa", "nda"),
    "SPEC": ("spec", "drawing", "datasheet", "bom"),
    "EMAIL": (".eml", ".msg"),
    "PHOTO": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic",
              "photo", "picture", "사진"),
}


# --- Scratch space ---------------------------------------------------------

def use_own_temp(folder=None):
    """Keep temporary files inside the workspace, and tidy old ones away.

    Reading a PDF out of an email, or writing the little script that makes
    the desktop icon, goes through a temporary file first. On a work
    computer where only approved programs may write to the system disk that
    fails, so the scratch folder is put beside the data instead — somewhere
    we already know can be written to, because the orders are kept there.

    Returns the folder in use, or None when it could not be made, in which
    case the system temporary folder is left alone.
    """
    import tempfile
    import time

    scratch = Path(folder) if folder else DATA_DIR / ".scratch"
    try:
        scratch.mkdir(parents=True, exist_ok=True)
        probe = scratch / ".probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return None

    day_ago = time.time() - 86400
    for leftover in scratch.iterdir():
        try:
            if leftover.is_file() and leftover.stat().st_mtime < day_ago:
                leftover.unlink()
        except OSError:
            pass

    tempfile.tempdir = str(scratch)
    return scratch
