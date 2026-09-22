"""Telling a local disk from a network one.

This matters more than it looks. A mapped drive that points at a file
server is not a hard disk with a different letter:

  * SQLite's own documentation says its locking cannot be relied on over a
    network filesystem, and that write-ahead logging — which this app uses
    — does not work over one at all, because it needs shared memory the
    share cannot provide.
  * Git cannot always do the atomic renames it depends on, which is why a
    clone onto one fails partway with a rename error on .git/config.lock.

So the right answer for a network drive is to keep the live order book on a
local disk and send backups to the share, rather than running on it. This
module exists so the app can spot the situation and say so, instead of
letting someone find out the hard way.

Everything here is defensive: any surprise means "assume local", because a
wrong warning is worse than none.
"""

import re
import sys
from pathlib import Path

# "G:" at the start of a path. Read from the text rather than from
# Path.drive, which only understands drive letters when the code happens to
# be running on Windows — this way the logic behaves the same everywhere
# and can be tested anywhere.
_DRIVE_LETTER = re.compile(r"^([A-Za-z]:)")

DRIVE_REMOTE = 4          # from GetDriveTypeW
_NO_ERROR = 0


def _drive_type(root: str) -> int:
    """Windows' idea of what kind of drive this is. 0 when it cannot say."""
    if sys.platform != "win32":
        return 0
    try:
        import ctypes

        return int(ctypes.windll.kernel32.GetDriveTypeW(root))
    except Exception:
        return 0


def _unc_for(letter: str) -> str:
    """What a mapped drive letter actually points at, if anything."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        buffer = ctypes.create_unicode_buffer(2048)
        length = wintypes.DWORD(len(buffer))
        result = ctypes.windll.mpr.WNetGetConnectionW(
            letter, buffer, ctypes.byref(length))
        return buffer.value if result == _NO_ERROR else ""
    except Exception:
        return ""


def describe(path) -> dict:
    """Is this path on a network location, and what is it called?

    Returns {"network": bool, "where": str}. "where" is the server and
    share when we can name them, so a warning can be specific.
    """
    answer = {"network": False, "where": ""}
    try:
        text = str(Path(path))
    except Exception:
        return answer

    # A UNC path says so itself, on any platform.
    if text.startswith("\\\\") or text.startswith("//"):
        parts = text.replace("/", "\\").lstrip("\\").split("\\")
        answer["network"] = True
        answer["where"] = "\\\\" + "\\".join(parts[:2]) if len(parts) >= 2 else text
        return answer

    match = _DRIVE_LETTER.match(text)
    if not match:
        return answer
    drive = match.group(1).upper()    # "G:" for G:\folder

    # Defensive to the last: the guarantee is that a surprise here means
    # "assume local", because a wrong warning is worse than none.
    try:
        if _drive_type(drive + "\\") != DRIVE_REMOTE:
            return answer
    except Exception:
        return answer

    answer["network"] = True
    try:
        named = _unc_for(drive)
    except Exception:
        named = ""
    answer["where"] = named or f"{drive} (a network drive)"
    return answer


WARNING = (
    "{where} is a network drive, not a disk in this machine.\n"
    "\n"
    "Order Tracker should not keep its live order book on one. SQLite — the\n"
    "database underneath it — says its file locking cannot be relied on over\n"
    "a network share, and the write-ahead log it uses does not work over one\n"
    "at all. Git cannot reliably clone onto one either, which is the rename\n"
    "error you get partway through.\n"
    "\n"
    "Keep the app and its data on this machine, and set the backup folder to\n"
    "the network drive instead. You then get a complete copy on the share\n"
    "every time the app starts, without running on it."
)


def warning_for(path) -> str:
    """The warning to show for this path, or an empty string when local."""
    found = describe(path)
    if not found["network"]:
        return ""
    return WARNING.format(where=found["where"] or str(path))
