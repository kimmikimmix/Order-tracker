"""Copying the whole app, with its data, to another drive.

The logic lives here rather than in move_to.py so that the same steps can be
driven from the command line or from the SETUP page in the browser. Someone
who cannot reliably get a command prompt into the right folder can do the
whole thing with a button instead.

Two rules throughout: the folder being copied from is never modified, and
the database is copied through SQLite's own backup call rather than as a
file, because in WAL mode the newest changes live in a side file and a plain
copy arrives without them.
"""

import os
import shutil
import sqlite3
import stat
from pathlib import Path

from . import config, drives, settings

# Nothing here is worth copying. The data folders are excluded from the file
# copy because the database needs the backup call, and the documents are
# fetched separately from wherever they actually live.
JUNK = ("__pycache__", "*.pyc", "*.pyo", ".DS_Store")
SKIP = shutil.ignore_patterns(*JUNK, "data", "demo-data")
SKIP_NO_GIT = shutil.ignore_patterns(*JUNK, "data", "demo-data", ".git")
SKIP_JUNK_ONLY = shutil.ignore_patterns(*JUNK)

PORTABLE_NOTE = (
    "This file makes Order Tracker portable.\n\n"
    "While it is here, orders and documents are kept in this folder\n"
    "rather than wherever setup.py was pointed, and the app works\n"
    "whatever drive letter this folder ends up with.\n\n"
    "Delete it to go back to a chosen folder.\n"
)


class MoveError(Exception):
    """Something stopped the copy, with an explanation worth showing."""


# --- small helpers ---------------------------------------------------------

def force_copy(source, target, follow_symlinks=True):
    """Copy one file, over the top of a read-only one if need be.

    Git keeps everything under .git/objects read-only. Copying onto a folder
    that already holds them — running this a second time, or copying into a
    folder that once held a copy — is refused by Windows with "access is
    denied" unless the read-only flag is cleared first.
    """
    if os.path.exists(target):
        try:
            os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass  # if it still cannot be written, the copy below will say so
    return shutil.copy2(source, target, follow_symlinks=follow_symlinks)


def describe_copy_failure(exc) -> list[str]:
    """Turn whatever copytree threw into lines a person can act on."""
    lines = []
    failures = exc.args[0] if isinstance(exc, shutil.Error) and exc.args else None
    if isinstance(failures, list):
        for failure in failures[:8]:
            if isinstance(failure, tuple) and len(failure) == 3:
                source, _, why = failure
                lines.append(f"{source}\n    {why}")
            else:
                lines.append(str(failure))
        if len(failures) > 8:
            lines.append(f"… and {len(failures) - 8} more")
    else:
        lines.append(str(exc))
    return lines


WINDOWS_ADVICE = (
    "On Windows that is nearly always one of three things: Order Tracker is "
    "still running, you do not have permission to write to that drive (common "
    "on a company or network drive), or antivirus — or Controlled folder "
    "access — is guarding it."
)


def copy_database(source_db: Path, target_db: Path) -> None:
    """Copy a SQLite database safely, even while the app is running.

    SQLite's own backup call reads a consistent snapshot including anything
    still in the write-ahead log, which copying the .db file on its own
    would leave behind.
    """
    target_db.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True, timeout=30)
    try:
        target_conn = sqlite3.connect(target_db, timeout=30)
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
    finally:
        source_conn.close()


def set_journal_mode(db_path: Path, network: bool) -> str:
    """Put a freshly copied database into the right journal mode.

    Done here because this file is brand new and nothing else has it open,
    which is the one moment the change is certain to take. A database that
    arrives on a share still in write-ahead mode would otherwise have to be
    converted on first use, when it may well be refused.
    """
    wanted = "DELETE" if network else "WAL"
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            got = conn.execute(f"PRAGMA journal_mode={wanted}").fetchone()[0]
        finally:
            conn.close()
        return str(got)
    except sqlite3.Error:
        return ""


def usable(folder: Path) -> tuple[bool, str]:
    """Can we create files and a database in here?"""
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"the folder could not be created ({exc.strerror or exc})"

    probe = folder / ".write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return False, f"files cannot be written there ({exc.strerror or exc})"

    db_probe = folder / ".db-probe"
    try:
        sqlite3.connect(db_probe, timeout=10).close()
        db_probe.unlink(missing_ok=True)
    except sqlite3.Error as exc:
        return False, f"a database cannot be opened there ({exc})"
    except OSError:
        pass
    return True, "ready"


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def count_stored(db_path: Path) -> str:
    """What is in a database, in words, so a copy can be checked by eye."""
    if not Path(db_path).exists():
        return ""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return "a database that could not be read"
    return f"{orders} orders and {docs} documents"


