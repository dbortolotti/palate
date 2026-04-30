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

    def test_how_to_tool_returns_user_guide_markdown(self) -> None:
        guide_path = self.temp_dir / "USER-GUIDE.md"
        guide_path.write_text("# Palate User Guide\n\nUse Palate for this.\n", encoding="utf-8")

        with patch.object(server, "USER_GUIDE_PATH", guide_path):
            result = server.palate_how_to()

        self.assertEqual(result["title"], "Palate User Guide")
        self.assertEqual(result["mime_type"], "text/markdown")
        self.assertIn("Use Palate for this.", result["content"])

    def test_how_to_resource_returns_user_guide_markdown(self) -> None:
        guide_path = self.temp_dir / "USER-GUIDE.md"
        guide_path.write_text("# Palate User Guide\n\nConnector instructions.\n", encoding="utf-8")

        with patch.object(server, "USER_GUIDE_PATH", guide_path):
            result = server.palate_how_to_resource()

        self.assertIn("Connector instructions.", result)

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

    def test_delete_record_removes_exact_id(self) -> None:
        result = server.palate_delete_record("wine_mike")

        self.assertTrue(result["deleted"])
        self.assertEqual(result["record"]["name"], "Mike's Cabernet")
        self.assertNotIn(
            "wine_mike",
            {entity["id"] for entity in self.store.list_entities()},
        )

    def test_delete_record_reports_missing_id(self) -> None:
        result = server.palate_delete_record("missing")

        self.assertFalse(result["deleted"])
        self.assertEqual(result["id"], "missing")
        self.assertIn("No Palate record found", result["error"])

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

    def test_remember_accepts_movie_and_series_types(self) -> None:
        with patch.object(
            server,
            "normalize_enrichment",
            return_value={"attributes": {}, "notes": "", "metadata": {}},
        ):
            movie_result = server.palate_remember(
                id="movie_ok",
                type="movie",
                canonical_name="Movie OK",
                description="A movie to watch.",
                fetch_external_ratings=False,
            )
            series_result = server.palate_remember(
                id="series_ok",
                type="series",
                canonical_name="Series OK",
                description="A series to watch.",
                fetch_external_ratings=False,
            )

        self.assertTrue(movie_result["stored"])
        self.assertTrue(series_result["stored"])
        self.assertEqual(
            {entity["type"] for entity in self.store.list_entities() if entity["id"] in {"movie_ok", "series_ok"}},
            {"movie", "series"},
        )

    def test_remember_stores_media_metadata_and_rating_marks_watched(self) -> None:
        with patch.object(
            server,
            "normalize_enrichment",
            return_value={"attributes": {}, "notes": "", "metadata": {}},
        ):
            server.palate_remember(
                id="movie_meta",
                type="movie",
                canonical_name="Manual Movie",
                description="A precise thriller.",
                rating=4,
                synopsis="A precise thriller.",
                main_actors=["Actor One", "Actor Two"],
                director="Director One",
                country=["United Kingdom"],
                language=["English", "French"],
                genre=["Thriller"],
                runtime=104,
                seasons=1,
                imdb_id="tt7654321",
                fetch_external_ratings=False,
            )

        stored = next(entity for entity in self.store.list_entities() if entity["id"] == "movie_meta")

        self.assertTrue(stored["metadata"]["watched"])
        self.assertEqual(stored["metadata"]["synopsis"], "A precise thriller.")
        self.assertEqual(stored["metadata"]["main_actors"], ["Actor One", "Actor Two"])
        self.assertEqual(stored["metadata"]["director"], "Director One")
        self.assertEqual(stored["metadata"]["country"], ["United Kingdom"])
        self.assertEqual(stored["metadata"]["language"], ["English", "French"])
        self.assertEqual(stored["metadata"]["genre"], ["thriller"])
        self.assertEqual(stored["metadata"]["runtime"], 104)
        self.assertEqual(stored["metadata"]["seasons"], 1)
        self.assertEqual(stored["metadata"]["external_ids"]["imdb_id"], "tt7654321")

    def test_remember_stores_music_metadata(self) -> None:
        with patch.object(
            server,
            "normalize_enrichment",
            return_value={
                "attributes": {"intellectual": 0.8},
                "notes": "normalized",
                "metadata": {
                    "artist": "LLM Artist",
                    "album": "LLM Album",
                    "personnel": ["Player One"],
                    "genre": ["jazz"],
                },
            },
        ):
            server.palate_remember(
                id="music_kind_of_blue",
                type="music",
                canonical_name="Kind of Blue",
                description="Miles Davis modal jazz album.",
                artist="Miles Davis",
                album="Kind of Blue",
                personnel=["Miles Davis", "John Coltrane", "Bill Evans"],
                genre=["Jazz", "Modal Jazz"],
            )

        stored = next(
            entity
            for entity in self.store.list_entities()
            if entity["id"] == "music_kind_of_blue"
        )

        self.assertEqual(stored["metadata"]["artist"], "Miles Davis")
        self.assertEqual(stored["metadata"]["album"], "Kind of Blue")
        self.assertEqual(
            stored["metadata"]["personnel"],
            ["Miles Davis", "John Coltrane", "Bill Evans"],
        )
        self.assertEqual(stored["metadata"]["genre"], ["jazz"])
        self.assertEqual(stored["attributes"]["intellectual"], 0.8)

    def test_remember_warns_when_omdb_key_is_missing(self) -> None:
        with patch.dict("os.environ", {"OMDB_API_KEY": ""}), patch.object(
            server,
            "normalize_enrichment",
            return_value={"attributes": {}, "notes": "", "metadata": {}},
        ):
            result = server.palate_remember(
                id="movie_no_key",
                type="movie",
                canonical_name="No Key Movie",
                description="A movie with no key available.",
            )

        self.assertTrue(result["stored"])
        self.assertIn("OMDB_API_KEY is not set", result["warnings"][0])

    def test_omdb_metadata_fills_empty_fields_without_overriding_manual_fields(self) -> None:
        with patch.object(
            server,
            "fetch_omdb_metadata",
            return_value={
                "metadata": {
                    "synopsis": "OMDb synopsis",
                    "director": "OMDb Director",
                    "external_ids": {"imdb_id": "tt1111111"},
                    "external_ratings": {
                        "imdb": {"rating": 8.5, "votes": 1200},
                        "rotten_tomatoes": {"critic_score": 91},
                    },
                    "ratings_source": {"provider": "omdb", "fetched_at": "2026-04-30T00:00:00+00:00"},
                },
                "warnings": [],
            },
        ), patch.object(
            server,
            "normalize_enrichment",
            return_value={"attributes": {}, "notes": "", "metadata": {}},
        ):
            server.palate_remember(
                id="movie_omdb",
                type="movie",
                canonical_name="OMDb Movie",
                description="A movie with OMDb metadata.",
                director="Manual Director",
            )

        stored = next(entity for entity in self.store.list_entities() if entity["id"] == "movie_omdb")

        self.assertEqual(stored["metadata"]["director"], "Manual Director")
        self.assertEqual(stored["metadata"]["synopsis"], "OMDb synopsis")
        self.assertEqual(stored["metadata"]["external_ids"]["imdb_id"], "tt1111111")
        self.assertEqual(stored["metadata"]["external_ratings"]["imdb"]["rating"], 8.5)

    def test_manual_media_metadata_overrides_llm_metadata(self) -> None:
        with patch.object(
            server,
            "normalize_enrichment",
            return_value={
                "attributes": {},
                "notes": "normalized",
                "metadata": {
                    "director": "LLM Director",
                    "genre": ["Drama"],
                },
            },
        ):
            server.palate_remember(
                id="movie_manual_wins",
                type="movie",
                canonical_name="Manual Wins",
                description="some movie notes",
                director="Manual Director",
                fetch_external_ratings=False,
            )

        stored = next(
            entity
            for entity in self.store.list_entities()
            if entity["id"] == "movie_manual_wins"
        )

        self.assertEqual(stored["metadata"]["director"], "Manual Director")
        self.assertEqual(stored["metadata"]["genre"], ["drama"])

    def test_remember_rejects_unknown_entity_type(self) -> None:
        with self.assertRaises(ValueError):
            server.palate_remember(
                id="bad",
                type="book",
                canonical_name="Bad Type",
                description="Invalid type.",
            )

    def test_remember_rejects_blank_description_before_llm_call(self) -> None:
        with patch.object(server, "normalize_enrichment", side_effect=AssertionError("should not call")):
            with self.assertRaises(ValueError):
                server.palate_remember(
                    id="movie_blank",
                    type="movie",
                    canonical_name="Blank Description",
                    description="   ",
                )

    def test_remember_rejects_attributes_not_valid_for_type_before_llm_call(self) -> None:
        with patch.object(server, "normalize_enrichment", side_effect=AssertionError("should not call")):
            with self.assertRaises(ValueError) as caught:
                server.palate_remember(
                    id="movie_oak",
                    type="movie",
                    canonical_name="Oaky Movie",
                    description="A movie that should not accept wine attributes.",
                    attributes={"oak": 0.7},
                )

        self.assertIn("attributes for movie", str(caught.exception))
        self.assertIn("oak", str(caught.exception))

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
