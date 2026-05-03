from __future__ import annotations

import asyncio
import unittest

import palate.server as server


class ApiAffordanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}

    def test_public_surface_has_no_confusing_preview_or_enrich_tools(self) -> None:
        self.assertIn("palate_describe_item", self.tools)
        self.assertNotIn("palate_lookup", self.tools)
        self.assertNotIn("palate_enrich_item", self.tools)

    def test_descriptions_distinguish_common_user_intents(self) -> None:
        expectations = {
            "palate_describe_item": ["tell", "without storing", "do not save"],
            "palate_remember": ["store", "remember/save"],
            "palate_query": ["recommend", "saved", "open-ended"],
            "palate_evaluate_options": ["rank only", "pasted/provided options"],
            "palate_recall": ["recall", "saved", "not asking to rank"],
            "palate_delete_record": ["delete", "99%+", "returns candidates"],
        }

        for tool_name, expected_phrases in expectations.items():
            description = self.tools[tool_name].description.lower()
            for phrase in expected_phrases:
                with self.subTest(tool=tool_name, phrase=phrase):
                    self.assertIn(phrase, description)

    def test_required_fields_are_minimal_for_llm_routing(self) -> None:
        required = {
            name: set(tool.inputSchema.get("required") or [])
            for name, tool in self.tools.items()
        }

        self.assertEqual(required["palate_describe_item"], {"item_text", "entity_type"})
        self.assertEqual(
            required["palate_remember"],
            {"id", "type", "canonical_name", "description"},
        )
        self.assertEqual(required["palate_query"], {"query"})
        self.assertEqual(required["palate_evaluate_options"], {"query", "options_text"})
        self.assertEqual(required["palate_recall"], {"query"})
        self.assertEqual(required["palate_delete_record"], {"id"})

    def test_no_public_description_tells_llm_to_use_lookup(self) -> None:
        for tool in self.tools.values():
            with self.subTest(tool=tool.name):
                self.assertNotIn("palate_lookup", tool.description)
                self.assertNotIn("lookup without storing", tool.description.lower())
