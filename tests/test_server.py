from __future__ import annotations

import asyncio
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
        self.assertEqual(
            result["server_llm_used"],
            {"intent": True, "entity_extraction": False, "explanation": False},
        )
        event = self.store.list_application_events(tool_name="palate_query")[0]
        self.assertEqual(event["status"], "success")
        self.assertEqual(event["input"]["query"], "oaky wine")
        self.assertEqual(event["output"]["ranked_results"][0]["id"], "wine_mike")
        self.assertEqual(event["metadata"]["ranked_count"], 1)
        self.assertTrue(event["metadata"]["server_llm_used"]["intent"])

    def test_query_accepts_client_intent_without_server_intent_call(self) -> None:
        with patch.object(server, "parse_intent", side_effect=AssertionError("should not parse")):
            result = server.palate_query(
                "oaky wine",
                intent=base_intent(entity_type="wine", attributes=["oak"]),
                explain=False,
            )

        self.assertEqual(result["ranked_results"][0]["id"], "wine_mike")
        self.assertFalse(result["server_llm_used"]["intent"])

    def test_tool_errors_are_logged_before_reraising(self) -> None:
        with self.assertRaises(ValueError):
            server.palate_remember(
                id="bad",
                type="wine",
                canonical_name="Bad Wine",
                description="",
                fetch_external_ratings=False,
            )

        event = self.store.list_application_events(tool_name="palate_remember")[0]
        self.assertEqual(event["status"], "error")
        self.assertEqual(event["input"]["id"], "bad")
        self.assertEqual(event["error"]["type"], "ValueError")
        self.assertIn("description is required", event["error"]["message"])

    def test_backup_now_returns_snapshot_paths(self) -> None:
        with patch.object(server, "backup_once", return_value={"sqlite": "a.sqlite", "json": "a.json", "removed": []}):
            result = server.palate_backup_now()

        self.assertEqual(result["sqlite"], "a.sqlite")
        self.assertEqual(result["json"], "a.json")

    def test_healthz_reports_database_ready(self) -> None:
        result = asyncio.run(server.healthz(None))

        self.assertEqual(result.status_code, 200)

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
        self.assertEqual(result["retrieval"]["option_matches"][0]["matched_id"], "wine_mike")
        self.assertEqual(result["retrieval"]["needs_confirmation"], [])

    def test_evaluate_options_accepts_client_entities_without_extraction_call(self) -> None:
        with patch.object(server, "parse_intent", side_effect=AssertionError("should not parse")), \
             patch.object(server, "extract_entities", side_effect=AssertionError("should not extract")), \
             patch.object(server, "explain_results", side_effect=AssertionError("should not explain")):
            result = server.palate_evaluate_options(
                "which wine",
                "Mike's Cabernet\nUnknown Cellar Cabernet",
                intent=base_intent(entity_type="wine"),
                extracted_entities=[
                    {"canonical_name": "Mike's Cabernet", "type": "wine"},
                    {"canonical_name": "Unknown Cellar Cabernet", "type": "wine"},
                ],
            )

        self.assertEqual(result["ranked_results"][0]["id"], "wine_mike")
        self.assertEqual(result["retrieval"]["unmatched_options"], ["Unknown Cellar Cabernet"])
        self.assertEqual(result["retrieval"]["option_matches"][0]["matched_id"], "wine_mike")
        self.assertEqual(
            result["server_llm_used"],
            {"intent": False, "entity_extraction": False, "explanation": False},
        )

    def test_evaluate_options_surfaces_uncertain_match_for_confirmation(self) -> None:
        with patch.object(server, "parse_intent", side_effect=AssertionError("should not parse")), \
             patch.object(server, "extract_entities", side_effect=AssertionError("should not extract")):
            result = server.palate_evaluate_options(
                "which wine",
                "Mike Syrah",
                intent=base_intent(entity_type="wine"),
                extracted_entities=[{"canonical_name": "Mike Syrah", "type": "wine"}],
            )

        self.assertEqual(result["ranked_results"][0]["id"], "wine_mike")
        self.assertEqual(result["retrieval"]["needs_confirmation"][0]["matched_id"], "wine_mike")
        self.assertLess(result["retrieval"]["needs_confirmation"][0]["confidence"], 0.85)

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

    def test_remember_accepts_valid_client_attributes_without_server_enrichment(self) -> None:
        with patch.object(server, "normalize_enrichment", side_effect=AssertionError("should not enrich")):
            result = server.palate_remember(
                id="wine_new",
                type="wine",
                canonical_name="New Wine",
                description="rich and oaky",
                attributes={"oak": 0.9, "premium": 0.4},
                attribute_intervals_95={"oak": {"lower": 0.85, "upper": 0.95}},
                rating=10,
                recommended_by="Sam",
            )

        stored = next(entity for entity in self.store.list_entities() if entity["id"] == "wine_new")
        self.assertTrue(result["stored"])
        self.assertEqual(stored["attributes"]["oak"], 0.9)
        self.assertEqual(stored["attributes"]["premium"], 0.4)
        self.assertEqual(
            stored["attribute_intervals_95"]["oak"],
            {"lower": 0.85, "upper": 0.95},
        )
        self.assertEqual(
            stored["attribute_intervals_95"]["premium"],
            {"lower": 0.4, "upper": 0.4},
        )
        self.assertEqual(
            result["normalized_attribute_intervals_95"]["oak"],
            {"lower": 0.85, "upper": 0.95},
        )
        self.assertEqual(result["server_llm_used"], {"enrichment": False})
        self.assertEqual(
            {signal["type"] for signal in stored["signals"]},
            {"rating", "tried", "recommended_by"},
        )

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
                rating=8,
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
        self.assertIn(
            "tried",
            {signal["type"] for signal in stored["signals"]},
        )

    def test_remember_stores_explicit_tried_signal(self) -> None:
        with patch.object(
            server,
            "normalize_enrichment",
            return_value={"attributes": {}, "notes": "", "metadata": {}},
        ):
            server.palate_remember(
                id="restaurant_tried",
                type="restaurant",
                canonical_name="Tried Restaurant",
                description="A tried restaurant.",
                tried=True,
                rating=7,
            )

        stored = next(
            entity
            for entity in self.store.list_entities()
            if entity["id"] == "restaurant_tried"
        )

        self.assertEqual(
            {signal["type"] for signal in stored["signals"]},
            {"rating", "tried"},
        )

    def test_remember_stores_restaurant_cuisine_as_genre_metadata(self) -> None:
        with patch.object(
            server,
            "normalize_enrichment",
            return_value={
                "attributes": {},
                "notes": "",
                "metadata": {"genre": ["Italian", "Pizzeria"]},
            },
        ):
            server.palate_remember(
                id="restaurant_italian",
                type="restaurant",
                canonical_name="Casa Test",
                description="Italian neighborhood restaurant.",
                genre=["Mexican", "Modern European"],
            )

        stored = next(
            entity
            for entity in self.store.list_entities()
            if entity["id"] == "restaurant_italian"
        )

        self.assertEqual(stored["metadata"]["genre"], ["mexican", "modern_european"])

    def test_describe_item_suggests_restaurant_genre_remember_payload(self) -> None:
        with patch.object(
            server,
            "normalize_enrichment",
            return_value={
                "attributes": {},
                "notes": "Italian restaurant",
                "metadata": {"genre": ["Trattoria", "Italian"]},
            },
        ):
            result = server.palate_describe_item(
                item_text="Casa Test Italian restaurant",
                entity_type="restaurant",
                canonical_name="Casa Test",
            )

        self.assertEqual(result["enriched"]["metadata"]["genre"], ["italian"])
        self.assertEqual(
            result["suggested_remember"]["arguments"]["genre"],
            ["italian"],
        )

    def test_lookup_computes_memory_without_storing(self) -> None:
        before_ids = {entity["id"] for entity in self.store.list_entities()}

        with patch.object(
            server,
            "normalize_enrichment",
            return_value={
                "attributes": {
                    "suspenseful": {
                        "value": 0.8,
                        "interval_95": {"lower": 0.7, "upper": 0.9},
                    },
                },
                "notes": "normalized",
                "metadata": {
                    "director": "LLM Director",
                    "genre": ["Thriller"],
                },
            },
        ):
            result = server.palate_lookup(
                type="movie",
                canonical_name="Lookup Movie",
                description="A tense thriller.",
                do_not_store=True,
                rating=8,
                director="Manual Director",
                fetch_external_ratings=False,
            )

        after_ids = {entity["id"] for entity in self.store.list_entities()}
        self.assertEqual(after_ids, before_ids)
        self.assertFalse(result["stored"])
        self.assertEqual(result["record"]["canonical_name"], "Lookup Movie")
        self.assertEqual(result["record"]["attributes"]["suspenseful"], 0.8)
        self.assertEqual(
            result["record"]["attribute_intervals_95"]["suspenseful"],
            {"lower": 0.7, "upper": 0.9},
        )
        self.assertEqual(result["record"]["metadata"]["director"], "Manual Director")
        self.assertTrue(result["record"]["metadata"]["watched"])
        self.assertEqual(
            {signal["type"] for signal in result["record"]["signals"]},
            {"rating", "tried"},
        )

    def test_lookup_requires_explicit_do_not_store_flag(self) -> None:
        with patch.object(server, "normalize_enrichment", side_effect=AssertionError("should not call")):
            with self.assertRaises(ValueError) as caught:
                server.palate_lookup(
                    type="wine",
                    canonical_name="Lookup Wine",
                    description="A structured wine.",
                    do_not_store=False,
                    fetch_external_ratings=False,
                )

        self.assertIn("do_not_store=true", str(caught.exception))
        self.assertIn("explicitly says not to store", str(caught.exception))

    def test_describe_item_returns_existing_memory_without_enriching(self) -> None:
        before_ids = {entity["id"] for entity in self.store.list_entities()}

        with patch.object(server, "normalize_enrichment", side_effect=AssertionError("should not enrich")):
            result = server.palate_describe_item(
                item_text="Mike's Cabernet",
                entity_type="wine",
            )

        after_ids = {entity["id"] for entity in self.store.list_entities()}
        self.assertEqual(after_ids, before_ids)
        self.assertFalse(result["stored"])
        self.assertTrue(result["found_existing"])
        self.assertEqual(result["source"], "memory")
        self.assertEqual(result["record"]["id"], "wine_mike")
        self.assertEqual(result["match"]["confidence"], 1.0)
        self.assertIsNone(result["suggested_remember"])
        self.assertEqual(result["server_llm_used"], {"enrichment": False})

    def test_describe_item_surfaces_uncertain_match_without_enriching(self) -> None:
        with patch.object(server, "normalize_enrichment", side_effect=AssertionError("should not enrich")):
            result = server.palate_describe_item(
                item_text="Mike Syrah",
                entity_type="wine",
            )

        self.assertFalse(result["found_existing"])
        self.assertEqual(result["source"], "memory_confirmation_required")
        self.assertEqual(result["needs_confirmation"][0]["matched_id"], "wine_mike")
        self.assertLess(result["needs_confirmation"][0]["confidence"], 0.85)
        self.assertIsNone(result["enriched"])
        self.assertIn("Confirm", result["ask_user"])

    def test_describe_item_enriches_missing_item_without_storing(self) -> None:
        before_ids = {entity["id"] for entity in self.store.list_entities()}

        with patch.object(
            server,
            "normalize_enrichment",
            return_value={
                "attributes": {
                    "body": {
                        "value": 0.7,
                        "interval_95": {"lower": 0.4, "upper": 0.9},
                    },
                    "premium": {
                        "value": 0.9,
                        "interval_95": {"lower": 0.6, "upper": 1.0},
                    },
                },
                "notes": "structured Barbaresco profile",
                "metadata": {},
            },
        ) as enrich:
            result = server.palate_describe_item(
                item_text="Gaja 2016 Barbaresco",
                entity_type="wine",
            )

        after_ids = {entity["id"] for entity in self.store.list_entities()}
        self.assertEqual(after_ids, before_ids)
        enrich.assert_called_once_with("Gaja 2016 Barbaresco", "wine")
        self.assertFalse(result["stored"])
        self.assertFalse(result["found_existing"])
        self.assertEqual(result["source"], "enrichment")
        self.assertEqual(result["enriched"]["canonical_name"], "Gaja 2016 Barbaresco")
        self.assertEqual(result["normalized_attributes"]["premium"], 0.9)
        self.assertEqual(
            result["normalized_attribute_intervals_95"]["body"],
            {"lower": 0.4, "upper": 0.9},
        )
        self.assertEqual(result["suggested_remember"]["tool"], "palate_remember")
        self.assertEqual(
            result["suggested_remember"]["arguments"]["id"],
            "wine_gaja_2016_barbaresco",
        )
        self.assertEqual(
            result["suggested_remember"]["arguments"]["attributes"]["premium"],
            0.9,
        )
        self.assertIn("remember", result["ask_user"])
        self.assertEqual(result["server_llm_used"], {"enrichment": True})

    def test_lookup_mcp_schema_requires_do_not_store(self) -> None:
        tools = asyncio.run(server.mcp.list_tools())
        lookup_tool = next(tool for tool in tools if tool.name == "palate_lookup")

        self.assertIn("do_not_store", lookup_tool.inputSchema["required"])
        self.assertIn("explicitly says not to store", lookup_tool.description)

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
        self.assertEqual(
            stored["attribute_intervals_95"]["intellectual"],
            {"lower": 0.8, "upper": 0.8},
        )

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

    def test_remember_ignores_invalid_client_attributes(self) -> None:
        with patch.object(
            server,
            "normalize_enrichment",
            return_value={
                "attributes": {
                    "suspenseful": {
                        "value": 0.7,
                        "interval_95": {"lower": 0.5, "upper": 0.9},
                    },
                },
                "notes": "",
                "metadata": {},
            },
        ):
            server.palate_remember(
                id="movie_oak",
                type="movie",
                canonical_name="Oaky Movie",
                description="A movie that should not accept wine attributes.",
                attributes={"oak": 0.7},
                attribute_intervals_95={"oak": {"lower": 0.9, "upper": 0.4}},
                fetch_external_ratings=False,
            )

        stored = next(
            entity
            for entity in self.store.list_entities()
            if entity["id"] == "movie_oak"
        )
        self.assertNotIn("oak", stored["attributes"])
        self.assertEqual(stored["attributes"]["suspenseful"], 0.7)
        self.assertEqual(
            stored["attribute_intervals_95"]["suspenseful"],
            {"lower": 0.5, "upper": 0.9},
        )

    def test_remember_rejects_rating_outside_ten_point_scale_before_llm_call(self) -> None:
        with patch.object(server, "normalize_enrichment", side_effect=AssertionError("should not call")):
            with self.assertRaises(ValueError) as caught:
                server.palate_remember(
                    id="wine_bad_rating",
                    type="wine",
                    canonical_name="Bad Rating",
                    description="A wine with an invalid rating.",
                    rating=11,
                )

        self.assertIn("between 1 and 10", str(caught.exception))

    def test_remember_rejects_tried_or_watched_without_rating_before_llm_call(self) -> None:
        with patch.object(server, "normalize_enrichment", side_effect=AssertionError("should not call")):
            with self.assertRaises(ValueError) as tried_error:
                server.palate_remember(
                    id="wine_tried_no_rating",
                    type="wine",
                    canonical_name="Tried No Rating",
                    description="A tried item with no score.",
                    tried=True,
                )
            with self.assertRaises(ValueError) as watched_error:
                server.palate_remember(
                    id="movie_watched_no_rating",
                    type="movie",
                    canonical_name="Watched No Rating",
                    description="A watched movie with no score.",
                    watched=True,
                    fetch_external_ratings=False,
                )

        self.assertIn(
            "rating is required when tried is true",
            str(tried_error.exception),
        )
        self.assertIn(
            "rating is required when watched is true",
            str(watched_error.exception),
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
                {"type": "rating", "value": 8},
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
            "signals": [{"type": "rating", "value": 8}],
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
