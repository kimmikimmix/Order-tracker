"""Stopping two machines opening the same order book at once.

On a local disk this hardly matters: the app already refuses to start twice
on one machine. On a shared folder it matters a great deal. SQLite's locking
cannot be relied on over a network filesystem, so two computers writing to
the same database is the way to corrupt it — quietly, and usually a while
after the damage is done.

So a machine leaves a note in the data folder saying it has the book open,
and refreshes it while it runs. Another machine finding a fresh note from
somewhere else stops and says whose it is.

The note is advisory, not a lock: a file on a share cannot be anything else.
It catches the honest mistake of two people opening the same folder, which
is the case that actually happens.
"""

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

from . import config

NOTE_NAME = "in-use.json"

# A note not refreshed for this long belongs to a session that died.
STALE_SECONDS = 300
REFRESH_SECONDS = 60


def note_path() -> Path:
    return config.DATA_DIR / NOTE_NAME


def this_machine() -> str:
    try:
        return socket.gethostname() or "unknown"
    except Exception:
        return "unknown"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def read() -> dict | None:
    """Whoever has it open, as far as the note says."""
    try:
        note = json.loads(note_path().read_text("utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(note, dict) or "host" not in note:
        return None
    return note


def age_seconds(note: dict) -> float:
    try:
        when = datetime.fromisoformat(note["at"])
    except (KeyError, TypeError, ValueError):
        return STALE_SECONDS + 1
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (_now() - when).total_seconds()


def held_elsewhere() -> dict | None:
    """A fresh note from another machine, or None if we are free to open.

    A note from this machine is not in the way: starting twice here is
    already handled, and a crash leaves a note nobody will clean up.
    """
    note = read()
    if note is None:
        return None
    if note.get("host") == this_machine():
        return None
    if age_seconds(note) > STALE_SECONDS:
        return None
    return note


def claim() -> Path | None:
    """Say this machine has the book open. Harmless if it cannot be written."""
    note = {
        "host": this_machine(),
        "pid": os.getpid(),
        "at": _now().isoformat(timespec="seconds"),
        "data": str(config.DATA_DIR),
    }
    path = note_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(note, indent=2), encoding="utf-8")
    except OSError:
        return None      # a read-only folder is not a reason to refuse to run
    return path


def release() -> None:
    """Give it up on the way out, so the next machine does not have to wait."""
    note = read()
    if note is not None and note.get("host") != this_machine():
        return           # not ours to remove
    try:
        note_path().unlink(missing_ok=True)
    except OSError:
        pass


def describe(note: dict) -> str:
    """The warning to show when someone else has it."""
    minutes = max(1, int(age_seconds(note) // 60))
    return (
        f"{note.get('host', 'Another computer')} has this order book open.\n"
        f"    {note.get('data', config.DATA_DIR)}\n"
        f"    last seen {minutes} minute(s) ago\n"
        "\n"
        "Two machines writing to one database on a shared folder is how it\n"
        "gets corrupted. Close it there first.\n"
        "\n"
        "If that machine crashed, the note clears itself after five minutes,\n"
        "or start with --force to ignore it."
    )
