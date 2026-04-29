from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .storage import DEFAULT_DB_PATH
from .google_drive import google_drive_backup_enabled, upload_backup_to_google_drive


DEFAULT_BACKUP_DIR = "./backups"
DEFAULT_RETENTION_DAYS = 31
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60


def backup_once(
    *,
    db_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    now: datetime | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    db = Path(db_path or os.getenv("PALATE_DB_PATH") or DEFAULT_DB_PATH).resolve()
    target_dir = Path(
        backup_dir or os.getenv("PALATE_BACKUP_DIR") or DEFAULT_BACKUP_DIR
    ).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    sqlite_target = target_dir / f"palate-{timestamp}.sqlite"
    json_target = target_dir / f"palate-{timestamp}.json"

    backup_sqlite(db, sqlite_target)
    export_json(sqlite_target, json_target)
    removed = cleanup_old_backups(
        backup_dir=target_dir,
        retention_days=retention_days,
        now=now,
    )
    google_drive = {"enabled": False}
    if google_drive_backup_enabled():
        google_drive = upload_backup_to_google_drive(
            sqlite_path=sqlite_target,
            json_path=json_target,
            retention_days=retention_days,
            now=now,
        )

    return {
        "sqlite": str(sqlite_target),
        "json": str(json_target),
        "removed": [str(path) for path in removed],
        "google_drive": google_drive,
    }


def backup_sqlite(source: Path, target: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Palate database does not exist: {source}")

    source_conn = sqlite3.connect(source)
    try:
        target_conn = sqlite3.connect(target)
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
    finally:
        source_conn.close()


def export_json(sqlite_path: Path, target: Path) -> None:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        payload = {
            "exported_at": datetime.now(UTC).isoformat(),
            "entities": [dict(row) for row in conn.execute("SELECT * FROM entities")],
            "attributes": [dict(row) for row in conn.execute("SELECT * FROM attributes")],
            "signals": [dict(row) for row in conn.execute("SELECT * FROM signals")],
            "decisions": [dict(row) for row in conn.execute("SELECT * FROM decisions")],
        }
    finally:
        conn.close()

    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def cleanup_old_backups(
    *,
    backup_dir: str | Path,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    now: datetime | None = None,
) -> list[Path]:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    removed = []

    for path in Path(backup_dir).glob("palate-*"):
        if path.suffix not in {".sqlite", ".json"}:
            continue
        timestamp = parse_backup_timestamp(path)
        if timestamp is None or timestamp >= cutoff:
            continue
        path.unlink()
        removed.append(path)

    return removed


def start_backup_scheduler() -> threading.Thread | None:
    if os.getenv("PALATE_BACKUP_ENABLED", "1").lower() in {"0", "false", "no"}:
        return None

    interval_seconds = int(
        os.getenv("PALATE_BACKUP_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS))
    )
    retention_days = int(
        os.getenv("PALATE_BACKUP_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS))
    )
    db_path = os.getenv("PALATE_DB_PATH") or DEFAULT_DB_PATH
    backup_dir = os.getenv("PALATE_BACKUP_DIR") or DEFAULT_BACKUP_DIR

    def loop() -> None:
        while True:
            try:
                backup_once(
                    db_path=db_path,
                    backup_dir=backup_dir,
                    retention_days=retention_days,
                )
            except Exception as exc:  # noqa: BLE001 - keep server alive if backup fails.
                print(f"Palate backup failed: {exc}", flush=True)
            time.sleep(interval_seconds)

    thread = threading.Thread(target=loop, name="palate-backup", daemon=True)
    thread.start()
    return thread


def parse_backup_timestamp(path: Path) -> datetime | None:
    name = path.stem
    if not name.startswith("palate-"):
        return None
    timestamp = name.removeprefix("palate-")
    try:
        return datetime.strptime(timestamp, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None
