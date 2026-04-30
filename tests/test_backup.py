from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from palate.backup import backup_once, cleanup_old_backups, start_backup_scheduler
from palate.storage import open_store


class BackupBehaviorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="palate-backup-"))
        self.db_path = self.temp_dir / "palate.sqlite"
        self.backup_dir = self.temp_dir / "backups"
        self.store = open_store(str(self.db_path))
        self.store.upsert_entity(
            {
                "id": "wine_backup",
                "type": "wine",
                "canonical_name": "Backup Wine",
                "attributes": {"oak": 0.7},
                "signals": [{"type": "rating", "value": 8}],
            }
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_backup_once_creates_sqlite_and_json_snapshots(self) -> None:
        result = backup_once(
            db_path=self.db_path,
            backup_dir=self.backup_dir,
            now=datetime(2026, 4, 28, 12, 30, 0, tzinfo=UTC),
        )

        sqlite_path = Path(result["sqlite"])
        json_path = Path(result["json"])
        self.assertTrue(sqlite_path.exists())
        self.assertTrue(json_path.exists())
        self.assertEqual(sqlite_path.name, "palate-20260428-123000.sqlite")
        self.assertEqual(json_path.name, "palate-20260428-123000.json")

        exported = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(exported["entities"][0]["canonical_name"], "Backup Wine")
        self.assertEqual(exported["entities"][0]["metadata_json"], "{}")
        self.assertEqual(exported["attributes"][0]["key"], "oak")
        self.assertEqual(exported["signals"][0]["type"], "rating")
        self.assertEqual(result["google_drive"], {"enabled": False})

    def test_backup_once_uploads_to_google_drive_when_enabled(self) -> None:
        with patch(
            "palate.backup.google_drive_backup_enabled",
            return_value=True,
        ), patch(
            "palate.backup.upload_backup_to_google_drive",
            return_value={"enabled": True, "uploaded": [], "removed": []},
        ) as upload:
            result = backup_once(
                db_path=self.db_path,
                backup_dir=self.backup_dir,
                now=datetime(2026, 4, 28, 12, 30, 0, tzinfo=UTC),
            )

        self.assertTrue(result["google_drive"]["enabled"])
        upload.assert_called_once()
        kwargs = upload.call_args.kwargs
        self.assertEqual(Path(kwargs["sqlite_path"]).name, "palate-20260428-123000.sqlite")
        self.assertEqual(Path(kwargs["json_path"]).name, "palate-20260428-123000.json")

    def test_cleanup_old_backups_deletes_expired_snapshot_pairs(self) -> None:
        old_sqlite = self.backup_dir / "palate-20260301-000000.sqlite"
        old_json = self.backup_dir / "palate-20260301-000000.json"
        fresh_sqlite = self.backup_dir / "palate-20260420-000000.sqlite"
        unrelated = self.backup_dir / "notes.txt"
        self.backup_dir.mkdir()
        for path in [old_sqlite, old_json, fresh_sqlite, unrelated]:
            path.write_text("x", encoding="utf-8")

        removed = cleanup_old_backups(
            backup_dir=self.backup_dir,
            retention_days=31,
            now=datetime(2026, 4, 28, tzinfo=UTC),
        )

        self.assertEqual({path.name for path in removed}, {old_sqlite.name, old_json.name})
        self.assertFalse(old_sqlite.exists())
        self.assertFalse(old_json.exists())
        self.assertTrue(fresh_sqlite.exists())
        self.assertTrue(unrelated.exists())

    def test_backup_once_cleans_up_old_backups_after_successful_snapshot(self) -> None:
        self.backup_dir.mkdir()
        expired = self.backup_dir / "palate-20260301-000000.sqlite"
        expired.write_text("old", encoding="utf-8")

        result = backup_once(
            db_path=self.db_path,
            backup_dir=self.backup_dir,
            now=datetime(2026, 4, 28, 12, 30, 0, tzinfo=UTC),
            retention_days=31,
        )

        self.assertFalse(expired.exists())
        self.assertIn(str(expired.resolve()), result["removed"])

    def test_scheduler_can_be_disabled(self) -> None:
        with patch.dict(os.environ, {"PALATE_BACKUP_ENABLED": "0"}):
            self.assertIsNone(start_backup_scheduler())
