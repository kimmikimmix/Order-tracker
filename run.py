#!/usr/bin/env python3
"""Order Tracker — start the local terminal.

    python3 run.py              start, and open the browser
    python3 run.py --demo       load sample data first, in its own database
    python3 run.py --port 9000  use a different port
    python3 run.py --reindex    re-read every stored document, then start
    python3 run.py --no-backup  start without taking the usual backup copy

Nothing here needs installing: it runs on a stock Python 3.10 or newer.
"""

import argparse
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ordertracker import config  # noqa: E402


def already_running(host: str, port: int) -> bool:
    """True when an Order Tracker is already serving on this port."""
    import json
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/ping", timeout=2) as r:
            return json.loads(r.read()).get("app") == "order-tracker"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def stored_here() -> str:
    """What the data folder holds, so a copy can be checked at a glance."""
    import sqlite3

    if not config.DB_PATH.exists():
        return ""
    try:
        conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, timeout=5)
        try:
            orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return "a database that could not be read"
    return f"{orders} orders and {docs} documents"


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local order and document terminal.")
    parser.add_argument("--host", default=config.HOST,
                        help="interface to bind (default 127.0.0.1, this machine only)")
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--demo", action="store_true",
                        help="load sample data into a separate demo database")
    parser.add_argument("--data", metavar="FOLDER",
                        help="keep orders and documents in this folder instead "
                             "(use when the app folder is locked down by "
                             "antivirus or OneDrive)")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-backup", action="store_true",
                        help="skip the startup copy to the backup folder")
    parser.add_argument("--force", action="store_true",
                        help="start even though another machine has the data "
                             "folder open")
    parser.add_argument("--reindex", action="store_true",
                        help="re-read the text of every stored document before starting")
    parser.add_argument("--where", action="store_true",
                        help="print where the data is kept, then exit")
    args = parser.parse_args(argv)

    # An explicit --data folder wins over the demo default.
    if args.data:
        config.DATA_DIR = Path(os.path.expandvars(args.data)).expanduser().resolve()
    elif args.demo:
        config.DATA_DIR = config.DEMO_DIR
    config.DOCS_DIR = config.DATA_DIR / "documents"
    config.DB_PATH = config.DATA_DIR / "orders.db"

    if args.where:
        from ordertracker import settings
        print(f"\n  data folder      {config.DATA_DIR}")
        print(f"  holding          {stored_here() or 'nothing yet'}")
        print(f"  app folder       {config.BASE_DIR}")
        print(f"  settings file    {settings.settings_path()}")
        if config.PORTABLE:
            print("  mode             portable — everything lives in the app "
                  "folder, and\n                   the saved setting is ignored")
        else:
            chosen = settings.load().get("workspace") or ""
            print(f"  chosen location  {chosen or '(none — using the app folder)'}")

        # In portable mode nothing should be left on the machine itself.
        # Say so when something is, since that is the whole point of it.
        leftover = settings.machine_dir()
        if config.PORTABLE and leftover.exists():
            print(f"\n  Still on this machine, from an earlier install:")
            print(f"      {leftover}")
            print("  Nothing reads it while portable.txt is here. Delete it "
                  "if you want\n  this folder to be the only copy.")

        print("\n  Change it with:  py setup.py\n")
        return 0

    from ordertracker import (backup, db, documents, drives, inuse,
                              sampledata, server)

    # Do our temporary work beside the data rather than on the system disk,
    # which a locked-down work computer may refuse Python entirely.
    config.use_own_temp()

    # On a shared folder, two machines writing at once is the way to lose
    # the lot. Check before anything is opened.
    held = inuse.held_elsewhere()
    if held and not args.force:
        print(f"\n  {inuse.describe(held)}\n", file=sys.stderr)
        return 1

    try:
        db.init_db()
    except db.StorageError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1

    if args.demo:
        conn = db.connect()
        existing = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
        if existing:
            print(f"  demo database already holds {existing} orders — leaving it alone")
        else:
            print("  building demo data …")
            counts = sampledata.load()
            print(f"  {counts['orders']} orders, {counts['companies']} companies, "
                  f"{counts['documents']} documents,\n"
                  f"  {counts['emails']} emails in the tray, "
                  f"{counts['cases']} open disputes")

    if not args.no_backup:
        report = backup.run_quietly()
        if report and report.get("ok"):
            print(f"  backed up to {report['path']}")
        elif report:
            print(f"  backup skipped: {report['error'].splitlines()[0]}")

    if args.reindex:
        print("  re-reading stored documents …")
        db.rebuild_search_index()
        print(f"  {documents.reextract_all()} documents re-read")

    port = args.port

    # Double-clicking the desktop icon twice should bring the window back,
    # not start a second copy on a different port.
    if not port_is_free(args.host, port) and already_running(args.host, port):
        url = f"http://{args.host}:{port}/"
        print(f"\n  Order Tracker is already running at {url}")
        print("  Opening it again.\n")
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    if not port_is_free(args.host, port):
        for candidate in range(port + 1, port + 25):
            if port_is_free(args.host, candidate):
                print(f"  port {port} was busy, using {candidate}")
                port = candidate
                break
        else:
            print(f"Could not find a free port near {port}.", file=sys.stderr)
            return 1

    url = f"http://{args.host}:{port}/"
    httpd = server.serve(args.host, port)

    inuse.claim()
    keep_note = threading.Event()

    def hold_the_note():
        while not keep_note.wait(inuse.REFRESH_SECONDS):
            inuse.claim()

    threading.Thread(target=hold_the_note, daemon=True).start()

    print()
    print("  ORDER TRACKER")
    print(f"  {url}")
    print(f"  data: {config.DATA_DIR}")
    if db.on_network():
        where = drives.describe(config.DATA_DIR)["where"]
        print(f"  note: this data folder is on {where}.")
        print("        Keep one machine on it at a time, and keep a backup")
        print("        somewhere local — SETUP > BACKUP FOLDER.")
        from ordertracker import prefs
        if not (prefs.get("backup_dir") or "").strip():
            print("        No backup folder is set yet. Please set one.")
    print("  to stop: click QUIT in the app, or press Ctrl+C here")
    print()

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        keep_note.set()
        inuse.release()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
