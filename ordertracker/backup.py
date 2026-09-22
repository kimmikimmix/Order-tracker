"""A second copy of everything, somewhere else.

The database is copied through SQLite's own backup call rather than as a
file, because in WAL mode the newest changes live in a side file and a plain
copy can arrive empty. Documents are mirrored instead of re-copied: a stored
document never changes, so only new ones need moving each time.
"""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from . import config, db, prefs, settings

FOLDER_NAME = "OrderTracker Backup"
STAMP = "%Y%m%d-%H%M%S"


class BackupError(Exception):
    """Somewhere to put the copy could not be used."""


def destination(folder=None) -> Path | None:
    """The backup folder, or None when one has not been chosen."""
    chosen = folder if folder is not None else prefs.get("backup_dir")
    chosen = str(chosen or "").strip()
    if not chosen:
        return None
    return settings.expand(chosen).resolve() / FOLDER_NAME


def last_saved() -> dict:
    """When the order book last changed, and how big it is."""
    stamp = db.meta_get("last_saved")
    size = None
    try:
        size = config.DB_PATH.stat().st_size
        if not stamp:
            stamp = datetime.fromtimestamp(
                config.DB_PATH.stat().st_mtime
            ).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        pass
    return {"saved_at": stamp, "db_size": size, "db_path": str(config.DB_PATH)}


def copy_database(target_db: Path) -> None:
    """Write a consistent copy of the live database, WAL included."""
    target_db.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, timeout=30)
    try:
        target = sqlite3.connect(target_db, timeout=30)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _mirror_documents(root: Path) -> int:
    """Copy across any document not already in the backup."""
    if not config.DOCS_DIR.exists():
        return 0
    mirror = root / "documents"
    mirror.mkdir(parents=True, exist_ok=True)
    copied = 0
    for item in config.DOCS_DIR.iterdir():
        if not item.is_file():
            continue
        twin = mirror / item.name
        try:
            if twin.exists() and twin.stat().st_size == item.stat().st_size:
                continue
            shutil.copy2(item, twin)
            copied += 1
        except OSError:
            continue  # one unreadable file must not stop the rest
    return copied


def _prune(root: Path, keep: int) -> list[str]:
    """Delete all but the newest few snapshots."""
    snapshots = sorted(root.glob("orders-*.db"), key=lambda p: p.name, reverse=True)
    removed = []
    for old in snapshots[max(1, keep):]:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            pass
    return removed


def run(folder=None) -> dict:
    """Take a backup now. Returns what was written, for the status bar."""
    root = destination(folder)
    if root is None:
        raise BackupError(
            "No backup folder has been chosen yet. Set one on the SETUP page."
        )
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".writable"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise BackupError(
            f"Cannot write to the backup folder:\n    {root}\n\n{exc}\n\n"
            "If it is a network or company drive you may not have permission "
            "to write there. Pick another folder on the SETUP page."
        ) from exc

    name = f"orders-{datetime.now().strftime(STAMP)}.db"
    target = root / name
    try:
        copy_database(target)
    except (OSError, sqlite3.Error) as exc:
        raise BackupError(f"The database could not be copied: {exc}") from exc

    documents = _mirror_documents(root)
    removed = _prune(root, int(prefs.get("backup_keep") or 10))

    stamp = db.now()
    db.meta_set("last_backup_at", stamp)
    db.meta_set("last_backup_path", str(target))
    return {
        "ok": True, "path": str(target), "folder": str(root),
        "documents_copied": documents, "removed": removed, "at": stamp,
        "size": target.stat().st_size if target.exists() else 0,
    }


def status() -> dict:
    """What the settings page shows about backups."""
    root = destination()
    snapshots = []
    if root and root.exists():
        for item in sorted(root.glob("orders-*.db"), reverse=True):
            try:
                snapshots.append({"name": item.name, "size": item.stat().st_size})
            except OSError:
                continue
    return {
        "folder": str(root) if root else "",
        "configured": bool(root),
        "exists": bool(root and root.exists()),
        "last_backup_at": db.meta_get("last_backup_at"),
        "last_backup_path": db.meta_get("last_backup_path"),
        "snapshots": snapshots[:20],
        "keep": int(prefs.get("backup_keep") or 10),
        "on_start": bool(prefs.get("backup_on_start")),
        **last_saved(),
    }


def run_quietly() -> dict | None:
    """Startup backup. A failure here must never stop the app opening."""
    if not prefs.get("backup_on_start") or destination() is None:
        return None
    try:
        return run()
    except (BackupError, OSError, sqlite3.Error) as exc:
        return {"ok": False, "error": str(exc)}