def running_copy() -> str | None:
    """The data folder of an Order Tracker that is running, if one is.

    Copying over the top of a live database is the one way this can leave
    you worse off than you started, so it is worth a moment to check. The
    app moving itself does not need this: reading its own database through
    the backup call is safe, and it is writing somewhere else entirely.
    """
    import json
    import urllib.error
    import urllib.request

    try:
        url = f"http://{config.HOST}:{config.PORT}/api/ping"
        with urllib.request.urlopen(url, timeout=2) as response:
            answer = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if answer.get("app") != "order-tracker":
        return None
    return answer.get("data") or "(unknown)"


# --- what a move would involve --------------------------------------------

def plan(destination, probe: bool = True) -> dict:
    """Everything worth knowing before committing to a copy.

    With probe off nothing at all is written — not even the empty folder
    that testing for writability would otherwise create. That matters for
    the printed plan, which promises to touch nothing.
    """
    source = config.BASE_DIR.resolve()
    target = settings.expand(destination).resolve()
    data_dir = config.DATA_DIR.resolve()

    report = {
        "source": str(source),
        "destination": str(target),
        "data_source": str(data_dir),
        "data_destination": str(target / "data"),
        "data_inside_app": is_inside(data_dir, source),
        "stored": count_stored(config.DB_PATH.resolve()),
        "exists": target.exists(),
        "not_empty": target.exists() and any(target.iterdir()),
        # What is already in the destination. Copying over a folder that
        # holds more than the source does is how someone updating the app
        # would wipe the orders they were trying to keep.
        "destination_stored": count_stored(target / "data" / "orders.db"),
        "problem": "",
        "writable": False,
        "reason": "",
        # A network drive can usually be written to perfectly well, so this
        # is a warning rather than a refusal — but it is the wrong home for
        # a live database, and worth saying loudly.
        "warning": drives.warning_for(target),
        "network": drives.describe(target)["network"],
    }

    if target == source:
        report["problem"] = "That is the folder it is already in."
        return report
    if is_inside(target, source):
        report["problem"] = ("That folder is inside the current one, which "
                             "would copy the app into itself. Pick a folder "
                             "somewhere else.")
        return report

    if not probe:
        report["reason"] = "not checked"
        return report

    ok, reason = usable(target)
    report["writable"] = ok
    report["reason"] = reason
    if not ok:
        report["problem"] = f"That folder will not work: {reason}"
    return report


# --- doing it --------------------------------------------------------------

def copy_app(source: Path, destination: Path, keep_git: bool = True) -> None:
    """Copy the program files, leaving the data folders out."""
    try:
        shutil.copytree(source, destination,
                        ignore=SKIP if keep_git else SKIP_NO_GIT,
                        copy_function=force_copy, dirs_exist_ok=True)
    except (shutil.Error, OSError) as exc:
        raise MoveError("These files could not be written:\n  "
                        + "\n  ".join(describe_copy_failure(exc))
                        + "\n\n" + WINDOWS_ADVICE) from exc


def copy_data(destination: Path, replace: bool = False) -> dict:
    """Bring the orders and the documents across, wherever they live now.

    Refuses to write over a destination that already holds orders unless
    told to: that folder may be the one with the real order book in it.
    """
    result = {"orders": "", "documents": 0, "replaced": "", "journal": ""}
    already = count_stored(destination / "data" / "orders.db")
    if already and not replace:
        raise MoveError(
            f"{destination / 'data'} already holds {already}.\n\n"
            f"This copy would replace them with {count_stored(config.DB_PATH)} "
            "from\n"
            f"{config.DATA_DIR}.\n\n"
            "If that is what you want, say so explicitly — tick the box on the "
            "page,\nor pass --replace-data on the command line. Nothing has "
            "been changed."
        )
    result["replaced"] = already
    db_source = config.DB_PATH.resolve()
    data_target = destination / "data"

    if not db_source.exists():
        return result

    # Always lands as orders.db: the copy is a fresh portable install, and
    # that is the name it will look for in its own data folder.
    try:
        copy_database(db_source, data_target / "orders.db")
    except (sqlite3.Error, OSError) as exc:
        raise MoveError(
            f"The app was copied, but your orders were not: {exc}\n\n"
            "Close Order Tracker if it is running, then try again."
        ) from exc
    result["orders"] = count_stored(data_target / "orders.db")
    result["journal"] = set_journal_mode(
        data_target / "orders.db", drives.describe(destination)["network"])

    documents_source = config.DOCS_DIR.resolve()
    if documents_source.exists():
        try:
            shutil.copytree(documents_source, data_target / "documents",
                            ignore=SKIP_JUNK_ONLY, copy_function=force_copy,
                            dirs_exist_ok=True)
        except (shutil.Error, OSError) as exc:
            raise MoveError(
                "Your orders came across but the documents did not:\n  "
                + "\n  ".join(describe_copy_failure(exc))
                + f"\n\nCopy {documents_source} to {data_target / 'documents'} "
                "by hand."
            ) from exc
        result["documents"] = sum(1 for _ in (data_target / "documents").iterdir())
    return result


