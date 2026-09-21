#!/usr/bin/env python3
"""Order Tracker — start the local terminal.

    python3 run.py              start, and open the browser
    python3 run.py --demo       load sample data first, in its own database
    python3 run.py --port 9000  use a different port
    python3 run.py --reindex    re-read every stored document, then start

Nothing here needs installing: it runs on a stock Python 3.10 or newer.
"""

import argparse
import socket
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ordertracker import config  # noqa: E402


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
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--reindex", action="store_true",
                        help="re-read the text of every stored document before starting")
    args = parser.parse_args(argv)

    if args.demo:
        config.DATA_DIR = config.DATA_DIR.parent / "demo-data"
        config.DOCS_DIR = config.DATA_DIR / "documents"
        config.DB_PATH = config.DATA_DIR / "orders.db"

    from ordertracker import db, documents, sampledata, server

    db.init_db()

    if args.demo:
        conn = db.connect()
        existing = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
        if existing:
            print(f"  demo database already holds {existing} orders — leaving it alone")
        else:
            print("  building demo data …")
            counts = sampledata.load()
            print(f"  {counts['orders']} orders, {counts['companies']} companies, "
                  f"{counts['documents']} documents")

    if args.reindex:
        print("  re-reading stored documents …")
        db.rebuild_search_index()
        print(f"  {documents.reextract_all()} documents re-read")

    port = args.port
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

    print()
    print("  ORDER TRACKER")
    print(f"  {url}")
    print(f"  data: {config.DATA_DIR}")
    print("  press Ctrl+C to stop")
    print()

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
