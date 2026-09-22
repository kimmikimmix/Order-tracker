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
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ordertracker import config, settings  # noqa: E402

# Nothing here is worth copying.
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store",
                              "*.db-wal", "*.db-shm")


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

    ok, reason = usable(destination)
    if not ok:
        print(f"  That folder will not work: {reason}")
        print("  Nothing has been copied.\n")
        return 1

    if any(destination.iterdir()):
        print("  Note: that folder is not empty. Files with the same names will")
        print("  be overwritten; anything else there is left alone.\n")

    # --- copy the app ----------------------------------------------------
    ignore = SKIP
    if args.no_git:
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo",
                                        ".DS_Store", "*.db-wal", "*.db-shm",
                                        ".git")
    try:
        shutil.copytree(source, destination, ignore=ignore, dirs_exist_ok=True)
    except OSError as exc:
        print(f"  The copy failed: {exc}")
        print("  Nothing has been changed in the original folder.\n")
        return 1
    print(f"  [ ok ] copied the app to {destination}")

    # --- bring the data, wherever it currently lives ---------------------
    data_source = config.DATA_DIR.resolve()
    data_target = destination / "data"
    if data_source.exists() and not is_inside(data_source, source):
        try:
            shutil.copytree(data_source, data_target, ignore=SKIP, dirs_exist_ok=True)
            print(f"  [ ok ] copied your orders from {data_source}")
        except OSError as exc:
            print(f"\n  The app was copied, but your data was not: {exc}")
            print(f"  Copy {data_source} to {data_target} by hand, then carry on.\n")
            return 1
    elif data_source.exists():
        print("  [ ok ] your orders came across with the app")
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
