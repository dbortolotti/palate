from __future__ import annotations

import unittest
from unittest.mock import patch

from palate.llm import normalize_enrichment, parse_intent
from palate.media import MEDIA_GENRES, MUSIC_GENRES
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

    def test_parse_intent_filters_attributes_by_known_entity_type(self) -> None:
        context = {key: False for key in ATTRIBUTE_KEYS}
        context["oak"] = True
        context["suspenseful"] = True
        response = {
            "intent": "contextual_decision",
            "attributes": ["oak", "suspenseful"],
            "context": context,
            "filters": {"min_rating": None, "recommended_by": None},
            "entity_type": "movie",
            "search_text": "",
        }

        with patch("palate.llm.json_response", return_value=response):
            intent = parse_intent("a suspenseful movie")

        self.assertEqual(intent["attributes"], ["suspenseful"])
        self.assertEqual(intent["context"], {"suspenseful": True})


if __name__ == "__main__":
    unittest.main()
