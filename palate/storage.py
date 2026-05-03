from __future__ import annotations

from difflib import SequenceMatcher
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
          lower_95 REAL NOT NULL DEFAULT 0 CHECK (lower_95 >= 0 AND lower_95 <= 1),
          upper_95 REAL NOT NULL DEFAULT 1 CHECK (upper_95 >= 0 AND upper_95 <= 1),
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

        CREATE TABLE IF NOT EXISTS application_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          tool_name TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN ('success', 'error')),
          duration_ms REAL NOT NULL,
          input_json TEXT NOT NULL,
          output_json TEXT,
          error_json TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}',
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
    migrate_attribute_intervals(conn)
    migrate_rating_signals_to_ten_point_scale(conn)
    migrate_wine_attributes_to_flavour_wheel(conn)
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


def migrate_attribute_intervals(conn: sqlite3.Connection) -> None:
    migration_key = "attribute_intervals_95"
    applied = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE key = ?",
        (migration_key,),
    ).fetchone()
    attribute_columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(attributes)").fetchall()
    }
    had_interval_columns = (
        "lower_95" in attribute_columns and "upper_95" in attribute_columns
    )
    if (
        applied is not None
        and "lower_95" in attribute_columns
        and "upper_95" in attribute_columns
        and "confidence" not in attribute_columns
    ):
        return

    if "lower_95" not in attribute_columns:
        conn.execute(
            """
            ALTER TABLE attributes
            ADD COLUMN lower_95 REAL NOT NULL DEFAULT 0
            CHECK (lower_95 >= 0 AND lower_95 <= 1)
            """
        )
    if "upper_95" not in attribute_columns:
        conn.execute(
            """
            ALTER TABLE attributes
            ADD COLUMN upper_95 REAL NOT NULL DEFAULT 1
            CHECK (upper_95 >= 0 AND upper_95 <= 1)
            """
        )

    attribute_columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(attributes)").fetchall()
    }
    if "confidence" in attribute_columns:
        rows = conn.execute(
            "SELECT entity_id, key, value, confidence FROM attributes"
        ).fetchall()
        for row in rows:
            entity_id = row["entity_id"] if isinstance(row, sqlite3.Row) else row[0]
            key = row["key"] if isinstance(row, sqlite3.Row) else row[1]
            value = row["value"] if isinstance(row, sqlite3.Row) else row[2]
            confidence = row["confidence"] if isinstance(row, sqlite3.Row) else row[3]
            interval = interval_from_legacy_confidence(value, confidence)
            conn.execute(
                """
                UPDATE attributes
                SET lower_95 = ?, upper_95 = ?
                WHERE entity_id = ? AND key = ?
                """,
                (interval["lower"], interval["upper"], entity_id, key),
            )
        rebuild_attributes_without_confidence(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (key) VALUES (?)",
            (migration_key,),
        )
        return

    if applied is None and not had_interval_columns:
        conn.execute(
            """
            UPDATE attributes
            SET lower_95 = value, upper_95 = value
            WHERE lower_95 = 0 AND upper_95 = 1
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations (key) VALUES (?)",
            (migration_key,),
        )
    elif applied is None:
        conn.execute(
            "INSERT INTO schema_migrations (key) VALUES (?)",
            (migration_key,),
        )


def rebuild_attributes_without_confidence(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        ALTER TABLE attributes RENAME TO attributes_with_confidence;

        CREATE TABLE attributes (
          entity_id TEXT NOT NULL,
          key TEXT NOT NULL,
          value REAL NOT NULL CHECK (value >= 0 AND value <= 1),
          lower_95 REAL NOT NULL DEFAULT 0 CHECK (lower_95 >= 0 AND lower_95 <= 1),
          upper_95 REAL NOT NULL DEFAULT 1 CHECK (upper_95 >= 0 AND upper_95 <= 1),
          PRIMARY KEY (entity_id, key),
          FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
        );

        INSERT INTO attributes (entity_id, key, value, lower_95, upper_95)
        SELECT entity_id, key, value, lower_95, upper_95
        FROM attributes_with_confidence;

        DROP TABLE attributes_with_confidence;
        """
    )


