from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import palate.server as server
from palate.storage import open_store


class ScriptedPalateClient:
    """Deterministic stand-in for the client LLM routing described in USER-GUIDE."""

    def respond(self, prompt: str) -> dict:
        normalized = " ".join(prompt.lower().split())
        if "tell me about" in normalized and "don't save" in normalized:
            return server.palate_describe_item(
                item_text="Twist Connubio, Marylebone, London",
                entity_type="restaurant",
            )
        if "remember" in normalized and "suggested by robert" in normalized:
            return server.palate_remember(
                id="restaurant_twist_connubio_marylebone_london",
                type="restaurant",
                canonical_name="Twist Connubio, Marylebone, London",
                description="Twist Connubio, Marylebone, London",
                recommended_by="Robert",
            )
        if "delete" in normalized:
            return server.palate_delete_record(prompt.rsplit(" ", 1)[-1].strip("."))
        raise AssertionError(f"No scripted route for prompt: {prompt}")


class UserGuideFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="palate-guide-flow-"))
        self.store = open_store(str(self.temp_dir / "test.sqlite"))
        seed_server_store(self.store)
        self.store_patch = patch.object(server, "store", self.store)
        self.store_patch.start()
        self.client = ScriptedPalateClient()

    def tearDown(self) -> None:
        self.store_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_tell_me_about_but_do_not_save_uses_describe_item_contract(self) -> None:
        before_ids = {entity["id"] for entity in self.store.list_entities()}

        with patch.object(
            server,
            "normalize_restaurant_enrichment",
            return_value={
                "attributes": {
                    "premium": {
                        "value": 0.72,
                        "interval_95": {"lower": 0.58, "upper": 0.86},
                        "interval_1sigma": {"lower": 0.64, "upper": 0.8},
                    },
                    "indulgent": {
                        "value": 0.79,
                        "interval_95": {"lower": 0.64, "upper": 0.92},
                        "interval_1sigma": {"lower": 0.69, "upper": 0.87},
                    },
                },
                "notes": "Spanish and Italian influenced restaurant in Marylebone.",
                "metadata": {
                    "cuisine": {
                        "spanish": {
                            "value": 0.78,
                            "interval_95": {"lower": 0.63, "upper": 0.9},
                        },
                        "modern_european": {
                            "value": 0.86,
                            "interval_95": {"lower": 0.74, "upper": 0.94},
                        },
                    }
                },
                "sources": [{"url": "https://twistconnubio.com/menu/"}],
            },
        ) as enrich:
            result = self.client.respond(
                "Use Palate to tell me about Twist Connubio in Marylebone, "
                "but don't save it."
            )

        after_ids = {entity["id"] for entity in self.store.list_entities()}
        self.assertEqual(after_ids, before_ids)
        enrich.assert_called_once_with("Twist Connubio, Marylebone, London")
        self.assertFalse(result["stored"])
        self.assertEqual(result["source"], "enrichment")
        self.assertFalse(result["found_existing"])
        self.assertEqual(result["suggested_remember"]["tool"], "palate_remember")
        self.assertEqual(
            result["normalized_attribute_intervals_1sigma"]["premium"],
            {"lower": 0.64, "upper": 0.8},
        )
        self.assertEqual(result["sources"], [{"url": "https://twistconnubio.com/menu/"}])

    def test_remember_suggested_by_records_recommender_signal(self) -> None:
        with patch.object(
            server,
            "normalize_restaurant_enrichment",
            return_value={
                "attributes": {
                    "premium": {
                        "value": 0.72,
                        "interval_95": {"lower": 0.58, "upper": 0.86},
                        "interval_1sigma": {"lower": 0.64, "upper": 0.8},
                    }
                },
                "notes": "Spanish and Italian influenced restaurant in Marylebone.",
                "metadata": {"cuisine": ["Spanish", "Italian"]},
            },
        ):
            result = self.client.respond(
                "Use Palate to remember Twist Connubio in Marylebone as suggested by Robert."
            )

        stored = next(
            entity
            for entity in self.store.list_entities()
            if entity["id"] == "restaurant_twist_connubio_marylebone_london"
        )
        self.assertTrue(result["stored"])
        self.assertEqual(
            {signal["type"]: signal["value"] for signal in stored["signals"]},
            {"recommended_by": "Robert"},
        )
        self.assertEqual(stored["metadata"]["cuisine"]["spanish"]["value"], 1.0)

    def test_delete_fuzzy_prompt_returns_candidates_instead_of_deleting(self) -> None:
        result = self.client.respond("Use Palate to delete Mike.")

        self.assertFalse(result["deleted"])
        self.assertEqual(result["needs_confirmation"][0]["matched_id"], "wine_mike")
        self.assertIn("choose one by id", result["ask_user"])
        self.assertIn(
            "wine_mike",
            {entity["id"] for entity in self.store.list_entities()},
        )

    def test_delete_exact_id_prompt_deletes_record(self) -> None:
        result = self.client.respond("Use Palate to delete wine_mike.")

        self.assertTrue(result["deleted"])
        self.assertEqual(result["record"]["id"], "wine_mike")
        self.assertNotIn(
            "wine_mike",
            {entity["id"] for entity in self.store.list_entities()},
        )


def seed_server_store(store) -> None:
    store.upsert_entity(
        {
            "id": "wine_mike",
            "type": "wine",
            "canonical_name": "Mike's Cabernet",
            "notes": "Cedar, oak, and premium structure.",
            "attributes": {"oak": 0.8, "premium": 0.7},
            "signals": [{"type": "recommended_by", "value": "Mike"}],
        }
    )
