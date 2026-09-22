#!/usr/bin/env python3
"""Work out why Order Tracker will not start on this machine.

    python3 doctor.py          (Windows: py doctor.py)

It walks the same steps the app takes at startup and reports exactly which
one fails and why, instead of ending in a bare traceback.
"""

import os
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def line(label, value):
    print(f"  {label:<22} {value}")


def check(label, fn):
    """Run one step, print OK or the real error, and return success."""
    try:
        detail = fn()
    except Exception as exc:
        print(f"  [FAIL] {label}")
        print(f"         {type(exc).__name__}: {exc}")
        return False
    print(f"  [ ok ] {label}" + (f" — {detail}" if detail else ""))
    return True


def main():
    print("\nORDER TRACKER — startup check\n")

    print("Environment")
    line("python", sys.version.split()[0])
    line("executable", sys.executable)
    line("platform", platform.platform())
    line("sqlite", sqlite3.sqlite_version)
    line("cwd", os.getcwd())

    try:
        from ordertracker import config
    except Exception as exc:
        print(f"\n  [FAIL] could not import the app: {type(exc).__name__}: {exc}")
        print("\n  Run this from inside the Order-tracker folder.\n")
        return 1

    for demo in (False, True):
        data_dir = (config.BASE_DIR / "demo-data") if demo else config.DATA_DIR
        db_path = data_dir / "orders.db"
        docs_dir = data_dir / "documents"

        print(f"\n{'Demo data' if demo else 'Real data'}  ({data_dir})")

        from ordertracker import drives
        network = drives.warning_for(data_dir)
        if network:
            print()
            for text in network.splitlines():
                print(f"  ! {text}" if text else "  !")
            print()

        ok = check("create the folder",
                   lambda: docs_dir.mkdir(parents=True, exist_ok=True))
        if ok:
            probe = data_dir / ".write-probe"

            def write_probe():
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
                return "folder is writable"

            ok = check("write a file there", write_probe)

        if ok:
            def open_database():
                conn = sqlite3.connect(db_path, timeout=10)
                conn.execute("CREATE TABLE IF NOT EXISTS probe (x INTEGER)")
                conn.execute("DROP TABLE probe")
                conn.close()
                return f"opened {db_path.name}"

            if not check("open the database", open_database):
                explain(data_dir)

    print("\nWhere the app itself is")
    from ordertracker import drives
    here = drives.describe(config.BASE_DIR)
    line("app folder", config.BASE_DIR)
    line("on a network drive", "YES — " + here["where"] if here["network"] else "no")
    if here["network"]:
        print("\n  Git cannot reliably clone or pull onto a network share: it")
        print("  needs atomic renames the share may refuse, which shows up as")
        print("  a rename error on .git/config.lock partway through a clone.")
        print("  Keep the app on this machine and back up to the share.")

    print("\nFallback location")
    fallback = Path(tempfile.gettempdir()) / "order-tracker-data"

    def fallback_db():
        fallback.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(fallback / "orders.db", timeout=10)
        conn.close()
        return str(fallback)

    if check("database in a temp folder", fallback_db):
        print(f"\n  If the checks above failed but this one passed, start the app\n"
              f"  with its data somewhere else:\n\n"
              f"      py run.py --demo --data \"{fallback}\"\n")

    print()
    return 0


def explain(data_dir):
    """Name the usual Windows causes for a folder that resists SQLite."""
    print()
    print("  The folder exists and takes ordinary files, but SQLite cannot")
    print("  create its database there. On Windows that is nearly always one of:")
    print()
    print("   * Controlled folder access (Windows Security > Virus & threat")
    print("     protection > Ransomware protection). Allow python.exe, or move")
    print("     the app out of Documents/Desktop.")
    print("   * OneDrive syncing the folder, with files set to 'online only'.")
    print("     Right-click the folder > Always keep on this device.")
    print("   * Antivirus blocking new database files in the user profile.")
    print()
    print("  The quickest way past all three is to keep the data elsewhere:")
    print(f'      py run.py --demo --data "%LOCALAPPDATA%\\OrderTracker"')
    print()


if __name__ == "__main__":
    raise SystemExit(main())
