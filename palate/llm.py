from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from .schema import ATTRIBUTE_KEYS, ENTITY_TYPES, INTENTS


MODEL = os.getenv("PALATE_MODEL", "gpt-5.5")


def client() -> OpenAI:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for this LLM-owned operation.")
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def parse_intent(query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return json_response(
        name="palate_intent",
        instructions=" ".join(
            [
                "You translate ambiguous taste requests into Palate's fixed intent schema.",
                "Do not rank or recommend anything.",
                "Use only predefined attributes and entity types.",
                "If uncertain, leave fields empty or set intent to fuzzy_recall.",
            ]
        ),
        payload={
            "query": query,
            "context": context or {},
            "allowed_attributes": ATTRIBUTE_KEYS,
            "allowed_entity_types": ENTITY_TYPES,
            "allowed_intents": INTENTS,
        },
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "intent",
                "attributes",
                "context",
                "filters",
                "entity_type",
                "search_text",
            ],
            "properties": {
                "intent": {"type": "string", "enum": INTENTS},
                "attributes": {
                    "type": "array",
                    "items": {"type": "string", "enum": ATTRIBUTE_KEYS},
                },
                "context": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ATTRIBUTE_KEYS,
                    "properties": {
                        key: {"type": "boolean"} for key in ATTRIBUTE_KEYS
                    },
                },
                "filters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["min_rating", "recommended_by"],
                    "properties": {
                        "min_rating": {
                            "type": ["number", "null"],
                            "minimum": 1,
                            "maximum": 5,
                        },
                        "recommended_by": {"type": ["string", "null"]},
                    },
                },
                "entity_type": {"type": ["string", "null"], "enum": [*ENTITY_TYPES, None]},
                "search_text": {"type": "string"},
            },
        },
    )


def extract_entities(text: str, expected_type: str | None = None) -> dict[str, Any]:
    return json_response(
        name="palate_entities",
        instructions=" ".join(
            [
                "Extract canonical entities from an option set such as a wine list or restaurant shortlist.",
                "Do not evaluate or rank them.",
                "Return only entities present in the input.",
            ]
        ),
        payload={
            "text": text,
            "expected_type": expected_type,
            "allowed_entity_types": ENTITY_TYPES,
        },
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["entities"],
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["canonical_name", "type", "source_text"],
                        "properties": {
                            "canonical_name": {"type": "string"},
                            "type": {"type": "string", "enum": ENTITY_TYPES},
                            "source_text": {"type": "string"},
                        },
                    },
                }
            },
        },
    )


def normalize_enrichment(item_text: str, entity_type: str) -> dict[str, Any]:
    return json_response(
        name="palate_enrichment",
        instructions=" ".join(
            [
                "Normalize noisy descriptive text into Palate's fixed attribute schema.",
                "Never invent new attribute keys.",
                "Each value must be in [0, 1]. Use 0 when not evidenced.",
            ]
        ),
        payload={
            "item_text": item_text,
            "entity_type": entity_type,
            "allowed_attributes": ATTRIBUTE_KEYS,
        },
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["attributes", "notes"],
            "properties": {
                "attributes": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ATTRIBUTE_KEYS,
                    "properties": {
                        key: {"type": "number", "minimum": 0, "maximum": 1}
                        for key in ATTRIBUTE_KEYS
                    },
                },
                "notes": {"type": "string"},
            },
        },
    )


def explain_results(
    query: str,
    intent: dict[str, Any],
    grounding: list[dict[str, Any]],
) -> str:
    response = client().responses.create(
        model=MODEL,
        input=[
            {
                "role": "system",
                "content": " ".join(
                    [
                        "You write concise Palate explanations.",
                        "Use only the provided grounding facts.",
                        "Do not introduce new preferences, ratings, provenance, or tasting notes.",
                        "Do not change the ranking order.",
                    ]
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "query": query,
                        "intent": intent,
                        "ranked_results": grounding,
                    }
                ),
            },
        ],
        text={"verbosity": "low"},
    )
    return response.output_text.strip()


def json_response(
    *,
    name: str,
    instructions: str,
    payload: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    response = client().responses.create(
        model=MODEL,
        input=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(payload)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": name,
                "strict": True,
                "schema": schema,
            }
        },
    )
    return json.loads(response.output_text)
