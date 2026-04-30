from __future__ import annotations

import unittest
from unittest.mock import patch

from palate.llm import normalize_enrichment, parse_intent
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
