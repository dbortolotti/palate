from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from palate.storage import open_store


class StorageBehaviorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="palate-storage-"))
        self.db_path = self.temp_dir / "test.sqlite"
        self.store = open_store(str(self.db_path))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_attribute_values_are_clamped_to_zero_one_range(self) -> None:
        self.store.upsert_entity(
            {
                "id": "wine_bounds",
                "type": "wine",
                "canonical_name": "Bounds Wine",
                "attributes": {
                    "oak": {
                        "value": 1.5,
                        "interval_95": {"lower": 0.7, "upper": 1.2},
                    },
                    "quiet": {
                        "value": -0.25,
                        "interval_95": {"lower": -0.5, "upper": 0.4},
                    },
                },
            }
        )

        entity = self.store.list_entities()[0]
        self.assertEqual(entity["attributes"]["oak"], 1.0)
        self.assertEqual(entity["attributes"]["quiet"], 0.0)
        self.assertEqual(
            entity["attribute_intervals_95"]["oak"],
            {"lower": 0.7, "upper": 1.0},
        )
        self.assertEqual(
            entity["attribute_intervals_95"]["quiet"],
            {"lower": 0.0, "upper": 0.4},
        )
        self.assertEqual(
            entity["attribute_details"]["oak"],
            {"value": 1.0, "interval_95": {"lower": 0.7, "upper": 1.0}},
        )

    def test_name_matching_handles_case_and_punctuation(self) -> None:
        self.store.upsert_entity(
            {
                "id": "duck_waffle",
                "type": "restaurant",
                "canonical_name": "Duck & Waffle",
            }
        )

        matched = self.store.match_entities_by_names(["duck waffle"])
        self.assertEqual([entity["id"] for entity in matched["matched"]], ["duck_waffle"])
        self.assertEqual(matched["unmatched"], [])

    def test_name_matching_deduplicates_repeated_options(self) -> None:
        self.store.upsert_entity(
            {
                "id": "wine_repeat",
                "type": "wine",
                "canonical_name": "Repeat Wine",
            }
        )

        matched = self.store.match_entities_by_names(["Repeat Wine", "repeat wine"])
        self.assertEqual([entity["id"] for entity in matched["matched"]], ["wine_repeat"])

    def test_migration_converts_attribute_confidence_to_interval_and_removes_column(self) -> None:
        raw_db_path = self.temp_dir / "raw_attribute_confidence.sqlite"
        conn = sqlite3.connect(raw_db_path)
        conn.executescript(
            """
            CREATE TABLE entities (
              id TEXT PRIMARY KEY,
              type TEXT NOT NULL,
              canonical_name TEXT NOT NULL,
              source_text TEXT,
              notes TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE attributes (
              entity_id TEXT NOT NULL,
              key TEXT NOT NULL,
              value REAL NOT NULL CHECK (value >= 0 AND value <= 1),
              confidence REAL NOT NULL DEFAULT 100 CHECK (confidence >= 0 AND confidence <= 100),
              PRIMARY KEY (entity_id, key)
            );

            INSERT INTO entities (id, type, canonical_name)
            VALUES ('wine_confidence', 'wine', 'Confidence Wine');

            INSERT INTO attributes (entity_id, key, value, confidence)
            VALUES ('wine_confidence', 'oak', 0.70, 80);
            """
        )
        conn.commit()
        conn.close()

        reopened = open_store(str(raw_db_path))
        wine = reopened.list_entities()[0]
        columns = {
            row["name"]
            for row in reopened.conn.execute("PRAGMA table_info(attributes)").fetchall()
        }

        self.assertAlmostEqual(wine["attribute_intervals_95"]["oak"]["lower"], 0.5)
        self.assertAlmostEqual(wine["attribute_intervals_95"]["oak"]["upper"], 0.9)
        self.assertNotIn("confidence", columns)

    def test_migration_removes_duplicate_signals_from_existing_database(self) -> None:
        raw_db_path = self.temp_dir / "raw_duplicates.sqlite"
        conn = sqlite3.connect(raw_db_path)
        conn.executescript(
            """
            CREATE TABLE entities (
              id TEXT PRIMARY KEY,
              type TEXT NOT NULL,
              canonical_name TEXT NOT NULL,
              source_text TEXT,
              notes TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE signals (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              entity_id TEXT NOT NULL,
              type TEXT NOT NULL,
              value TEXT NOT NULL,
              provenance TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO entities (id, type, canonical_name)
            VALUES ('wine_dup', 'wine', 'Duplicate Wine');

            INSERT INTO signals (entity_id, type, value, provenance)
            VALUES
              ('wine_dup', 'rating', '4', NULL),
              ('wine_dup', 'rating', '4', NULL),
              ('wine_dup', 'recommended_by', 'Mike', NULL),
              ('wine_dup', 'recommended_by', 'Mike', NULL);
            """
        )
        conn.commit()
        conn.close()

        reopened = open_store(str(raw_db_path))
        wine = reopened.list_entities()[0]

        self.assertEqual(len(wine["signals"]), 2)
        signals_by_type = {signal["type"]: signal["value"] for signal in wine["signals"]}
        self.assertEqual(signals_by_type["rating"], "8")

    def test_migration_converts_existing_rating_signals_to_ten_point_scale_once(self) -> None:
        raw_db_path = self.temp_dir / "raw_rating_scale.sqlite"
        conn = sqlite3.connect(raw_db_path)
        conn.executescript(
            """
            CREATE TABLE entities (
              id TEXT PRIMARY KEY,
              type TEXT NOT NULL,
              canonical_name TEXT NOT NULL,
              source_text TEXT,
              notes TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE signals (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              entity_id TEXT NOT NULL,
              type TEXT NOT NULL,
              value TEXT NOT NULL,
              provenance TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO entities (id, type, canonical_name)
            VALUES ('wine_old_rating', 'wine', 'Old Rating Wine');

            INSERT INTO signals (entity_id, type, value, provenance)
            VALUES
              ('wine_old_rating', 'rating', '4.5', NULL),
              ('wine_old_rating', 'recommended_by', 'Mike', NULL);
            """
        )
        conn.commit()
        conn.close()

        reopened = open_store(str(raw_db_path))
        reopened = open_store(str(raw_db_path))
        wine = reopened.list_entities()[0]
        ratings = [
            signal["value"]
            for signal in wine["signals"]
            if signal["type"] == "rating"
        ]

        self.assertEqual(ratings, ["9"])

    def test_migration_replaces_old_wine_attributes_with_body_and_flavour_wheel(self) -> None:
        raw_db_path = self.temp_dir / "raw_wine_attributes.sqlite"
        conn = sqlite3.connect(raw_db_path)
        conn.executescript(
            """
            CREATE TABLE entities (
              id TEXT PRIMARY KEY,
              type TEXT NOT NULL,
              canonical_name TEXT NOT NULL,
              source_text TEXT,
              notes TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE attributes (
              entity_id TEXT NOT NULL,
              key TEXT NOT NULL,
              value REAL NOT NULL CHECK (value >= 0 AND value <= 1),
              PRIMARY KEY (entity_id, key)
            );

            INSERT INTO entities (id, type, canonical_name)
            VALUES ('wine_old_attrs', 'wine', 'Old Attribute Wine');

            INSERT INTO attributes (entity_id, key, value)
            VALUES
              ('wine_old_attrs', 'richness', 0.72),
              ('wine_old_attrs', 'intensity', 0.84),
              ('wine_old_attrs', 'comfort', 0.30),
              ('wine_old_attrs', 'premium', 0.90),
              ('wine_old_attrs', 'fruity', 0.55);
            """
        )
        conn.commit()
        conn.close()

        reopened = open_store(str(raw_db_path))
        wine = reopened.list_entities()[0]

        self.assertAlmostEqual(wine["attributes"]["body"], 0.84)
        self.assertAlmostEqual(wine["attributes"]["premium"], 0.9)
        self.assertAlmostEqual(wine["attributes"]["fruity"], 0.55)
        self.assertEqual(
            wine["attribute_intervals_95"]["body"],
            {"lower": 0.72, "upper": 0.84},
        )
        self.assertNotIn("richness", wine["attributes"])
        self.assertNotIn("intensity", wine["attributes"])
        self.assertNotIn("comfort", wine["attributes"])

    def test_migration_adds_empty_metadata_to_existing_database(self) -> None:
        raw_db_path = self.temp_dir / "raw_metadata.sqlite"
        conn = sqlite3.connect(raw_db_path)
        conn.executescript(
            """
            CREATE TABLE entities (
              id TEXT PRIMARY KEY,
              type TEXT NOT NULL,
              canonical_name TEXT NOT NULL,
              source_text TEXT,
              notes TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO entities (id, type, canonical_name)
            VALUES ('movie_old', 'movie', 'Old Movie');
            """
        )
        conn.commit()
        conn.close()

        reopened = open_store(str(raw_db_path))
        movie = reopened.list_entities()[0]

        self.assertEqual(movie["metadata"], {})
        self.assertEqual(movie["metadata_json"], "{}")

    def test_upsert_entity_stores_and_returns_parsed_metadata(self) -> None:
        self.store.upsert_entity(
            {
                "id": "movie_meta",
                "type": "movie",
                "canonical_name": "Metadata Movie",
                "metadata": {
                    "director": "Jane Director",
                    "external_ids": {"imdb_id": "tt1234567"},
                },
            }
        )

        movie = self.store.list_entities()[0]

        self.assertEqual(movie["metadata"]["director"], "Jane Director")
        self.assertEqual(movie["metadata"]["external_ids"]["imdb_id"], "tt1234567")

    def test_delete_entity_removes_entity_attributes_and_signals(self) -> None:
        self.store.upsert_entity(
            {
                "id": "wine_delete",
                "type": "wine",
                "canonical_name": "Delete Wine",
                "attributes": {"oak": 0.8},
                "signals": [{"type": "rating", "value": 8}],
            }
        )

        deleted = self.store.delete_entity("wine_delete")
        attribute_rows = self.store.conn.execute(
            "SELECT COUNT(*) AS count FROM attributes WHERE entity_id = ?",
            ("wine_delete",),
        ).fetchone()
        signal_rows = self.store.conn.execute(
            "SELECT COUNT(*) AS count FROM signals WHERE entity_id = ?",
            ("wine_delete",),
        ).fetchone()

        self.assertIsNotNone(deleted)
        self.assertEqual(deleted["canonical_name"], "Delete Wine")
        self.assertEqual(self.store.list_entities(), [])
        self.assertEqual(attribute_rows["count"], 0)
        self.assertEqual(signal_rows["count"], 0)

    def test_delete_entity_returns_none_for_missing_id(self) -> None:
        self.assertIsNone(self.store.delete_entity("missing"))

    def test_decision_rows_preserve_serialized_payloads(self) -> None:
        decision_id = self.store.log_decision(
            query="query",
            context={"mood": "quiet"},
            options=[{"canonical_name": "A"}],
            ranked=[{"id": "wine_a", "score": 1.2}],
        )

        row = self.store.conn.execute(
            "SELECT context_json, options_json, ranked_json FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()
        self.assertEqual(row["context_json"], '{"mood": "quiet"}')
        self.assertEqual(row["options_json"], '[{"canonical_name": "A"}]')
        self.assertEqual(row["ranked_json"], '[{"id": "wine_a", "score": 1.2}]')
