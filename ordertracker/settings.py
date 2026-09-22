"""Remembered settings: chiefly where your orders and documents are kept.

Normally saved outside the app folder, in the place each operating system
sets aside for program settings, so updating or re-downloading the app never
disturbs your choice of storage location.

A portable folder is the exception. There the settings file sits beside
run.py, so the folder is genuinely self-contained: unplug the drive, plug it
into another machine, and your name on the welcome screen comes with it.
"""

import json
import os
import sys
from pathlib import Path

APP_NAME = "OrderTracker"

# Computed here rather than read from config, which imports this module.
PORTABLE_MARKER = Path(__file__).resolve().parent.parent / "portable.txt"

DEFAULTS = {
    # Folder holding data/ and demo-data/. Empty means "next to the app".
    "workspace": "",
    # Shown on the welcome screen at startup.
    "welcome_name": "",
    "show_welcome": True,
}


def portable() -> bool:
    """True when this copy keeps everything in its own folder."""
    return PORTABLE_MARKER.exists()


def machine_dir() -> Path:
    """The per-user folder this platform keeps program settings in."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "order-tracker"


def settings_dir() -> Path:
    """Where this copy of the app keeps its settings file."""
    return PORTABLE_MARKER.parent if portable() else machine_dir()


def settings_path() -> Path:
    return settings_dir() / "settings.json"


def _read_order() -> list[Path]:
    """Files to try, best first.

    A folder that has only just been made portable has no settings of its
    own yet, so this machine's copy is read instead and carried over the
    first time anything is saved. Nothing is lost in the changeover.
    """
    paths = [settings_path()]
    machine = machine_dir() / "settings.json"
    if portable() and machine not in paths:
        paths.append(machine)
    return paths


def read_file(path: Path) -> dict | None:
    """One settings file, or None when it is absent or damaged."""
    try:
        stored = json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(stored, dict):
        return None
    return {k: v for k, v in stored.items() if k in DEFAULTS}


def load() -> dict:
    """Saved settings, with anything missing filled in from the defaults."""
    values = dict(DEFAULTS)
    for path in _read_order():
        stored = read_file(path)
        if stored is not None:
            values.update(stored)
            break
    return values


def dump(path, values: dict) -> Path:
    """Write a settings file at an exact place. Used when moving a copy."""
    path = Path(path)
    keep = {k: v for k, v in values.items() if k in DEFAULTS}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**DEFAULTS, **keep}, indent=2), encoding="utf-8")
    return path


def save(**changes) -> Path:
    """Update the saved settings and return where they were written."""
    values = load()
    values.update({k: v for k, v in changes.items() if k in DEFAULTS})
    return dump(settings_path(), values)


def expand(folder: str) -> Path:
    """Resolve a folder the user typed, including %VARS% and ~."""
    return Path(os.path.expandvars(str(folder))).expanduser()


def workspace() -> Path | None:
    """The chosen storage folder, or None when the app folder is being used."""
    chosen = load().get("workspace") or ""
    return expand(chosen).resolve() if chosen.strip() else None
