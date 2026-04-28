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

    def test_option_set_retrieval_keeps_matched_and_unmatched_separate(self) -> None:
        intent = base_intent(entity_type="wine", attributes=["oak"])
        retrieval = retrieve_candidates(
            self.store,
            intent,
            [
                {"canonical_name": "Mike's Cabernet", "type": "wine"},
                {"canonical_name": "Unknown Cellar Cabernet", "type": "wine"},
            ],
        )

        self.assertTrue(retrieval["constrained_to_options"])
        self.assertEqual([entity["id"] for entity in retrieval["candidates"]], ["wine_mike"])
        self.assertEqual(retrieval["unmatched_options"], ["Unknown Cellar Cabernet"])

    def test_option_set_retrieval_respects_inferred_entity_type(self) -> None:
        intent = base_intent(entity_type="wine")
        retrieval = retrieve_candidates(
            self.store,
            intent,
            [{"canonical_name": "Skyline Room", "type": "restaurant"}],
        )

        self.assertTrue(retrieval["constrained_to_options"])
        self.assertEqual(retrieval["candidates"], [])

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

    def test_min_rating_filter_excludes_low_rated_items(self) -> None:
        intent = base_intent(
            entity_type="restaurant",
            filters={"min_rating": 5, "recommended_by": None},
        )
        retrieval = retrieve_candidates(self.store, intent)
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertEqual([result["id"] for result in ranked], ["restaurant_loud"])

    def test_search_text_narrows_fuzzy_recall_candidates(self) -> None:
        intent = base_intent(
            entity_type="restaurant",
            search_text="that place with a view",
        )
        retrieval = retrieve_candidates(self.store, intent)
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertEqual([result["id"] for result in ranked], ["restaurant_view"])

    def test_search_text_falls_back_to_typed_candidates_when_no_text_matches(self) -> None:
        intent = base_intent(entity_type="restaurant", search_text="volcanic lighthouse")
        retrieval = retrieve_candidates(self.store, intent)

        self.assertEqual(
            {entity["id"] for entity in retrieval["candidates"]},
            {"restaurant_view", "restaurant_loud"},
        )

    def test_context_match_can_lift_contextually_relevant_item(self) -> None:
        self.store.upsert_entity(
            {
                "id": "restaurant_context_view",
                "type": "restaurant",
                "canonical_name": "Context View",
                "attributes": {"view": 0.9},
                "signals": [{"type": "rating", "value": 4}],
            }
        )
        self.store.upsert_entity(
            {
                "id": "restaurant_context_plain",
                "type": "restaurant",
                "canonical_name": "Context Plain",
                "attributes": {"quiet": 0.9},
                "signals": [{"type": "rating", "value": 4}],
            }
        )
        intent = base_intent(entity_type="restaurant", context={"view": True})
        retrieval = retrieve_candidates(
            self.store,
            intent,
            [
                {"canonical_name": "Context View", "type": "restaurant"},
                {"canonical_name": "Context Plain", "type": "restaurant"},
            ],
        )
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertEqual(ranked[0]["id"], "restaurant_context_view")
        self.assertIn("context view: 0.90", ranked[0]["matched_attributes"])

    def test_attribute_matching_is_reflected_in_grounding(self) -> None:
        intent = base_intent(entity_type="wine", attributes=["oak", "premium"])
        retrieval = retrieve_candidates(self.store, intent)
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertEqual(ranked[0]["id"], "wine_mike")
        self.assertIn("oak: 0.80", ranked[0]["matched_attributes"])
        self.assertIn("premium: 0.70", ranked[0]["matched_attributes"])

    def test_dislike_signal_penalizes_but_does_not_hide_item(self) -> None:
        self.store.add_signal("wine_alex", "dislike", "too heavy")
        intent = base_intent(entity_type="wine")
        retrieval = retrieve_candidates(self.store, intent)
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertEqual(ranked[-1]["id"], "wine_alex")
        self.assertIn("too heavy", ranked[-1]["negative_signals"])

    def test_grounding_is_capped_at_five_results(self) -> None:
        for index in range(10):
            self.store.upsert_entity(
                {
                    "id": f"wine_extra_{index}",
                    "type": "wine",
                    "canonical_name": f"Extra Wine {index}",
                    "attributes": {"oak": 0.5},
                    "signals": [{"type": "rating", "value": 4}],
                }
            )

        intent = base_intent(entity_type="wine")
        retrieval = retrieve_candidates(self.store, intent)
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertEqual(len(ranked), 5)

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
