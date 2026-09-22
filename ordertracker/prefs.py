"""Editable settings that live with your data.

config.py holds the things a developer changes; this holds the things a
salesperson changes — exchange rate, markup, the lists of panel sizes and
surface finishes, how many days count as "due soon".

They are kept in the database rather than in a file next to the app, so they
travel with the orders when the data folder moves to another drive or
machine, and so the settings page can write them without touching code.
"""

import json
import threading

from . import config, db

# Every key the settings page can write, with the value used until it does.
DEFAULTS = {
    # --- money -------------------------------------------------------------
    # Won per dollar. Costs are entered in KRW and shown in both.
    "fx_rate": 1050.0,
    "inflation_rate": 1.25,
    "markup_pct": 25.0,
    # A stencil runs 130,000-150,000 KRW; two are needed when both sides
    # are populated.
    "stencil_unit_krw": 140000.0,
    "stencil_min_krw": 130000.0,
    "stencil_max_krw": 150000.0,

    # --- alerting ----------------------------------------------------------
    "due_soon_days": config.DUE_SOON_DAYS,
    "stalled_days": config.STALLED_DAYS,

    # --- spec vocabulary ---------------------------------------------------
    # Each list feeds a drop-down on the order form. Add your own freely.
    "product_types": ["RIGID", "FLEX", "FLEX-RIGID"],
    "ipc_classes": ["CLASS 1", "CLASS 2", "CLASS 3"],
    "panel_sizes": [
        {"code": "J(6)", "x": 507, "y": 404},
        {"code": "J(4)", "x": 507, "y": 607},
        {"code": "AJ(6)", "x": 532, "y": 607},
        {"code": "R(8)", "x": 454, "y": 607},
        {"code": "R(6)", "x": 454, "y": 404},
        {"code": "R(4)", "x": 454, "y": 302},
    ],
    # Unusable edge left around a working panel, per side.
    "panel_margin_mm": 10.0,
    "surface_finishes": [
        "ENIG", "HASL", "LEAD-FREE HASL", "OSP", "IMMERSION SILVER",
        "IMMERSION TIN", "ENEPIG", "HARD GOLD", "GOLD FINGER",
    ],
    "ccl_materials": [
        "FR-4 TG140", "FR-4 TG150", "FR-4 TG170", "185 HR", "IT-180A",
        "ROGERS 4003C", "ROGERS 4350B", "POLYIMIDE", "ALUMINIUM",
    ],

    # --- email intake ------------------------------------------------------
    # Your own addresses, so mail you sent is marked as going out rather
    # than coming in. A bare domain counts too: "ourcompany.com".
    "my_addresses": [],
    # How sure the matching has to be before a mail files itself. Lower it
    # to have more filed for you, raise it to check more by hand.
    "auto_file_confidence": 0.8,

    # --- disputes and defects ----------------------------------------------
    "case_kinds": ["DEFECT", "SHORTAGE", "DELAY", "WRONG SPEC", "DAMAGE",
                   "PRICE", "OTHER"],
    "case_severities": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    "case_statuses": ["OPEN", "INVESTIGATING", "AWAITING CUSTOMER",
                      "AWAITING FACTORY", "RESOLVED", "CLOSED", "REJECTED"],
    "case_entry_kinds": ["EMAIL IN", "EMAIL OUT", "CALL", "MEETING", "VISIT",
                         "NOTE", "ACTION", "DECISION"],
    # A new case is chased by this date unless you set another.
    "case_due_days": 7,

    # --- housekeeping ------------------------------------------------------
    # Second home for your data. Empty means backups are not being taken.
    "backup_dir": "",
    "backup_on_start": True,
    "backup_keep": 10,
    # Where you are. The map clocks are shown relative to this.
    "home_country": "KR",
}

_lock = threading.Lock()
_cache = None


def _coerce(key, value):
    """Keep a written value the same shape as its default."""
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, float):
        try:
            return float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return default
    if isinstance(default, int):
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return default
    if isinstance(default, list):
        return value if isinstance(value, list) else default
    return "" if value is None else str(value)


def load() -> dict:
    """Every setting, saved values over defaults."""
    global _cache
    with _lock:
        if _cache is not None:
            return dict(_cache)
    values = dict(DEFAULTS)
    try:
        row = db.connect().execute(
            "SELECT value FROM meta WHERE key = 'prefs'"
        ).fetchone()
    except Exception:
        return values  # database not ready yet; defaults still work
    if row and row["value"]:
        try:
            stored = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            stored = {}
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULTS:
                    values[key] = _coerce(key, value)
    with _lock:
        _cache = dict(values)
    return values


def get(key):
    return load().get(key, DEFAULTS.get(key))


def save(changes: dict) -> dict:
    """Write the settings the page sent and return the full set."""
    global _cache
    values = load()
    for key, value in (changes or {}).items():
        if key in DEFAULTS:
            values[key] = _coerce(key, value)
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('prefs', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(values, ensure_ascii=False),),
        )
    with _lock:
        _cache = dict(values)
    return values


def reset() -> dict:
    """Put every setting back to the value it shipped with."""
    global _cache
    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM meta WHERE key = 'prefs'")
    with _lock:
        _cache = None
    return load()


def forget_cache() -> None:
    """Drop the in-memory copy. Used by the tests and after a restore."""
    global _cache
    with _lock:
        _cache = None
