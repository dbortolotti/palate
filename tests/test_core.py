from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from palate.core import (
    RankingWeights,
    build_grounding,
    rank_candidates,
    retrieve_candidates,
    score_entity,
    score_text_match,
)
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
        self.assertEqual(retrieval["option_matches"][0]["matched_id"], "wine_mike")
        self.assertEqual(retrieval["needs_confirmation"], [])

    def test_option_set_retrieval_surfaces_uncertain_fuzzy_matches(self) -> None:
        intent = base_intent(entity_type="wine")
        retrieval = retrieve_candidates(
            self.store,
            intent,
            [{"canonical_name": "Mike Syrah", "type": "wine"}],
        )

        self.assertEqual([entity["id"] for entity in retrieval["candidates"]], ["wine_mike"])
        self.assertEqual(retrieval["needs_confirmation"][0]["matched_id"], "wine_mike")
        self.assertLess(retrieval["needs_confirmation"][0]["confidence"], 0.85)

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

    def test_recommended_by_boosts_matching_person_without_hard_excluding(self) -> None:
        intent = base_intent(
            entity_type="wine",
            filters={"min_rating": None, "recommended_by": "Mike"},
        )
        retrieval = retrieve_candidates(self.store, intent)
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertEqual([result["id"] for result in ranked], ["wine_mike", "wine_alex"])
        self.assertIn("not recommended by Mike", ranked[1]["negative_signals"])

    def test_min_rating_filter_excludes_low_rated_items(self) -> None:
        intent = base_intent(
            entity_type="restaurant",
            filters={"min_rating": 10, "recommended_by": None},
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

    def test_search_text_matches_media_metadata(self) -> None:
        self.store.upsert_entity(
            {
                "id": "movie_inception",
                "type": "movie",
                "canonical_name": "Inception",
                "metadata": {
                    "synopsis": "A thief enters dreams to plant an idea.",
                    "main_actors": ["Leonardo DiCaprio"],
                    "director": "Christopher Nolan",
                    "country": ["United States"],
                    "genre": ["Sci-Fi", "Thriller"],
                    "external_ids": {"imdb_id": "tt1375666"},
                },
            }
        )

        intent = base_intent(entity_type="movie", search_text="Nolan dream tt1375666")
        retrieval = retrieve_candidates(self.store, intent)

        self.assertEqual([entity["id"] for entity in retrieval["candidates"]], ["movie_inception"])

    def test_search_text_matches_music_metadata(self) -> None:
        self.store.upsert_entity(
            {
                "id": "music_kind_of_blue",
                "type": "music",
                "canonical_name": "Kind of Blue",
                "metadata": {
                    "artist": "Miles Davis",
                    "album": "Kind of Blue",
                    "personnel": ["John Coltrane", "Bill Evans"],
                    "genre": ["Jazz", "Modal Jazz"],
                },
            }
        )

        intent = base_intent(entity_type="music", search_text="Coltrane modal")
        retrieval = retrieve_candidates(self.store, intent)

        self.assertEqual(
            [entity["id"] for entity in retrieval["candidates"]],
            ["music_kind_of_blue"],
        )

    def test_external_ratings_are_grounding_facts(self) -> None:
        self.store.upsert_entity(
            {
                "id": "movie_grounding",
                "type": "movie",
                "canonical_name": "Grounding Movie",
                "metadata": {
                    "external_ratings": {
                        "imdb": {"rating": 8.8, "votes": 2000000},
                        "rotten_tomatoes": {"critic_score": 87},
                    },
                },
            }
        )

        intent = base_intent(entity_type="movie")
        retrieval = retrieve_candidates(self.store, intent)
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertIn("IMDb 8.8/10, 2,000,000 votes", ranked[0]["signal_facts"])
        self.assertIn("Rotten Tomatoes critic 87%", ranked[0]["signal_facts"])
        self.assertEqual(
            ranked[0]["metadata"]["external_ratings"]["rotten_tomatoes"]["critic_score"],
            87,
        )

    def test_external_ratings_only_break_primary_score_ties(self) -> None:
        self.store.upsert_entity(
            {
                "id": "movie_high_external",
                "type": "movie",
                "canonical_name": "High External",
                "metadata": {
                    "external_ratings": {
                        "imdb": {"rating": 9.0, "votes": 1000},
                        "rotten_tomatoes": {"critic_score": 95},
                    },
                },
            }
        )
        self.store.upsert_entity(
            {
                "id": "movie_personal",
                "type": "movie",
                "canonical_name": "Personal Favorite",
                "metadata": {
                    "external_ratings": {
                        "imdb": {"rating": 6.0, "votes": 1000},
                        "rotten_tomatoes": {"critic_score": 60},
                    },
                },
                "signals": [{"type": "rating", "value": 10}],
            }
        )
        self.store.upsert_entity(
            {
                "id": "movie_low_external",
                "type": "movie",
                "canonical_name": "Low External",
                "metadata": {
                    "external_ratings": {
                        "imdb": {"rating": 5.0, "votes": 1000},
                        "rotten_tomatoes": {"critic_score": 50},
                    },
                },
            }
        )

        intent = base_intent(entity_type="movie")
        retrieval = retrieve_candidates(self.store, intent)
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertEqual(ranked[0]["id"], "movie_personal")
        self.assertEqual(ranked[1]["id"], "movie_high_external")
        self.assertEqual(ranked[2]["id"], "movie_low_external")

    def test_context_match_can_lift_contextually_relevant_item(self) -> None:
        self.store.upsert_entity(
            {
                "id": "restaurant_context_view",
                "type": "restaurant",
                "canonical_name": "Context View",
                "attributes": {"view": 0.9},
                "signals": [{"type": "rating", "value": 8}],
            }
        )
        self.store.upsert_entity(
            {
                "id": "restaurant_context_plain",
                "type": "restaurant",
                "canonical_name": "Context Plain",
                "attributes": {"quiet": 0.9},
                "signals": [{"type": "rating", "value": 8}],
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
        self.assertIn(
            "context view: 0.90 (95% interval 0.90-0.90)",
            ranked[0]["matched_attributes"],
        )

    def test_attribute_matching_is_reflected_in_grounding(self) -> None:
        intent = base_intent(entity_type="wine", attributes=["oak", "premium"])
        retrieval = retrieve_candidates(self.store, intent)
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertEqual(ranked[0]["id"], "wine_mike")
        self.assertIn(
            "oak: 0.80 (95% interval 0.80-0.80)",
            ranked[0]["matched_attributes"],
        )
        self.assertIn(
            "premium: 0.70 (95% interval 0.70-0.70)",
            ranked[0]["matched_attributes"],
        )
        self.assertEqual(
            ranked[0]["attribute_intervals_95"]["oak"],
            {"lower": 0.8, "upper": 0.8},
        )
        self.assertEqual(
            ranked[0]["attribute_details"]["oak"],
            {"value": 0.8, "interval_95": {"lower": 0.8, "upper": 0.8}},
        )

    def test_grounding_surfaces_memory_status_for_menu_matches(self) -> None:
        self.store.upsert_entity(
            {
                "id": "wine_future",
                "type": "wine",
                "canonical_name": "Future Wine",
                "notes": "Stored because I wanted to try it.",
                "attributes": {"oak": 0.5},
            }
        )
        intent = base_intent(entity_type="wine")
        retrieval = retrieve_candidates(
            self.store,
            intent,
            [
                {"canonical_name": "Mike's Cabernet", "type": "wine"},
                {"canonical_name": "Future Wine", "type": "wine"},
            ],
        )
        ranked = {
            result["id"]: result
            for result in build_grounding(rank_candidates(retrieval["candidates"], intent))
        }

        self.assertEqual(ranked["wine_mike"]["memory_status"]["status"], "liked")
        self.assertTrue(ranked["wine_mike"]["memory_status"]["tried_or_watched"])
        self.assertEqual(ranked["wine_future"]["memory_status"]["status"], "want_to_try")
        self.assertNotIn("want_to_try", ranked["wine_future"]["memory_status"])

    def test_wide_attribute_intervals_are_discounted_in_ranking(self) -> None:
        self.store.upsert_entity(
            {
                "id": "wine_narrow_body",
                "type": "wine",
                "canonical_name": "Narrow Body",
                "attributes": {
                    "body": {
                        "value": 0.7,
                        "interval_95": {"lower": 0.69, "upper": 0.71},
                    }
                },
            }
        )
        self.store.upsert_entity(
            {
                "id": "wine_wide_body",
                "type": "wine",
                "canonical_name": "Wide Body",
                "attributes": {
                    "body": {
                        "value": 0.7,
                        "interval_95": {"lower": 0.3, "upper": 0.95},
                    }
                },
            }
        )

        intent = base_intent(entity_type="wine", attributes=["body"])
        retrieval = retrieve_candidates(
            self.store,
            intent,
            [
                {"canonical_name": "Narrow Body", "type": "wine"},
                {"canonical_name": "Wide Body", "type": "wine"},
            ],
        )
        ranked = build_grounding(rank_candidates(retrieval["candidates"], intent))

        self.assertEqual([result["id"] for result in ranked], ["wine_narrow_body", "wine_wide_body"])

    def test_attribute_match_is_capped(self) -> None:
        facts = score_entity(
            {
                "id": "wine_many_attrs",
                "type": "wine",
                "canonical_name": "Many Attrs",
                "attributes": {"body": 0.9, "oak": 0.9, "premium": 0.9},
            },
            required=["body", "oak", "premium"],
            context={},
            avoid_below=None,
            recommended_by=None,
            search_text="",
            weights=RankingWeights(attribute_match_cap=1.5),
        )

        self.assertEqual(facts["attribute_match_raw"], 2.7)
        self.assertEqual(facts["attribute_match"], 1.5)
        self.assertIn("attribute match capped at 1.5", facts["negative_signals"])

    def test_decision_feedback_boosts_previous_choices(self) -> None:
        intent = base_intent(entity_type="wine")
        retrieval = retrieve_candidates(
            self.store,
            intent,
            [
                {"canonical_name": "Mike's Cabernet", "type": "wine"},
                {"canonical_name": "Alex's Syrah", "type": "wine"},
            ],
        )
        ranked = build_grounding(
            rank_candidates(
                retrieval["candidates"],
                intent,
                decision_feedback={
                    "wine_mike": {"chosen": 4, "rejected": 0},
                    "wine_alex": {"chosen": 0, "rejected": 4},
                },
                weights=RankingWeights(
                    preference=0,
                    recommended_by_other=0,
                    decision_feedback_cap=1,
                ),
            )
        )

        self.assertEqual(ranked[0]["id"], "wine_mike")
        self.assertIn("chosen previously 4 time(s)", ranked[0]["signal_facts"])

    def test_search_text_handles_accents_and_simple_variants(self) -> None:
        entity = {
            "id": "restaurant_italia",
            "type": "restaurant",
            "canonical_name": "Caffe Italia",
            "notes": "Caffe with regional Italia cooking.",
            "attributes": {},
            "signals": [],
        }

        self.assertEqual(score_text_match(entity, "café italianate"), 1.0)

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
                    "signals": [{"type": "rating", "value": 8}],
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
                {"type": "rating", "value": 8},
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
            "attributes": {"body": 0.85, "spicy": 0.45},
            "signals": [
                {"type": "rating", "value": 10},
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
            "signals": [{"type": "rating", "value": 8}],
        }
    )
    store.upsert_entity(
        {
            "id": "restaurant_loud",
            "type": "restaurant",
            "canonical_name": "Loud Counter",
            "notes": "Lively casual dinner.",
            "attributes": {"lively": 0.9, "casual": 0.7},
            "signals": [{"type": "rating", "value": 10}],
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
