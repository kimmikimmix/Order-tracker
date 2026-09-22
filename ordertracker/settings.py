"""Remembered settings: chiefly where your orders and documents are kept.

Saved outside the app folder, in the place each operating system sets aside
for program settings, so updating or re-downloading the app never disturbs
your choice of storage location.
"""

import json
import os
import sys
from pathlib import Path

APP_NAME = "OrderTracker"

DEFAULTS = {
    # Folder holding data/ and demo-data/. Empty means "next to the app".
    "workspace": "",
    # Shown on the welcome screen at startup.
    "welcome_name": "",
    "show_welcome": True,
}


def settings_dir() -> Path:
    """The per-user folder this platform keeps program settings in."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "order-tracker"


def settings_path() -> Path:
    return settings_dir() / "settings.json"


def load() -> dict:
    """Saved settings, with anything missing filled in from the defaults."""
    values = dict(DEFAULTS)
    path = settings_path()
    try:
        stored = json.loads(path.read_text("utf-8"))
        if isinstance(stored, dict):
            values.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, json.JSONDecodeError, ValueError):
        pass  # no settings yet, or a damaged file — the defaults still work
    return values


def save(**changes) -> Path:
    """Update the saved settings and return where they were written."""
    values = load()
    values.update({k: v for k, v in changes.items() if k in DEFAULTS})
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2), encoding="utf-8")
    return path


def expand(folder: str) -> Path:
    """Resolve a folder the user typed, including %VARS% and ~."""
    return Path(os.path.expandvars(str(folder))).expanduser()


def workspace() -> Path | None:
    """The chosen storage folder, or None when the app folder is being used."""
    chosen = load().get("workspace") or ""
    return expand(chosen).resolve() if chosen.strip() else None
