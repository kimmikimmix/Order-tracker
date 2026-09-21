"""Configuration: paths, the order pipeline, and alert thresholds.

Everything here is meant to be edited by hand. The pipeline in particular
should be renamed to match how your business actually talks about orders.
"""

import os
from pathlib import Path

# --- Paths -----------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ORDER_TRACKER_DATA", BASE_DIR / "data"))
DOCS_DIR = DATA_DIR / "documents"
DB_PATH = DATA_DIR / "orders.db"
WEB_DIR = BASE_DIR / "web"

HOST = os.environ.get("ORDER_TRACKER_HOST", "127.0.0.1")
PORT = int(os.environ.get("ORDER_TRACKER_PORT", "8787"))

# Largest single upload accepted, in bytes.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

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
}
