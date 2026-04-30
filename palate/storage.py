from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = "./data/palate.sqlite"


def open_store(db_path: str | None = None) -> "PalateStore":
    import os

    resolved = Path(db_path or os.getenv("PALATE_DB_PATH") or DEFAULT_DB_PATH).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return PalateStore(conn)


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP INDEX IF EXISTS signals_entity_type_value_provenance_unique;

        CREATE TABLE IF NOT EXISTS entities (
          id TEXT PRIMARY KEY,
          type TEXT NOT NULL,
          canonical_name TEXT NOT NULL,
          source_text TEXT,
          notes TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS attributes (
          entity_id TEXT NOT NULL,
          key TEXT NOT NULL,
          value REAL NOT NULL CHECK (value >= 0 AND value <= 1),
          PRIMARY KEY (entity_id, key),
          FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS signals (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          entity_id TEXT NOT NULL,
          type TEXT NOT NULL,
          value TEXT NOT NULL,
          provenance TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
        );

        DELETE FROM signals
        WHERE id NOT IN (
          SELECT MIN(id)
          FROM signals
          GROUP BY entity_id, type, value, COALESCE(provenance, '')
        );

        CREATE TABLE IF NOT EXISTS decisions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          query TEXT NOT NULL,
          context_json TEXT NOT NULL,
          options_json TEXT NOT NULL,
          ranked_json TEXT NOT NULL,
          chosen_entity_id TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS schema_migrations (
          key TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(entities)").fetchall()
    }
    if "metadata_json" not in columns:
        conn.execute(
            "ALTER TABLE entities ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
        )
    migrate_rating_signals_to_ten_point_scale(conn)
    conn.execute(
        """
        DELETE FROM signals
        WHERE id NOT IN (
          SELECT MIN(id)
          FROM signals
          GROUP BY entity_id, type, value, COALESCE(provenance, '')
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS signals_entity_type_value_provenance_unique
        ON signals (entity_id, type, value, COALESCE(provenance, ''))
        """
    )
    conn.commit()


def migrate_rating_signals_to_ten_point_scale(conn: sqlite3.Connection) -> None:
    migration_key = "rating_scale_1_to_10"
    applied = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE key = ?",
        (migration_key,),
    ).fetchone()
    if applied is not None:
        return

    rows = conn.execute("SELECT id, value FROM signals WHERE type = 'rating'").fetchall()
    for row in rows:
        row_id = row["id"] if isinstance(row, sqlite3.Row) else row[0]
        value = row["value"] if isinstance(row, sqlite3.Row) else row[1]
        try:
            rating = float(value)
        except (TypeError, ValueError):
            continue
        if 1 <= rating <= 5:
            conn.execute(
                "UPDATE signals SET value = ? WHERE id = ?",
                (format_signal_number(rating * 2), row_id),
            )

    conn.execute(
        "INSERT INTO schema_migrations (key) VALUES (?)",
        (migration_key,),
    )


class PalateStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_entity(self, entity: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO entities (
              id,
              type,
              canonical_name,
              source_text,
              notes,
              metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              type = excluded.type,
              canonical_name = excluded.canonical_name,
              source_text = excluded.source_text,
              notes = excluded.notes,
              metadata_json = excluded.metadata_json
            """,
            (
                entity["id"],
                entity["type"],
                entity["canonical_name"],
                entity.get("source_text"),
                entity.get("notes"),
                json.dumps(entity.get("metadata") or {}, sort_keys=True),
            ),
        )

        for key, value in (entity.get("attributes") or {}).items():
            self.set_attribute(entity["id"], key, value)

        for signal in entity.get("signals") or []:
            self.add_signal(
                entity["id"],
                signal["type"],
                signal["value"],
                signal.get("provenance"),
            )

        self.conn.commit()

    def set_attribute(self, entity_id: str, key: str, value: float) -> None:
        self.conn.execute(
            """
            INSERT INTO attributes (entity_id, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT(entity_id, key) DO UPDATE SET value = excluded.value
            """,
            (entity_id, key, clamp01(value)),
        )

    def add_signal(
        self,
        entity_id: str,
        signal_type: str,
        value: Any,
        provenance: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO signals (entity_id, type, value, provenance)
            VALUES (?, ?, ?, ?)
            """,
            (entity_id, signal_type, str(value), provenance),
        )
        self.conn.commit()

    def list_entities(self) -> list[dict[str, Any]]:
        entities = self.conn.execute(
            "SELECT * FROM entities ORDER BY canonical_name"
        ).fetchall()

        result = []
        for entity in entities:
            entity_dict = dict(entity)
            entity_dict["metadata"] = parse_metadata(entity_dict.get("metadata_json"))
            attrs = self.conn.execute(
                "SELECT key, value FROM attributes WHERE entity_id = ?",
                (entity_dict["id"],),
            ).fetchall()
            signals = self.conn.execute(
                """
                SELECT type, value, provenance, created_at
                FROM signals
                WHERE entity_id = ?
                ORDER BY id DESC
                """,
                (entity_dict["id"],),
            ).fetchall()
            entity_dict["attributes"] = {row["key"]: row["value"] for row in attrs}
            entity_dict["signals"] = [dict(row) for row in signals]
            result.append(entity_dict)

        return result

    def find_entities_by_names(self, names: list[str]) -> list[dict[str, Any]]:
        return self.match_entities_by_names(names)["matched"]

    def delete_entity(self, entity_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if row is None:
            return None

        deleted = dict(row)
        deleted["metadata"] = parse_metadata(deleted.get("metadata_json"))
        cursor = self.conn.execute(
            "DELETE FROM entities WHERE id = ?",
            (entity_id,),
        )
        self.conn.commit()
        return deleted if cursor.rowcount else None

    def match_entities_by_names(self, names: list[str]) -> dict[str, list[Any]]:
        all_entities = self.list_entities()
        matched = []
        unmatched = []

        for name in names:
            normalized = normalize(name)
            entity = next(
                (
                    candidate
                    for candidate in all_entities
                    if normalize(candidate["canonical_name"]) == normalized
                ),
                None,
            )
            if entity is None:
                entity = next(
                    (
                        candidate
                        for candidate in all_entities
                        if normalized in normalize(candidate["canonical_name"])
                        or normalize(candidate["canonical_name"]) in normalized
                    ),
                    None,
                )

            if entity:
                matched.append(entity)
            else:
                unmatched.append(name)

        return {"matched": unique_by_id(matched), "unmatched": unmatched}

    def log_decision(
        self,
        query: str,
        context: dict[str, Any] | None,
        options: list[Any] | None,
        ranked: list[Any] | None,
        chosen_entity_id: str | None = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO decisions (
              query,
              context_json,
              options_json,
              ranked_json,
              chosen_entity_id
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                query,
                json.dumps(context or {}),
                json.dumps(options or []),
                json.dumps(ranked or []),
                chosen_entity_id,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def update_decision_choice(self, decision_id: int, chosen_entity_id: str) -> int:
        cursor = self.conn.execute(
            "UPDATE decisions SET chosen_entity_id = ? WHERE id = ?",
            (chosen_entity_id, decision_id),
        )
        self.conn.commit()
        return cursor.rowcount


def normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def clamp01(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))


def format_signal_number(value: float) -> str:
    return f"{value:g}"


def parse_metadata(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        metadata = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def unique_by_id(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    unique = []
    for entity in entities:
        if entity["id"] in seen:
            continue
        seen.add(entity["id"])
        unique.append(entity)
    return unique