def make_portable(folder: Path, carried: dict | None = None) -> str:
    """Mark a folder portable and give it the settings to stand alone."""
    (folder / "portable.txt").write_text(PORTABLE_NOTE, encoding="utf-8")
    values = dict(carried if carried is not None else settings.load())
    values["workspace"] = ""      # portable ignores it; leave it clear
    settings.dump(folder / "settings.json", values)
    return values.get("welcome_name") or ""


def repoint_shortcut(destination: Path):
    """Point the desktop icon at the copy rather than at where we are."""
    from . import shortcut as shortcut_module

    real_base, real_assets = config.BASE_DIR, config.ASSETS_DIR
    config.BASE_DIR = destination
    config.ASSETS_DIR = destination / "assets"
    try:
        return shortcut_module.create()
    finally:
        config.BASE_DIR, config.ASSETS_DIR = real_base, real_assets


def run(destination, keep_git: bool = True, shortcut: bool = True,
        replace_data: bool = False) -> dict:
    """Copy the app and its data, and leave the copy ready to run.

    Raises MoveError with something worth reading when a step fails. The
    folder being copied from is never modified.
    """
    source = config.BASE_DIR.resolve()
    target = settings.expand(destination).resolve()

    report = plan(target)
    if report["problem"]:
        raise MoveError(report["problem"])

    # Read the settings before anything is written, so the welcome name is
    # taken from wherever it lives right now.
    carried = dict(settings.load())

    # Check the data question before anything is written, so a refusal
    # leaves the destination exactly as it was.
    already = count_stored(target / "data" / "orders.db")
    if already and not replace_data:
        raise MoveError(
            f"{target / 'data'} already holds {already}.\n\n"
            f"This copy would replace them with "
            f"{count_stored(config.DB_PATH) or 'an empty order book'} from\n"
            f"{config.DATA_DIR}.\n\n"
            "If that is what you want, say so explicitly — tick the box on "
            "the page,\nor pass --replace-data on the command line. Nothing "
            "has been changed."
        )

    copy_app(source, target, keep_git=keep_git)
    steps = [f"copied the app to {target}"]

    data = copy_data(target, replace=True)
    if data["journal"] == "delete":
        steps.append("set the database to the journal mode a network share "
                     "can handle")
    if data["replaced"]:
        steps.insert(0, f"replaced the {data['replaced']} that were there")
    if data["orders"]:
        steps.append(f"copied your orders — {data['orders']}")
        if data["documents"]:
            steps.append(f"copied {data['documents']} document file(s)")
    else:
        steps.append("nothing stored yet, so the copy starts empty")

    name = make_portable(target, carried)
    steps.append("set the copy to portable — it keeps its data in its own folder")
    steps.append(f"carried your settings over (welcome name: {name or 'not set'})")

    shortcut_path = None
    if shortcut:
        try:
            shortcut_path = repoint_shortcut(target)
            steps.append(f"desktop shortcut now opens {target}")
        except Exception as exc:
            steps.append(f"the desktop shortcut could not be updated: {exc}")

    return {
        "ok": True,
        "source": str(source),
        "destination": str(target),
        "data": str(target / "data"),
        "orders": data["orders"],
        "documents": data["documents"],
        "welcome_name": name,
        "shortcut": str(shortcut_path) if shortcut_path else "",
        "steps": steps,
    }


def finish_here(shortcut: bool = True) -> dict:
    """Complete a copy that was made by hand. Run inside the new folder.

    Deliberately never touches the folder it was copied from: if anything
    here is wrong, the original is still sitting there untouched.
    """
    base = config.BASE_DIR.resolve()

    for needed in ("run.py", "ordertracker", "web"):
        if not (base / needed).exists():
            raise MoveError(
                f"This does not look like an Order Tracker folder — {needed} "
                "is missing.\nRun this inside the copy you just made."
            )

    ok, reason = usable(base)
    if not ok:
        raise MoveError(f"This folder cannot be written to: {reason}\n\n"
                        "The copy will not be able to save anything here.")

    carried = dict(settings.load())

    steps = []
    stored = count_stored(base / "data" / "orders.db")
    if stored:
        steps.append(f"found your orders here — {stored}")
    elif (base / "data").exists():
        steps.append("there is a data folder here but no orders.db in it")
    else:
        steps.append("no data folder here yet, so this copy starts empty — "
                     f"your orders are currently in {config.DATA_DIR}")

    here = base / "data" / "orders.db"
    if stored and set_journal_mode(here, drives.describe(base)["network"]) == "delete":
        steps.append("set the database to the journal mode a network share "
                     "can handle")

    name = make_portable(base, carried)
    steps.append("set to portable — it keeps its data in its own folder")
    steps.append(f"settings carried over (welcome name: {name or 'not set'})")

    shortcut_path = None
    if shortcut:
        try:
            shortcut_path = repoint_shortcut(base)
            steps.append(f"desktop shortcut now opens {base}")
        except Exception as exc:
            steps.append(f"the desktop shortcut could not be updated: {exc}")

    return {"ok": True, "destination": str(base), "orders": stored,
            "welcome_name": name,
            "shortcut": str(shortcut_path) if shortcut_path else "",
            "steps": steps}
