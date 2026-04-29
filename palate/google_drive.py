from __future__ import annotations

import mimetypes
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DEFAULT_CREDENTIALS_PATH = "./secrets/google-oauth-client.json"
DEFAULT_TOKEN_PATH = "./secrets/google-token.json"
DEFAULT_FOLDER_NAME = "backup/palate"


def upload_backup_to_google_drive(
    *,
    sqlite_path: str | Path,
    json_path: str | Path,
    retention_days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    service = build_drive_service(allow_interactive=False)
    folder_path = backup_folder_path()
    folder_id = ensure_backup_folder(service)
    uploaded = [
        upload_file(service, Path(sqlite_path), folder_id),
        upload_file(service, Path(json_path), folder_id),
    ]
    removed = cleanup_old_drive_backups(
        service,
        folder_id=folder_id,
        retention_days=retention_days,
        now=now,
    )
    return {
        "enabled": True,
        "folder_path": "/".join(folder_path),
        "folder_id": folder_id,
        "uploaded": uploaded,
        "removed": removed,
    }


def authorize_google_drive() -> dict[str, Any]:
    service = build_drive_service(allow_interactive=True)
    folder_path = backup_folder_path()
    folder_id = ensure_backup_folder(service)
    return {
        "authorized": True,
        "folder_path": "/".join(folder_path),
        "folder_id": folder_id,
        "token_path": str(token_path().resolve()),
    }


def build_drive_service(*, allow_interactive: bool):
    from googleapiclient.discovery import build

    creds = load_credentials(allow_interactive=allow_interactive)
    return build("drive", "v3", credentials=creds)


def load_credentials(*, allow_interactive: bool):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token = token_path()
    credentials = credentials_path()
    creds = None

    if token.exists():
        creds = Credentials.from_authorized_user_file(str(token), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif allow_interactive:
        if not credentials.exists():
            raise FileNotFoundError(f"Google OAuth client file not found: {credentials}")
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials), SCOPES)
        creds = flow.run_local_server(port=0)
    else:
        raise RuntimeError(
            "Google Drive backup is enabled, but no valid token is available. "
            "Run `python3 -m palate.google_drive` once from a user session."
        )

    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    return creds


def ensure_backup_folder(service) -> str:
    configured_folder_id = os.getenv("PALATE_GOOGLE_DRIVE_FOLDER_ID")
    if configured_folder_id:
        return configured_folder_id

    parent_id = "root"
    for folder_name in backup_folder_path():
        parent_id = ensure_child_folder(service, folder_name, parent_id)

    return parent_id


def ensure_child_folder(service, folder_name: str, parent_id: str) -> str:
    query = (
        "mimeType = 'application/vnd.google-apps.folder' "
        f"and name = '{escape_drive_query(folder_name)}' "
        f"and '{escape_drive_query(parent_id)}' in parents "
        "and trashed = false"
    )
    response = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id, name)", pageSize=10)
        .execute()
    )
    folders = response.get("files", [])
    if folders:
        return folders[0]["id"]

    folder = (
        service.files()
        .create(
            body={
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            },
            fields="id",
        )
        .execute()
    )
    return folder["id"]


def backup_folder_path() -> list[str]:
    configured = os.getenv("PALATE_GOOGLE_DRIVE_FOLDER_NAME", DEFAULT_FOLDER_NAME)
    parts = [part.strip() for part in configured.split("/") if part.strip()]
    if not parts:
        raise ValueError("PALATE_GOOGLE_DRIVE_FOLDER_NAME must include at least one folder")
    return parts


def upload_file(service, path: Path, folder_id: str) -> dict[str, str]:
    from googleapiclient.http import MediaFileUpload

    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    media = MediaFileUpload(str(path), mimetype=mime_type, resumable=True)
    uploaded = (
        service.files()
        .create(
            body={"name": path.name, "parents": [folder_id]},
            media_body=media,
            fields="id, name",
        )
        .execute()
    )
    return {"id": uploaded["id"], "name": uploaded["name"]}


def cleanup_old_drive_backups(
    service,
    *,
    folder_id: str,
    retention_days: int,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    removed = []
    page_token = None

    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and name contains 'palate-' and trashed = false",
                spaces="drive",
                fields="nextPageToken, files(id, name)",
                pageSize=100,
                pageToken=page_token,
            )
            .execute()
        )
        for item in response.get("files", []):
            timestamp = parse_drive_backup_timestamp(item["name"])
            if timestamp is None or timestamp >= cutoff:
                continue
            service.files().delete(fileId=item["id"]).execute()
            removed.append({"id": item["id"], "name": item["name"]})

        page_token = response.get("nextPageToken")
        if not page_token:
            return removed


def google_drive_backup_enabled() -> bool:
    return os.getenv("PALATE_BACKUP_GOOGLE_DRIVE_ENABLED", "0").lower() in {
        "1",
        "true",
        "yes",
    }


def credentials_path() -> Path:
    return Path(
        os.getenv("PALATE_GOOGLE_CREDENTIALS_PATH", DEFAULT_CREDENTIALS_PATH)
    ).expanduser()


def token_path() -> Path:
    return Path(os.getenv("PALATE_GOOGLE_TOKEN_PATH", DEFAULT_TOKEN_PATH)).expanduser()


def escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def parse_drive_backup_timestamp(name: str) -> datetime | None:
    stem = Path(name).stem
    if not stem.startswith("palate-"):
        return None
    timestamp = stem.removeprefix("palate-")
    try:
        return datetime.strptime(timestamp, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def main() -> None:
    result = authorize_google_drive()
    print(
        "Google Drive authorization complete. "
        f"Folder path: {result['folder_path']} "
        f"(ID: {result['folder_id']})"
    )
    print(f"Token saved to: {result['token_path']}")


if __name__ == "__main__":
    main()
