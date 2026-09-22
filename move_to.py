#!/usr/bin/env python3
"""Copy Order Tracker to another drive and run it from there from now on.

    py move_to.py "G:\\my folder\\Order Tracker"

Copies the whole app plus whatever you have already stored, switches the
copy to portable mode so it keeps its data in its own folder, and repoints
the desktop shortcut at the new location.

Nothing is deleted. The original folder is left exactly as it is until you
have checked the copy works and remove it yourself.
"""

import argparse
import os
import shutil
import sqlite3
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ordertracker import config, settings  # noqa: E402

# Nothing here is worth copying. The data folders are excluded too: a live
# SQLite database must be copied through its own backup call rather than as
# loose files, or commits still sitting in the write-ahead log are lost.
JUNK = ("__pycache__", "*.pyc", "*.pyo", ".DS_Store")
SKIP = shutil.ignore_patterns(*JUNK, "data", "demo-data")
SKIP_NO_GIT = shutil.ignore_patterns(*JUNK, "data", "demo-data", ".git")
SKIP_JUNK_ONLY = shutil.ignore_patterns(*JUNK)


def running_copy() -> str | None:
    """The data folder of an Order Tracker that is running, if one is.

    Copying over the top of a live database is the one way this can leave
    you worse off than you started, so it is worth a moment to check.
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
                lines.append(f"    {source}\n        {why}")
            else:
                lines.append(f"    {failure}")
        if len(failures) > 8:
            lines.append(f"    … and {len(failures) - 8} more")
    else:
        lines.append(f"    {exc}")
    return lines


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


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Copy Order Tracker to another drive and run it from there.")
    parser.add_argument("destination", help=r'the new folder, e.g. "G:\\Order Tracker"')
    parser.add_argument("--no-git", action="store_true",
                        help="skip the .git folder (you then cannot `git pull` there)")
    parser.add_argument("--no-shortcut", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="test the destination and report, without copying")
    parser.add_argument("--force", action="store_true",
                        help="copy even though Order Tracker is still running")
    args = parser.parse_args(argv)

    source = config.BASE_DIR.resolve()
    destination = settings.expand(args.destination).resolve()

    print("\nORDER TRACKER — move to another drive\n")
    print(f"  from  {source}")
    print(f"  to    {destination}\n")

    if destination == source:
        print("  That is where it already is. Nothing to do.\n")
        return 1
    if is_inside(destination, source):
        print("  The new folder is inside the current one, which would copy the")
        print("  app into itself. Pick a folder somewhere else.\n")
        return 1

    live = running_copy()
    if live and not args.check and not args.force:
        print("  Order Tracker is still running, and its orders are open.")
        print(f"  It is using {live}")
        print()
        print("  Close it first, or the copy can end up with a half-written")
        print("  database: click QUIT in the app, then run this again.")
        print()
        print("  (If you are sure it is safe, add --force.)\n")
        return 1

    ok, reason = usable(destination)
    if not ok:
        print(f"  That folder will not work: {reason}")
        print("  Nothing has been copied.\n")
        return 1

    if args.check:
        print(f"  [ ok ] {destination} can be written to")
        print(f"  [ ok ] a database can be created there")
        source_files = sum(1 for _ in source.rglob("*") if _.is_file())
        print(f"  [ ok ] {source_files} file(s) would be copied from {source}")
        print(f"  [ ok ] your orders would come from {config.DB_PATH}")
        print("\n  Nothing was copied. Run the same command without --check "
              "to do it.\n")
        return 0

    if any(destination.iterdir()):
        print("  Note: that folder is not empty. Files with the same names will")
        print("  be overwritten; anything else there is left alone.\n")

    # --- copy the app ----------------------------------------------------
    try:
        shutil.copytree(source, destination,
                        ignore=SKIP_NO_GIT if args.no_git else SKIP,
                        copy_function=force_copy, dirs_exist_ok=True)
    except (shutil.Error, OSError) as exc:
        print("  The copy did not finish. These files could not be written:\n")
        for line in describe_copy_failure(exc):
            print(line)
        print("\n  On Windows that is nearly always one of three things:")
        print("    · Order Tracker is still running — click QUIT, then try again")
        print("    · you do not have permission to write to that drive")
        print("      (common on a company or network drive)")
        print("    · antivirus or Controlled folder access is guarding it")
        print("\n  You can also skip the git history, which is what most of")
        print("  these files are, and does not affect the app:\n")
        print(f'      py move_to.py "{args.destination}" --no-git\n')
        print("  Nothing has been changed in the original folder.\n")
        return 1
    print(f"  [ ok ] copied the app to {destination}")

    # --- bring the data, wherever it currently lives ---------------------
    data_source = config.DATA_DIR.resolve()
    data_target = destination / "data"
    db_source = config.DB_PATH.resolve()

    if db_source.exists():
        try:
            copy_database(db_source, data_target / db_source.name)
        except (sqlite3.Error, OSError) as exc:
            print(f"\n  The app was copied, but your orders were not: {exc}")
            print("  Close Order Tracker if it is running, then try again.\n")
            return 1
        print(f"  [ ok ] copied your orders from {db_source}")

        documents_source = config.DOCS_DIR.resolve()
        if documents_source.exists():
            try:
                shutil.copytree(documents_source, data_target / "documents",
                                ignore=SKIP_JUNK_ONLY, dirs_exist_ok=True)
            except OSError as exc:
                print(f"\n  Your orders came across but the documents did not: {exc}")
                print(f"  Copy {documents_source} to {data_target / 'documents'} "
                      "by hand.\n")
                return 1
            how_many = sum(1 for _ in (data_target / "documents").iterdir())
            print(f"  [ ok ] copied {how_many} document(s)")
    else:
        print("  [ -- ] nothing stored yet, so the copy starts empty")

    # --- make the copy portable ------------------------------------------
    (destination / "portable.txt").write_text(
        "This file makes Order Tracker portable.\n\n"
        "While it is here, orders and documents are kept in this folder\n"
        "rather than wherever setup.py was pointed, and the app works\n"
        "whatever drive letter this folder ends up with.\n\n"
        "Delete it to go back to a chosen folder.\n",
        encoding="utf-8")
    print("  [ ok ] set the copy to portable — it keeps its data in its own folder")

    # A portable folder reads its settings from beside run.py, so the welcome
    # name and the rest have to travel with it. Everything else you can
    # change on the SETUP page already lives in the database, which has just
    # been copied across.
    carried = dict(settings.load())
    carried["workspace"] = ""          # portable ignores it; leave it clear
    try:
        settings.dump(destination / "settings.json", carried)
        print("  [ ok ] carried your settings over "
              f"(welcome name: {carried.get('welcome_name') or 'not set'})")
    except OSError as exc:
        print(f"  [ -- ] the settings could not be carried over: {exc}")

    # --- repoint the desktop shortcut ------------------------------------
    shortcut_path = None
    if not args.no_shortcut:
        from ordertracker import shortcut as shortcut_module

        # The shortcut must point at the copy, not at where we are running from.
        real_base, real_assets = config.BASE_DIR, config.ASSETS_DIR
        config.BASE_DIR = destination
        config.ASSETS_DIR = destination / "assets"
        try:
            shortcut_path = shortcut_module.create()
            print(f"  [ ok ] desktop shortcut now opens the copy")
        except Exception as exc:
            print(f"  [ -- ] the desktop shortcut could not be updated: {exc}")
        finally:
            config.BASE_DIR, config.ASSETS_DIR = real_base, real_assets

    # --- what to do next --------------------------------------------------
    print("\n  Done.\n")
    print(f"    the app now lives in   {destination}")
    print(f"    its data is in         {data_target}")
    if shortcut_path:
        print(f"    desktop shortcut       {shortcut_path.name}")
    print()
    print("  Check it works:\n")
    print(f'      cd /d "{destination}"')
    print("      py run.py\n")
    print("  Once you are happy, delete the old folder:")
    print(f"      {source}\n")
    print("  Nothing has been removed for you.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