def migrate_wine_attributes_to_flavour_wheel(conn: sqlite3.Connection) -> None:
    migration_key = "wine_attributes_flavour_wheel"
    applied = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE key = ?",
        (migration_key,),
    ).fetchone()
    if applied is not None:
        return

    from .schema import ATTRIBUTE_KEYS_BY_TYPE

    rows = conn.execute(
        """
        SELECT
          entity_id,
          MAX(value) AS value,
          MIN(lower_95) AS lower_95,
          MAX(upper_95) AS upper_95
        FROM attributes
        JOIN entities ON entities.id = attributes.entity_id
        WHERE entities.type = 'wine'
          AND attributes.key IN ('richness', 'intensity')
        GROUP BY entity_id
        """
    ).fetchall()
    for row in rows:
        entity_id = row["entity_id"] if isinstance(row, sqlite3.Row) else row[0]
        value = row["value"] if isinstance(row, sqlite3.Row) else row[1]
        lower_95 = row["lower_95"] if isinstance(row, sqlite3.Row) else row[2]
        upper_95 = row["upper_95"] if isinstance(row, sqlite3.Row) else row[3]
        conn.execute(
            """
            INSERT INTO attributes (entity_id, key, value, lower_95, upper_95)
            VALUES (?, 'body', ?, ?, ?)
            ON CONFLICT(entity_id, key) DO UPDATE
            SET value = CASE
                WHEN attributes.value > excluded.value THEN attributes.value
                ELSE excluded.value
              END,
              lower_95 = CASE
                WHEN attributes.lower_95 < excluded.lower_95 THEN attributes.lower_95
                ELSE excluded.lower_95
              END,
              upper_95 = CASE
                WHEN attributes.upper_95 > excluded.upper_95 THEN attributes.upper_95
                ELSE excluded.upper_95
              END
            """,
            (entity_id, value, lower_95, upper_95),
        )

    allowed_wine_attributes = set(ATTRIBUTE_KEYS_BY_TYPE["wine"])
    placeholders = ", ".join("?" for _ in allowed_wine_attributes)
    conn.execute(
        f"""
        DELETE FROM attributes
        WHERE entity_id IN (SELECT id FROM entities WHERE type = 'wine')
          AND key NOT IN ({placeholders})
        """,
        tuple(sorted(allowed_wine_attributes)),
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

        attribute_intervals = entity.get("attribute_intervals_95") or {}
        for key, value in (entity.get("attributes") or {}).items():
            interval = normalize_interval_95(
                attribute_value(value),
                attribute_intervals.get(key, attribute_interval_95(value)),
            )
            self.set_attribute(
                entity["id"],
                key,
                attribute_value(value),
                interval["lower"],
                interval["upper"],
            )

        for signal in entity.get("signals") or []:
            self.add_signal(
                entity["id"],
                signal["type"],
                signal["value"],
                signal.get("provenance"),
            )

        self.conn.commit()

    def set_attribute(
        self,
        entity_id: str,
        key: str,
        value: float,
        lower_95: float | None = None,
        upper_95: float | None = None,
    ) -> None:
        interval = normalize_interval_95(
            value,
            {
                "lower": value if lower_95 is None else lower_95,
                "upper": value if upper_95 is None else upper_95,
            },
        )
        self.conn.execute(
            """
            INSERT INTO attributes (entity_id, key, value, lower_95, upper_95)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(entity_id, key) DO UPDATE SET
              value = excluded.value,
              lower_95 = excluded.lower_95,
              upper_95 = excluded.upper_95
            """,
            (entity_id, key, clamp01(value), interval["lower"], interval["upper"]),
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
                "SELECT key, value, lower_95, upper_95 FROM attributes WHERE entity_id = ?",
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
            entity_dict["attribute_intervals_95"] = {
                row["key"]: {"lower": row["lower_95"], "upper": row["upper_95"]}
                for row in attrs
            }
            entity_dict["attribute_details"] = {
                row["key"]: {
                    "value": row["value"],
                    "interval_95": {
                        "lower": row["lower_95"],
                        "upper": row["upper_95"],
                    },
                }
                for row in attrs
            }
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
        match_details = []
        needs_confirmation = []

        for name in names:
            match = best_entity_name_match(name, all_entities)

            if match and match["confidence"] >= 0.5:
                matched.append(match["entity"])
                detail = {
                    "input": name,
                    "matched_id": match["entity"]["id"],
                    "matched_name": match["entity"]["canonical_name"],
                    "confidence": round(match["confidence"], 3),
                    "needs_confirmation": match["confidence"] < 0.85,
                }
                match_details.append(detail)
                if detail["needs_confirmation"]:
                    needs_confirmation.append(detail)
            else:
                unmatched.append(name)

        return {
            "matched": unique_by_id(matched),
            "unmatched": unmatched,
            "matches": unique_match_details(match_details),
            "needs_confirmation": unique_match_details(needs_confirmation),
        }

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

    def decision_feedback(
        self,
        query: str,
        candidate_ids: list[str],
        *,
        limit: int = 100,
    ) -> dict[str, dict[str, int]]:
        candidate_set = set(candidate_ids)
        feedback = {
            entity_id: {"chosen": 0, "rejected": 0}
            for entity_id in candidate_ids
        }
        if not candidate_set:
            return feedback

        rows = self.conn.execute(
            """
            SELECT query, ranked_json, chosen_entity_id
            FROM decisions
            WHERE chosen_entity_id IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        for row in rows:
            historical_query = row["query"] if isinstance(row, sqlite3.Row) else row[0]
            if not query_is_similar(query, historical_query):
                continue

            chosen_entity_id = (
                row["chosen_entity_id"] if isinstance(row, sqlite3.Row) else row[2]
            )
            if chosen_entity_id in candidate_set:
                feedback[chosen_entity_id]["chosen"] += 1

            ranked_json = row["ranked_json"] if isinstance(row, sqlite3.Row) else row[1]
            try:
                ranked = json.loads(ranked_json or "[]")
            except json.JSONDecodeError:
                ranked = []
            for item in ranked[:3]:
                entity_id = item.get("id") if isinstance(item, dict) else None
                if entity_id in candidate_set and entity_id != chosen_entity_id:
                    feedback[entity_id]["rejected"] += 1

        return feedback

    def log_application_event(
        self,
        *,
        tool_name: str,
        status: str,
        duration_ms: float,
        inputs: dict[str, Any],
        output: Any | None = None,
        error: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO application_events (
              tool_name,
              status,
              duration_ms,
              input_json,
              output_json,
              error_json,
              metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tool_name,
                status,
                float(duration_ms),
                json.dumps(inputs, sort_keys=True, default=str),
                json.dumps(output, sort_keys=True, default=str)
                if output is not None
                else None,
                json.dumps(error, sort_keys=True, default=str)
                if error is not None
                else None,
                json.dumps(metadata or {}, sort_keys=True, default=str),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def list_application_events(
        self,
        *,
        limit: int = 100,
        tool_name: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        params: list[Any] = []
        where = ""
        if tool_name:
            where = "WHERE tool_name = ?"
            params.append(tool_name)
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM application_events
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "tool_name": row["tool_name"],
                "status": row["status"],
                "duration_ms": row["duration_ms"],
                "input": parse_json_value(row["input_json"]),
                "output": parse_json_value(row["output_json"]),
                "error": parse_json_value(row["error_json"]),
                "metadata": parse_metadata(row["metadata_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def best_entity_name_match(
    name: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for candidate in candidates:
        confidence = name_match_confidence(name, candidate["canonical_name"])
        if best is None or confidence > best["confidence"]:
            best = {"entity": candidate, "confidence": confidence}
    return best


def name_match_confidence(left: str, right: str) -> float:
    left_norm = normalize_name_for_match(left)
    right_norm = normalize_name_for_match(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        return 1.0

    left_tokens = left_norm.split()
    right_tokens = right_norm.split()
    overlap_tokens = set(left_tokens) & set(right_tokens)
    token_score = token_overlap_score(left_tokens, right_tokens)
    sequence_score = SequenceMatcher(None, left_norm, right_norm).ratio()
    if overlap_tokens and overlap_tokens <= GENERIC_WINE_NAME_TOKENS:
        return min(max(token_score, sequence_score), 0.49)
    return max(token_score, sequence_score)


def normalize_name_for_match(value: str) -> str:
    tokens = [
        normalize_wine_token(token)
        for token in normalize(value).split()
        if token not in NAME_MATCH_STOP_WORDS and not is_vintage_token(token)
    ]
    return " ".join(token for token in tokens if token)


def normalize_wine_token(token: str) -> str:
    aliases = {
        "cab": "cabernet",
        "cabs": "cabernet",
        "sauv": "sauvignon",
        "sauvignon": "sauvignon",
        "syra": "syrah",
        "est": "estate",
        "ch": "chateau",
    }
    return aliases.get(token, token)


def is_vintage_token(token: str) -> bool:
    return bool(re.fullmatch(r"(19|20)\d{2}", token))


def token_overlap_score(left_tokens: list[str], right_tokens: list[str]) -> float:
    left = set(left_tokens)
    right = set(right_tokens)
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    precision = overlap / len(left)
    recall = overlap / len(right)
    if precision == 0 or recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def unique_match_details(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    unique = []
    for match in matches:
        key = (match["input"], match["matched_id"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(match)
    return unique


NAME_MATCH_STOP_WORDS = {
    "the",
    "a",
    "an",
    "and",
    "of",
    "de",
    "di",
    "da",
    "la",
    "le",
    "il",
    "lo",
    "s",
}


GENERIC_WINE_NAME_TOKENS = {
    "barolo",
    "cabernet",
    "chardonnay",
    "grenache",
    "malbec",
    "merlot",
    "nebbiolo",
    "pinot",
    "riesling",
    "sangiovese",
    "sauvignon",
    "syrah",
    "tempranillo",
    "zinfandel",
}


def query_is_similar(current: str, historical: str) -> bool:
    current_tokens = query_tokens(current)
    historical_tokens = query_tokens(historical)
    if not current_tokens or not historical_tokens:
        return True
    return bool(current_tokens & historical_tokens)


def query_tokens(value: str) -> set[str]:
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "what",
        "which",
        "thing",
        "things",
        "place",
        "places",
        "something",
    }
    return {
        token
        for token in normalize(value).split()
        if len(token) > 2 and token not in stop_words
    }


def clamp01(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))


def attribute_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("value", 0)
    return value


def attribute_interval_95(value: Any) -> dict[str, float]:
    if isinstance(value, dict):
        if isinstance(value.get("interval_95"), dict):
            return normalize_interval_95(attribute_value(value), value["interval_95"])
        if "lower_95" in value and "upper_95" in value:
            return normalize_interval_95(
                attribute_value(value),
                {"lower": value["lower_95"], "upper": value["upper_95"]},
            )
        if "confidence" in value or "confidence_percent" in value:
            confidence = value.get("confidence", value.get("confidence_percent"))
            return interval_from_legacy_confidence(attribute_value(value), confidence)
    point = clamp01(attribute_value(value))
    return {"lower": point, "upper": point}


def interval_from_legacy_confidence(value: Any, confidence: Any) -> dict[str, float]:
    point = clamp01(value)
    confidence = max(0.0, min(100.0, float(confidence)))
    radius = (100.0 - confidence) / 100.0
    return {
        "lower": max(0.0, point - radius),
        "upper": min(1.0, point + radius),
    }


def normalize_interval_95(
    value: Any,
    interval: dict[str, Any] | None,
) -> dict[str, float]:
    point = clamp01(value)
    if not isinstance(interval, dict):
        return {"lower": point, "upper": point}
    lower = clamp01(interval.get("lower", interval.get("lower_95", point)))
    upper = clamp01(interval.get("upper", interval.get("upper_95", point)))
    if lower > upper:
        lower, upper = upper, lower
    return {
        "lower": min(lower, point),
        "upper": max(upper, point),
    }


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


def parse_json_value(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return None


def unique_by_id(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    unique = []
    for entity in entities:
        if entity["id"] in seen:
            continue
        seen.add(entity["id"])
        unique.append(entity)
    return unique
