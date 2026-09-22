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


CFA_KEYS = [
    (r"SOFTWARE\Microsoft\Windows Defender\Windows Defender Exploit Guard"
     r"\Controlled Folder Access"),
    (r"SOFTWARE\Policies\Microsoft\Windows Defender"
     r"\Windows Defender Exploit Guard\Controlled Folder Access"),
]


def controlled_folder_access() -> str:
    """Whether Windows' ransomware protection is on, if we can find out.

    It blocks writes per application, which is why git can fill a folder
    that python.exe is then refused a single file in.
    """
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""

    for path in CFA_KEYS:
        for view in (winreg.KEY_WOW64_64KEY, 0):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                                    winreg.KEY_READ | view) as key:
                    value, _ = winreg.QueryValueEx(
                        key, "EnableControlledFolderAccess")
            except OSError:
                continue
            return {0: "off", 1: "ON", 2: "audit only"}.get(
                int(value), f"set to {value}")
    return "could not be read"


def candidate_folders():
    """Places to keep the data, best first, for when the app folder is out."""
    from ordertracker import config

    places = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        places.append(Path(local) / "OrderTracker")
    places.append(Path.home() / "OrderTracker")
    places.append(Path(tempfile.gettempdir()) / "order-tracker-data")
    seen, out = set(), []
    for place in places:
        if place not in seen and place != config.DATA_DIR:
            seen.add(place)
            out.append(place)
    return out


def folder_works(folder: Path) -> str:
    """Empty when the folder can hold the order book, else why not."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        db_probe = folder / ".db-probe"
        conn = sqlite3.connect(db_probe, timeout=10)
        conn.execute("CREATE TABLE IF NOT EXISTS probe (x INTEGER)")
        conn.close()
        db_probe.unlink(missing_ok=True)
    except (OSError, sqlite3.Error) as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


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

        # Whether the folder is new matters: one left behind by an earlier
        # run — or made while elevated — can carry permissions that deny
        # writes, and deleting it is then the whole fix.
        was_there = data_dir.exists()

        def make_folder():
            docs_dir.mkdir(parents=True, exist_ok=True)
            return ("it was already there" if was_there
                    else "created it just now")

        ok = check("create the folder", make_folder)
        if ok:
            probe = data_dir / ".write-probe"

            def write_probe():
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
                return "folder is writable"

            ok = check("write a file there", write_probe)
            if not ok and was_there:
                print()
                print("         That folder already existed. One left over from")
                print("         an earlier attempt can carry permissions that")
                print("         deny writes. Deleting it is worth trying:")
                print(f"             rmdir /s /q \"{data_dir}\"")

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

    guard = controlled_folder_access()
    if guard:
        print("\nWindows ransomware protection")
        line("controlled folder access", guard)
        if guard == "ON":
            print("\n  That is almost certainly what is refusing the writes. It")
            print("  blocks per application, which is why git can fill a folder")
            print("  that python.exe is then denied a single file in.\n")
            print("  To allow it: Windows Security > Virus & threat protection")
            print("  > Ransomware protection > Manage ransomware protection")
            print("  > Allow an app through Controlled folder access")
            print(f"  > Add an allowed app, and pick:\n")
            print(f"      {sys.executable}")
            print("\n  Or just keep the data somewhere it does not watch, below.")

    print("\nSomewhere else to keep the data")
    working = []
    for folder in candidate_folders():
        problem = folder_works(folder)
        if problem:
            print(f"  [FAIL] {folder}")
            print(f"         {problem}")
        else:
            print(f"  [ ok ] {folder}")
            working.append(folder)

    if working:
        print("\n  Any of those will hold your orders. This remembers the")
        print("  choice, so you only do it once:\n")
        print(f'      py setup.py --folder "{working[0]}"\n')
        print("  The app itself can stay where it is.")
    else:
        print("\n  None of those worked either, which points at something")
        print("  blocking python.exe generally rather than one folder.")
        print("  The allowed-app step above is then the way through.")

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
