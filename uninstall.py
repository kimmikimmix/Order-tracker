#!/usr/bin/env python3
"""Remove Order Tracker from this machine.

    py uninstall.py            list everything it would remove, remove nothing
    py uninstall.py --delete   remove it, after confirming

Finds the pieces wherever they actually are — the data folder is often not
inside the app folder, and the settings live outside it by design — and says
what each one holds before anything goes.

Your orders are the only thing here that cannot be downloaded again, so it
offers to save a copy first and never deletes a backup folder.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ordertracker import config, settings  # noqa: E402
from ordertracker.relocate import copy_database, count_stored  # noqa: E402


def folder_size(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def shortcut_paths() -> list[Path]:
    """Everywhere a desktop shortcut might have been written."""
    from ordertracker import shortcut as shortcut_module

    desktops = []
    if sys.platform == "win32":
        try:
            desktops.append(shortcut_module.windows_desktop())
        except Exception:
            pass
        desktops.append(Path.home() / "Desktop")
        desktops.append(Path.home() / "OneDrive" / "Desktop")
    elif sys.platform == "darwin":
        desktops.append(Path.home() / "Desktop")
    else:
        desktops.append(Path(os.environ.get("XDG_DESKTOP_DIR")
                             or (Path.home() / "Desktop")))

    found, seen = [], set()
    for desktop in desktops:
        for suffix in (".lnk", ".bat", ".command", ".desktop"):
            link = desktop / f"{shortcut_module.SHORTCUT_NAME}{suffix}"
            if link.exists() and link not in seen:
                seen.add(link)
                found.append(link)
    return found


def find_everything() -> dict:
    """Every piece of Order Tracker on this machine, and what it holds."""
    app = config.BASE_DIR.resolve()
    data = config.DATA_DIR.resolve()
    demo = config.DEMO_DIR.resolve()

    items = []

    stored = count_stored(config.DB_PATH.resolve())
    if data.exists():
        items.append({
            "kind": "data", "path": data,
            "note": stored or "no orders database in it",
            "size": folder_size(data), "precious": bool(stored),
        })
    if demo.exists() and demo != data:
        items.append({
            "kind": "demo", "path": demo, "note": "the sample order book",
            "size": folder_size(demo), "precious": False,
        })

    settings_file = settings.settings_path()
    if settings_file.exists():
        items.append({
            "kind": "settings", "path": settings_file,
            "note": "your chosen folder and welcome name",
            "size": settings_file.stat().st_size, "precious": False,
        })

    for link in shortcut_paths():
        items.append({
            "kind": "shortcut", "path": link, "note": "desktop shortcut",
            "size": 0, "precious": False,
        })

    # A backup folder is somewhere else on purpose. It is reported so you
    # know it is there, and never touched.
    backup_dir = ""
    try:
        from ordertracker import backup, db, prefs
        db.init_db()
        backup_dir = prefs.get("backup_dir") or ""
        if backup_dir:
            root = backup.destination()
            backup_dir = str(root) if root else ""
    except Exception:
        backup_dir = ""

    return {"app": app, "items": items, "backup_dir": backup_dir,
            "stored": stored}


def save_copy(where: str) -> Path:
    """Put the orders somewhere safe before they go."""
    target = settings.expand(where).resolve()
    target.mkdir(parents=True, exist_ok=True)
    copy_database(config.DB_PATH.resolve(), target / "orders.db")
    if config.DOCS_DIR.exists():
        shutil.copytree(config.DOCS_DIR, target / "documents", dirs_exist_ok=True)
    return target


def remove(item: dict) -> str:
    path = item["path"]
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        return f"could not remove {path}: {exc}"
    return ""


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Remove Order Tracker from this machine.")
    parser.add_argument("--delete", action="store_true",
                        help="actually remove things (otherwise it only lists)")
    parser.add_argument("--save-to", metavar="FOLDER",
                        help="copy your orders here before deleting")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")
    args = parser.parse_args(argv)

    found = find_everything()
    app = found["app"]
    items = found["items"]

    print("\nORDER TRACKER — remove it from this machine\n")

    if not items:
        print("  Nothing found apart from the app folder itself:\n")
        print(f"      {app}\n")
        print("  Delete that folder in File Explorer and it is gone.\n")
        return 0

    print("  Found:\n")
    for item in items:
        mark = " <-- your orders" if item["precious"] else ""
        size = f"  ({human(item['size'])})" if item["size"] else ""
        print(f"    {item['path']}{size}")
        print(f"        {item['note']}{mark}")
    print(f"\n    {app}")
    print("        the app itself — delete this in File Explorer afterwards")

    if found["backup_dir"]:
        print(f"\n  Not touched: your backup folder\n      {found['backup_dir']}")
        print("  Remove that yourself if you want it gone too.")

    if not args.delete:
        print("\n  Nothing has been removed. To go ahead:\n")
        print("      py uninstall.py --delete\n")
        if found["stored"]:
            print("  Your orders are in the folder marked above. To keep a copy:\n")
            print('      py uninstall.py --delete --save-to "D:\\Order Tracker copy"\n')
        return 0

    if found["stored"] and not args.save_to:
        print(f"\n  WARNING: this deletes {found['stored']}.")
        print("  There is no undo, and they are not in the Recycle Bin.")
        if not args.yes:
            print("  Stop now and use --save-to if you want to keep them.")

    if not args.yes:
        print()
        try:
            answer = input("  Type DELETE to remove everything listed above: ")
        except EOFError:
            answer = ""
        if answer.strip() != "DELETE":
            print("\n  Nothing has been removed.\n")
            return 1

    if args.save_to:
        if not config.DB_PATH.exists():
            print("\n  There is nothing stored to save a copy of.")
        else:
            try:
                saved = save_copy(args.save_to)
            except Exception as exc:
                print(f"\n  The copy could not be saved: {exc}")
                print("  Nothing has been removed.\n")
                return 1
            print(f"\n  [ ok ] saved a copy of your orders to {saved}")

    print()
    problems = []
    for item in items:
        problem = remove(item)
        if problem:
            problems.append(problem)
            print(f"  [ -- ] {problem}")
        else:
            print(f"  [ ok ] removed {item['path']}")

    # The folder this is running from cannot remove itself on Windows, and
    # nothing in it is worth a clever trick — it is a fresh download away.
    print("\n  One thing left, which has to be done in File Explorer because")
    print("  this script is running from inside it:\n")
    print(f"      {app}\n")
    print("  Right-click it and delete. Then Order Tracker is gone.\n")

    if problems:
        print("  Some things could not be removed — usually because Order")
        print("  Tracker is still running. Click QUIT, then run this again.\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
