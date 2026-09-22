#!/usr/bin/env python3
"""Set Order Tracker up on this machine.

    python3 setup.py           (Windows: py setup.py)

Asks where to keep your orders and documents, offers to move anything
already stored, sets the name on the welcome screen, and puts a shortcut on
the desktop. Safe to run again whenever you want to change any of it.
"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ordertracker import config, settings  # noqa: E402


def ask(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix}\n> ").strip()
    except EOFError:
        return default
    return answer or default


def ask_yes(question: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        answer = input(f"{question} [{hint}] ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer.startswith("y")


def folder_is_usable(folder: Path) -> tuple[bool, str]:
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
        conn = sqlite3.connect(db_probe, timeout=10)
        conn.execute("CREATE TABLE IF NOT EXISTS probe (x INTEGER)")
        conn.close()
        db_probe.unlink(missing_ok=True)
    except sqlite3.Error as exc:
        return False, f"a database cannot be opened there ({exc})"
    except OSError:
        pass  # the probe file lingering is harmless

    return True, "ready"


def describe(data_dir: Path) -> str:
    """A short summary of what is already stored in a data folder."""
    db_path = data_dir / "orders.db"
    if not db_path.exists():
        return ""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        conn.close()
    except sqlite3.Error:
        return "an existing database"
    return f"{orders} orders and {docs} documents"


def move_folder(source: Path, target: Path) -> None:
    """Move one data folder, merging into whatever is already there."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.move(str(source), str(target))
        return
    for item in source.iterdir():
        destination = target / item.name
        if destination.exists():
            continue
        shutil.move(str(item), str(destination))
    try:
        source.rmdir()
    except OSError:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Set up Order Tracker.")
    parser.add_argument("--folder", help="where to keep orders and documents")
    parser.add_argument("--name", help="name shown on the welcome screen")
    parser.add_argument("--shortcut", dest="shortcut", action="store_true")
    parser.add_argument("--no-shortcut", dest="shortcut", action="store_false")
    parser.add_argument("--no-move", dest="move", action="store_false",
                        help="leave existing data where it is")
    parser.add_argument("--portable", dest="portable", action="store_true",
                        help="keep everything in the app folder, so the whole "
                             "app can live on a personal or removable drive")
    parser.add_argument("--not-portable", dest="portable", action="store_false")
    parser.set_defaults(shortcut=None, move=True, portable=None)
    args = parser.parse_args(argv)

    interactive = (args.folder is None and args.name is None
                   and args.shortcut is None and args.portable is None)

    print("\nORDER TRACKER — setup\n")

    saved = settings.load()
    current = saved.get("workspace") or ""
    old_data_dir = config.DATA_DIR
    old_demo_dir = config.DEMO_DIR

    print(f"  Orders are currently kept in:\n    {old_data_dir}")
    if not current:
        print("    (inside the app folder — fine, but it moves if you re-download)")
    print()

    # --- portable, or a folder of your choosing --------------------------
    if args.portable is not None:
        portable = args.portable
    elif interactive:
        print("  Two ways to store things:\n")
        print("    1. A folder you pick — your data lives there, the app stays"
              " where it is.")
        print("    2. Portable — the whole app and its data sit together in "
              "this folder,\n       so it runs from a personal or USB drive on"
              " any machine.\n")
        portable = ask_yes("  Set it up as portable?", default=False)
    else:
        portable = config.PORTABLE

    if portable:
        chosen = ""
        print(f"\n  Portable: everything stays in {config.BASE_DIR}")
    elif args.folder is not None:
        chosen = args.folder
    elif interactive:
        print("\n  Pick a folder on any drive — an external or network drive "
              "is fine.")
        print(r'  For example:  D:\OrderTracker')
        chosen = ask("\n  Where should Order Tracker keep your data? "
                     "(Enter to leave it as it is)", current)
    else:
        chosen = current

    workspace = (config.BASE_DIR if portable
                 else (settings.expand(chosen).resolve() if chosen.strip()
                       else config.BASE_DIR))
    usable, reason = folder_is_usable(workspace)
    if not usable:
        print(f"\n  That folder will not work: {reason}")
        print("  Nothing has been changed. Try another folder.\n")
        return 1
    print(f"\n  [ ok ] {workspace} — {reason}")

    new_data_dir = workspace / "data"
    new_demo_dir = workspace / "demo-data"

    # --- move anything already stored ------------------------------------
    if new_data_dir.resolve() != old_data_dir.resolve():
        existing = describe(old_data_dir)
        if existing:
            move = args.move and (
                not interactive
                or ask_yes(f"\n  Found {existing} in the old location. Move them across?")
            )
            if move:
                try:
                    move_folder(old_data_dir, new_data_dir)
                    if old_demo_dir.exists():
                        move_folder(old_demo_dir, new_demo_dir)
                    print(f"  [ ok ] moved your data to {new_data_dir}")
                except OSError as exc:
                    print(f"\n  Could not move the data: {exc}")
                    print("  Nothing has been changed. Close anything using the "
                          "app and try again.\n")
                    return 1
            else:
                print("  [ -- ] left the old data where it is; starting empty here")

    # --- the welcome screen ----------------------------------------------
    if args.name is not None:
        welcome_name = args.name
    elif interactive:
        welcome_name = ask("\n  Name to show on the welcome screen "
                           "(Enter to skip)", saved.get("welcome_name", ""))
    else:
        welcome_name = saved.get("welcome_name", "")

    # The marker file is what makes portable mode portable: it travels with
    # the folder, so the app does not depend on a setting saved on one machine.
    if portable:
        config.PORTABLE_MARKER.write_text(
            "This file makes Order Tracker portable.\n\n"
            "While it is here, orders and documents are kept in this folder\n"
            "rather than wherever setup.py was pointed, and the app works\n"
            "whatever drive letter this folder ends up with.\n\n"
            "Delete it to go back to a chosen folder.\n",
            encoding="utf-8")
    elif config.PORTABLE_MARKER.exists():
        config.PORTABLE_MARKER.unlink()

    settings_file = settings.save(
        workspace="" if (portable or workspace == config.BASE_DIR) else str(workspace),
        welcome_name=welcome_name,
        show_welcome=True,
    )

    # --- desktop shortcut -------------------------------------------------
    want_shortcut = args.shortcut
    if want_shortcut is None:
        want_shortcut = ask_yes("\n  Put a shortcut on the desktop?") if interactive else False

    shortcut_path = None
    if want_shortcut:
        from ordertracker import shortcut as shortcut_module
        try:
            shortcut_path = shortcut_module.create()
        except shortcut_module.ShortcutError as exc:
            print(f"\n  The desktop shortcut could not be created:\n    {exc}")
            print("\n  Everything else is set up — start it with:  py run.py")
        except Exception as exc:
            print(f"\n  The desktop shortcut could not be created: "
                  f"{type(exc).__name__}: {exc}")
            print("\n  Everything else is set up — start it with:  py run.py")
        else:
            if shortcut_path.suffix == ".bat":
                print("\n  PowerShell would not make a proper shortcut on this "
                      "machine,\n  so a batch launcher was written instead. It "
                      "works the same way.")

    # --- summary ----------------------------------------------------------
    print("\n  All set.\n")
    print(f"    data folder    {new_data_dir}")
    if portable:
        print("    mode           portable — move this whole folder anywhere")
    print(f"    settings       {settings_file}")
    if welcome_name:
        print(f"    welcome name   {welcome_name}")
    if shortcut_path:
        print(f"    shortcut       {shortcut_path}")
    print()
    if shortcut_path:
        print(f"  Double-click \"{shortcut_path.name}\" on your desktop to start.\n")
    else:
        print("  Start it with:  py run.py\n")
        print("  To try the desktop shortcut on its own:  py setup.py --shortcut\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
