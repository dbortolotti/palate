from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from palate.core import build_grounding, rank_candidates, retrieve_candidates
from palate.storage import open_store


class CoreBehaviorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="palate-"))
        self.store = open_store(str(self.temp_dir / "test.sqlite"))
        seed_store(self.store)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_option_set_retrieval_stays_constrained_to_provided_options(self) -> None:
        intent = base_intent(entity_type="wine", attributes=["oak"])
        retrieval = retrieve_candidates(
            self.store,
            intent,
            [{"canonical_name": "Unknown Cellar Cabernet", "type": "wine"}],
        )

        self.assertTrue(retrieval["constrained_to_options"])
        self.assertEqual(retrieval["unmatched_options"], ["Unknown Cellar Cabernet"])
        self.assertEqual(len(retrieval["candidates"]), 0)

    def test_upserted_signals_are_idempotent(self) -> None:
        seed_store(self.store)

        wine = next(
            entity
            for entity in self.store.list_entities()
            if entity["id"] == "wine_mike"
        )
        self.assertEqual(len(wine["signals"]), 2)

    def test_recommended_by_filters_rankings_to_requested_person(self) -> None:
        intent = base_intent(
            entity_type="wine",
            filters={"min_rating": None, "recommended_by": "Mike"},
        )
        retrieval = retrieve_candidates(self.store, intent)
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertEqual([result["id"] for result in ranked], ["wine_mike"])

    def test_search_text_narrows_fuzzy_recall_candidates(self) -> None:
        intent = base_intent(
            entity_type="restaurant",
            search_text="that place with a view",
        )
        retrieval = retrieve_candidates(self.store, intent)
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertEqual([result["id"] for result in ranked], ["restaurant_view"])

    def test_decision_choices_update_existing_decision_rows(self) -> None:
        decision_id = self.store.log_decision(
            query="which wine",
            context={},
            options=[],
            ranked=[],
        )

        self.assertEqual(self.store.update_decision_choice(decision_id, "wine_mike"), 1)
        self.assertEqual(self.store.update_decision_choice(999999, "wine_mike"), 0)


def seed_store(store) -> None:
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
            "id": "wine_alex",
            "type": "wine",
            "canonical_name": "Alex's Syrah",
            "notes": "Rich and intense.",
            "attributes": {"richness": 0.85, "intensity": 0.8},
            "signals": [
                {"type": "rating", "value": 5},
                {"type": "recommended_by", "value": "Alex"},
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
    store.upsert_entity(
        {
            "id": "restaurant_loud",
            "type": "restaurant",
            "canonical_name": "Loud Counter",
            "notes": "Lively casual dinner.",
            "attributes": {"lively": 0.9, "casual": 0.7},
            "signals": [{"type": "rating", "value": 5}],
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


if __name__ == "__main__":
    unittest.main()
