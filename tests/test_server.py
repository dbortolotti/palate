from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import palate.server as server
from palate.storage import open_store


class ServerToolBehaviorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="palate-server-"))
        self.store = open_store(str(self.temp_dir / "test.sqlite"))
        seed_server_store(self.store)
        self.store_patch = patch.object(server, "store", self.store)
        self.store_patch.start()

    def tearDown(self) -> None:
        self.store_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_query_without_options_ranks_and_logs_without_explanation_call(self) -> None:
        with patch.object(server, "parse_intent", return_value=base_intent(entity_type="wine", attributes=["oak"])) as parse, \
             patch.object(server, "explain_results", side_effect=AssertionError("should not explain")):
            result = server.palate_query("oaky wine", explain=False)

        parse.assert_called_once()
        self.assertIsInstance(result["decision_id"], int)
        self.assertIsNone(result["explanation"])
        self.assertEqual(result["ranked_results"][0]["id"], "wine_mike")
        self.assertFalse(result["retrieval"]["constrained_to_options"])

    def test_backup_now_returns_snapshot_paths(self) -> None:
        with patch.object(server, "backup_once", return_value={"sqlite": "a.sqlite", "json": "a.json", "removed": []}):
            result = server.palate_backup_now()

        self.assertEqual(result["sqlite"], "a.sqlite")
        self.assertEqual(result["json"], "a.json")

    def test_evaluate_options_reports_unmatched_without_substituting_memory(self) -> None:
        with patch.object(server, "parse_intent", return_value=base_intent(entity_type="wine")), \
             patch.object(server, "extract_entities", return_value={
                 "entities": [{"canonical_name": "Unknown Cellar Cabernet", "type": "wine", "source_text": "Unknown Cellar Cabernet"}]
             }), \
             patch.object(server, "explain_results", return_value="No known matches."):
            result = server.palate_evaluate_options("which wine", "Unknown Cellar Cabernet")

        self.assertTrue(result["retrieval"]["constrained_to_options"])
        self.assertEqual(result["retrieval"]["candidate_count"], 0)
        self.assertEqual(result["retrieval"]["unmatched_options"], ["Unknown Cellar Cabernet"])
        self.assertEqual(result["ranked_results"], [])

    def test_evaluate_options_ranks_only_matched_options(self) -> None:
        with patch.object(server, "parse_intent", return_value=base_intent(entity_type="wine")), \
             patch.object(server, "extract_entities", return_value={
                 "entities": [
                     {"canonical_name": "Mike's Cabernet", "type": "wine", "source_text": "Mike's Cabernet"},
                     {"canonical_name": "Unknown Cellar Cabernet", "type": "wine", "source_text": "Unknown Cellar Cabernet"},
                 ]
             }), \
             patch.object(server, "explain_results", return_value="Mike's Cabernet wins."):
            result = server.palate_evaluate_options("which wine", "Mike's Cabernet\nUnknown Cellar Cabernet")

        self.assertEqual(result["ranked_results"][0]["id"], "wine_mike")
        self.assertEqual(result["retrieval"]["unmatched_options"], ["Unknown Cellar Cabernet"])

    def test_recall_uses_parsed_search_text(self) -> None:
        with patch.object(server, "parse_intent", return_value=base_intent(entity_type="restaurant", search_text="place with a view")):
            result = server.palate_recall("that place with a view")

        self.assertEqual(result["results"][0]["id"], "restaurant_view")
        self.assertEqual(result["retrieval"]["candidate_count"], 1)

    def test_remember_merges_enrichment_and_manual_attributes(self) -> None:
        with patch.object(
            server,
            "normalize_enrichment",
            return_value={"attributes": {"oak": 0.2, "premium": 0.4}, "notes": "normalized"},
        ):
            result = server.palate_remember(
                id="wine_new",
                type="wine",
                canonical_name="New Wine",
                description="rich and oaky",
                attributes={"oak": 0.9},
                rating=5,
                recommended_by="Sam",
            )

        stored = next(entity for entity in self.store.list_entities() if entity["id"] == "wine_new")
        self.assertTrue(result["stored"])
        self.assertEqual(stored["attributes"]["oak"], 0.9)
        self.assertEqual(stored["attributes"]["premium"], 0.4)
        self.assertEqual({signal["type"] for signal in stored["signals"]}, {"rating", "recommended_by"})

    def test_remember_rejects_unknown_entity_type(self) -> None:
        with self.assertRaises(ValueError):
            server.palate_remember(
                id="bad",
                type="book",
                canonical_name="Bad Type",
            )

    def test_log_decision_updates_existing_decision(self) -> None:
        decision_id = self.store.log_decision("which wine", {}, [], [])

        result = server.palate_log_decision("wine_mike", decision_id=decision_id)

        self.assertTrue(result["logged"])
        self.assertTrue(result["updated_existing_decision"])
        self.assertEqual(result["decision_id"], decision_id)
        row = self.store.conn.execute(
            "SELECT chosen_entity_id FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()
        self.assertEqual(row["chosen_entity_id"], "wine_mike")

    def test_log_decision_reports_missing_decision(self) -> None:
        result = server.palate_log_decision("wine_mike", decision_id=999999)

        self.assertFalse(result["logged"])
        self.assertIn("No decision found", result["error"])

    def test_enrich_item_rejects_unknown_entity_type_before_llm_call(self) -> None:
        with patch.object(server, "normalize_enrichment", side_effect=AssertionError("should not call")):
            with self.assertRaises(ValueError):
                server.palate_enrich_item("text", "book")


def seed_server_store(store) -> None:
    store.upsert_entity(
        {
            "id": "wine_mike",
            "type": "wine",
            "canonical_name": "Mike's Cabernet",
            "notes": "Cedar, oak, and premium structure.",
            "attributes": {"oak": 0.8, "premium": 0.7},
            "signals": [
                {"type": "rating", "value": 4},
                {"type": "recommended_by", "value": "Mike"},
            ],
        }
    )
    store.upsert_entity(
        {
            "id": "restaurant_view",
            "type": "restaurant",
            "canonical_name": "Skyline Room",
            "notes": "Quiet place with a city view.",
            "attributes": {"view": 0.95, "quiet": 0.6},
            "signals": [{"type": "rating", "value": 4}],
        }
    )


def base_intent(**overrides):
    intent = {
        "intent": "contextual_decision",
        "attributes": [],
        "context": {},
        "filters": {"min_rating": None, "recommended_by": None},
        "entity_type": None,
        "search_text": "",
    }
    intent.update(overrides)
    return intent
