from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from palate.llm import normalize_enrichment, normalize_restaurant_enrichment, parse_intent
from palate.media import MEDIA_GENRES, MICHELIN_STATUSES, MUSIC_GENRES, RESTAURANT_GENRES
from palate.schema import ATTRIBUTE_KEYS, attribute_keys_for_type


class LlmSchemaBehaviorTest(unittest.TestCase):
    def test_normalize_enrichment_uses_type_specific_attribute_schema(self) -> None:
        movie_attributes = attribute_keys_for_type("movie")
        response = {
            "attributes": {key: 0 for key in movie_attributes},
            "notes": "",
            "metadata": {},
        }

        with patch("palate.llm.json_response", return_value=response) as json_response:
            result = normalize_enrichment("tense sci-fi film", "movie")

        kwargs = json_response.call_args.kwargs

        self.assertEqual(result, response)
        self.assertEqual(kwargs["payload"]["allowed_attributes"], movie_attributes)
        self.assertEqual(
            kwargs["schema"]["properties"]["attributes"]["required"],
            movie_attributes,
        )
        suspenseful_schema = kwargs["schema"]["properties"]["attributes"]["properties"][
            "suspenseful"
        ]
        self.assertEqual(suspenseful_schema["required"], ["value", "interval_95"])
        self.assertEqual(
            suspenseful_schema["properties"]["interval_95"]["properties"]["upper"][
                "maximum"
            ],
            1,
        )
        self.assertIn("suspenseful", movie_attributes)
        self.assertNotIn("oak", movie_attributes)
        media_genre_schema = kwargs["schema"]["properties"]["metadata"]["properties"]["genre"]
        media_required = kwargs["schema"]["properties"]["metadata"]["required"]
        self.assertEqual(media_genre_schema["items"]["enum"], MEDIA_GENRES)
        self.assertIn("language", media_required)
        self.assertIn("runtime", media_required)
        self.assertIn("seasons", media_required)

    def test_normalize_enrichment_uses_music_metadata_schema(self) -> None:
        music_attributes = attribute_keys_for_type("music")
        response = {
            "attributes": {key: 0 for key in music_attributes},
            "notes": "",
            "metadata": {
                "artist": "Miles Davis",
                "album": "Kind of Blue",
                "personnel": ["John Coltrane"],
                "genre": ["jazz"],
            },
        }

        with patch("palate.llm.json_response", return_value=response) as json_response:
            result = normalize_enrichment("Miles Davis Kind of Blue", "music")

        metadata_schema = json_response.call_args.kwargs["schema"]["properties"]["metadata"]

        self.assertEqual(result, response)
        self.assertEqual(
            metadata_schema["required"],
            ["artist", "album", "personnel", "genre"],
        )
        self.assertEqual(
            metadata_schema["properties"]["genre"]["items"]["enum"],
            MUSIC_GENRES,
        )

    def test_normalize_enrichment_uses_restaurant_cuisine_metadata_schema(self) -> None:
        restaurant_attributes = attribute_keys_for_type("restaurant")
        response = {
            "attributes": {key: 0 for key in restaurant_attributes},
            "notes": "",
            "metadata": {
                "cuisine": {
                    key: {"value": 0, "interval_95": {"lower": 0, "upper": 0}}
                    for key in RESTAURANT_GENRES
                },
                "michelin": {
                    "status": "unknown",
                    "stars": None,
                    "green_star": False,
                    "source_url": None,
                    "source": None,
                    "checked_at": None,
                },
                "google": {
                    "rating": None,
                    "rating_count": None,
                    "source_url": None,
                    "source": None,
                    "checked_at": None,
                },
            },
        }

        with patch("palate.llm.json_response", return_value=response) as json_response:
            result = normalize_enrichment("Italian trattoria", "restaurant")

        metadata_schema = json_response.call_args.kwargs["schema"]["properties"]["metadata"]

        self.assertEqual(result, response)
        self.assertEqual(metadata_schema["required"], ["cuisine", "michelin", "google"])
        self.assertEqual(
            metadata_schema["properties"]["cuisine"]["required"],
            RESTAURANT_GENRES,
        )
        self.assertIn("other", metadata_schema["properties"]["cuisine"]["properties"])
        self.assertEqual(
            metadata_schema["properties"]["michelin"]["properties"]["status"]["enum"],
            MICHELIN_STATUSES,
        )
        self.assertEqual(
            metadata_schema["properties"]["google"]["properties"]["rating"]["maximum"],
            5,
        )

    def test_restaurant_web_enrichment_requests_direct_1sigma_interval(self) -> None:
        restaurant_attributes = attribute_keys_for_type("restaurant")
        attributes = {
            key: {
                "value": 0,
                "interval_95": {"lower": 0, "upper": 0},
                "interval_1sigma": {"lower": 0, "upper": 0},
            }
            for key in restaurant_attributes
        }
        attributes["premium"] = {
            "value": 0.7,
            "interval_95": {"lower": 0.4, "upper": 0.9},
            "interval_1sigma": {"lower": 0.58, "upper": 0.76},
        }
        response = type(
            "FakeResponse",
            (),
            {
                "output_text": json.dumps(
                    {
                        "attributes": attributes,
                        "notes": "grounded",
                        "metadata": {
                            "cuisine": {},
                            "michelin": {
                                "status": "unknown",
                                "stars": None,
                                "green_star": False,
                                "source_url": None,
                                "source": None,
                                "checked_at": None,
                            },
                            "google": {
                                "rating": 4.6,
                                "rating_count": 123,
                                "source_url": "https://www.google.com/maps/place/test",
                                "source": "google",
                                "checked_at": "2026-05-03",
                            },
                        },
                    }
                ),
                "output": [],
            },
        )()

        with patch("palate.llm.client") as client:
            client.return_value.responses.create.return_value = response
            result = normalize_restaurant_enrichment("Casa Test")

        kwargs = client.return_value.responses.create.call_args.kwargs
        attribute_schema = kwargs["text"]["format"]["schema"]["properties"][
            "attributes"
        ]["properties"]["premium"]

        self.assertEqual(
            result["attributes"]["premium"]["interval_1sigma"]["lower"],
            0.58,
        )
        self.assertEqual(attribute_schema["required"], [
            "value",
            "interval_95",
            "interval_1sigma",
        ])
        self.assertEqual(
            kwargs["text"]["format"]["schema"]["properties"]["attributes"]["required"],
            restaurant_attributes,
        )
        self.assertIn("do not derive", kwargs["input"][0]["content"])
        self.assertIn("guide.michelin.com", kwargs["input"][0]["content"])
        self.assertIn("Google Maps", kwargs["input"][0]["content"])
        self.assertEqual(
            kwargs["text"]["format"]["schema"]["properties"]["metadata"]["required"],
            ["cuisine", "michelin", "google"],
        )
        self.assertEqual(result["metadata"]["google"]["rating_count"], 123)

    def test_wine_attribute_schema_uses_core_and_flavour_wheel_terms(self) -> None:
        wine_attributes = attribute_keys_for_type("wine")

        self.assertEqual(
            wine_attributes,
            [
                "premium",
                "classic",
                "body",
                "tannin",
                "acidity",
                "oak",
                "fruity",
                "floral",
                "spicy",
                "vegetative",
                "nutty",
                "caramelized",
                "woody",
                "earthy",
                "chemical",
                "pungent",
                "oxidized",
                "microbiological",
            ],
        )
        self.assertNotIn("richness", wine_attributes)
        self.assertNotIn("intensity", wine_attributes)
        self.assertNotIn("indulgent", wine_attributes)
        self.assertNotIn("comfort", wine_attributes)

    def test_parse_intent_filters_attributes_by_known_entity_type(self) -> None:
        context = {key: False for key in ATTRIBUTE_KEYS}
        context["oak"] = True
        context["suspenseful"] = True
        response = {
            "intent": "contextual_decision",
            "attributes": ["oak", "suspenseful"],
            "context": context,
            "filters": {"min_rating": None, "recommended_by": None, "cuisine": []},
            "entity_type": "movie",
            "search_text": "",
        }

        with patch("palate.llm.json_response", return_value=response) as json_response:
            intent = parse_intent("a suspenseful movie")

        min_rating_schema = json_response.call_args.kwargs["schema"]["properties"][
            "filters"
        ]["properties"]["min_rating"]
        cuisine_schema = json_response.call_args.kwargs["schema"]["properties"][
            "filters"
        ]["properties"]["cuisine"]
        self.assertEqual(intent["attributes"], ["suspenseful"])
        self.assertEqual(intent["context"], {"suspenseful": True})
        self.assertEqual(intent["filters"]["cuisine"], [])
        self.assertEqual(min_rating_schema["maximum"], 10)
        self.assertEqual(cuisine_schema["items"]["enum"], RESTAURANT_GENRES)


if __name__ == "__main__":
    unittest.main()
