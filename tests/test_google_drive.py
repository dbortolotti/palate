from __future__ import annotations

import os
import re
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from palate.google_drive import (
    backup_folder_path,
    cleanup_old_drive_backups,
    ensure_backup_folder,
    escape_drive_query,
    google_drive_backup_enabled,
    parse_drive_backup_timestamp,
)


class GoogleDriveBackupBehaviorTest(unittest.TestCase):
    def test_google_drive_backup_is_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(google_drive_backup_enabled())

    def test_google_drive_backup_accepts_truthy_env_values(self) -> None:
        for value in ["1", "true", "yes"]:
            with self.subTest(value=value), patch.dict(
                os.environ,
                {"PALATE_BACKUP_GOOGLE_DRIVE_ENABLED": value},
                clear=True,
            ):
                self.assertTrue(google_drive_backup_enabled())

    def test_escape_drive_query_handles_quotes_and_backslashes(self) -> None:
        self.assertEqual(escape_drive_query("Palate's \\ Backups"), "Palate\\'s \\\\ Backups")

    def test_parse_drive_backup_timestamp_accepts_supported_backup_names(self) -> None:
        self.assertEqual(
            parse_drive_backup_timestamp("palate-20260428-123000.sqlite"),
            datetime(2026, 4, 28, 12, 30, tzinfo=UTC),
        )
        self.assertIsNone(parse_drive_backup_timestamp("notes.txt"))
        self.assertIsNone(parse_drive_backup_timestamp("palate-not-a-date.sqlite"))

    def test_ensure_backup_folder_uses_configured_folder_id(self) -> None:
        with patch.dict(os.environ, {"PALATE_GOOGLE_DRIVE_FOLDER_ID": "folder-123"}):
            self.assertEqual(ensure_backup_folder(FakeDriveService([])), "folder-123")

    def test_ensure_backup_folder_finds_existing_folder(self) -> None:
        service = FakeDriveService(
            [{"id": "existing", "name": "Palate Backups", "kind": "folder"}]
        )

        with patch.dict(
            os.environ,
            {"PALATE_GOOGLE_DRIVE_FOLDER_NAME": "Palate Backups"},
            clear=True,
        ):
            self.assertEqual(ensure_backup_folder(service), "existing")

        self.assertEqual(service.created, [])

    def test_ensure_backup_folder_creates_missing_folder(self) -> None:
        service = FakeDriveService([])

        with patch.dict(
            os.environ,
            {"PALATE_GOOGLE_DRIVE_FOLDER_NAME": "Palate Backups"},
            clear=True,
        ):
            self.assertEqual(ensure_backup_folder(service), "created-1")

        self.assertEqual(service.created[0]["name"], "Palate Backups")
        self.assertEqual(service.created[0]["parents"], ["root"])

    def test_ensure_backup_folder_creates_nested_folder_path(self) -> None:
        service = FakeDriveService([])

        with patch.dict(
            os.environ,
            {"PALATE_GOOGLE_DRIVE_FOLDER_NAME": "backup/palate"},
            clear=True,
        ):
            self.assertEqual(ensure_backup_folder(service), "created-2")

        self.assertEqual(
            [(item["name"], item["parents"]) for item in service.created],
            [("backup", ["root"]), ("palate", ["created-1"])],
        )

    def test_ensure_backup_folder_reuses_nested_folder_path(self) -> None:
        service = FakeDriveService(
            [
                {
                    "id": "backup-folder",
                    "name": "backup",
                    "kind": "folder",
                    "parents": ["root"],
                },
                {
                    "id": "palate-folder",
                    "name": "palate",
                    "kind": "folder",
                    "parents": ["backup-folder"],
                },
            ]
        )

        with patch.dict(
            os.environ,
            {"PALATE_GOOGLE_DRIVE_FOLDER_NAME": "backup/palate"},
            clear=True,
        ):
            self.assertEqual(ensure_backup_folder(service), "palate-folder")

        self.assertEqual(service.created, [])

    def test_backup_folder_path_trims_empty_path_segments(self) -> None:
        with patch.dict(
            os.environ,
            {"PALATE_GOOGLE_DRIVE_FOLDER_NAME": " / backup / palate / "},
            clear=True,
        ):
            self.assertEqual(backup_folder_path(), ["backup", "palate"])

    def test_cleanup_old_drive_backups_deletes_only_expired_backup_files(self) -> None:
        service = FakeDriveService(
            [
                {"id": "old-sqlite", "name": "palate-20260301-000000.sqlite"},
                {"id": "old-json", "name": "palate-20260301-000000.json"},
                {"id": "fresh", "name": "palate-20260420-000000.sqlite"},
                {"id": "invalid", "name": "palate-not-a-date.sqlite"},
                {"id": "other", "name": "notes.txt"},
            ]
        )

        removed = cleanup_old_drive_backups(
            service,
            folder_id="folder",
            retention_days=31,
            now=datetime(2026, 4, 28, tzinfo=UTC),
        )

        self.assertEqual(
            {item["id"] for item in removed},
            {"old-sqlite", "old-json"},
        )
        self.assertEqual(service.deleted, ["old-sqlite", "old-json"])


class FakeDriveService:
    def __init__(self, files):
        self.files_resource = FakeFilesResource(files)
        self.created = self.files_resource.created
        self.deleted = self.files_resource.deleted

    def files(self):
        return self.files_resource


class FakeFilesResource:
    def __init__(self, files):
        self.files = list(files)
        self.created = []
        self.deleted = []

    def list(self, **kwargs):
        query = kwargs.get("q", "")
        if "mimeType = 'application/vnd.google-apps.folder'" in query:
            name = query_value(query, "name")
            parent_id = parent_query_value(query)
            files = [
                item
                for item in self.files
                if item.get("kind") == "folder"
                and item["name"] == name
                and parent_id in item_parents(item)
            ]
        else:
            parent_id = parent_query_value(query)
            files = [
                {"id": item["id"], "name": item["name"]}
                for item in self.files
                if item.get("kind") != "folder"
                and (parent_id is None or parent_id in item_parents(item))
            ]
        return FakeExecute({"files": files})

    def create(self, **kwargs):
        body = kwargs.get("body", {})
        item = {
            "id": f"created-{len(self.created) + 1}",
            "name": body["name"],
            "kind": "folder" if body.get("mimeType") == "application/vnd.google-apps.folder" else "file",
            "parents": body.get("parents", ["root"]),
        }
        self.created.append(item)
        self.files.append(item)
        return FakeExecute({"id": item["id"], "name": item["name"]})

    def delete(self, **kwargs):
        self.deleted.append(kwargs["fileId"])
        return FakeExecute({})


class FakeExecute:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


def query_value(query: str, field: str) -> str | None:
    match = re.search(rf"{field} = '((?:\\\\'|[^'])*)'", query)
    if not match:
        return None
    return match.group(1).replace("\\'", "'").replace("\\\\", "\\")


def parent_query_value(query: str) -> str | None:
    match = re.search(r"and '((?:\\\\'|[^'])*)' in parents", query)
    if not match:
        return None
    return match.group(1).replace("\\'", "'").replace("\\\\", "\\")


def item_parents(item) -> list[str]:
    if "parents" in item:
        return item["parents"]
    if item.get("kind") == "folder":
        return ["root"]
    return ["folder"]
