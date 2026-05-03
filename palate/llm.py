from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from .media import MEDIA_GENRES, MUSIC_GENRES
from .schema import (
    ATTRIBUTE_KEYS,
    ATTRIBUTE_KEYS_BY_TYPE,
    ENTITY_TYPES,
    INTENTS,
    attribute_keys_for_type,
)


MODEL = os.getenv("PALATE_MODEL", "gpt-5.4-mini")


def client() -> OpenAI:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for this LLM-owned operation.")
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def parse_intent(query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    intent = json_response(
        name="palate_intent",
        instructions=" ".join(
            [
                "You translate ambiguous taste requests into Palate's fixed intent schema.",
                "Do not rank or recommend anything.",
                "Use only predefined attributes and entity types.",
                "Attributes are scoped by entity type.",
                "If entity_type is known, use only attributes allowed for that entity type.",
                "If uncertain, leave fields empty or set intent to fuzzy_recall.",
            ]
        ),
        payload={
            "query": query,
            "context": context or {},
            "allowed_attributes": ATTRIBUTE_KEYS,
            "allowed_attributes_by_type": ATTRIBUTE_KEYS_BY_TYPE,
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
                            "maximum": 10,
                        },
                        "recommended_by": {"type": ["string", "null"]},
                    },
                },
                "entity_type": {"type": ["string", "null"], "enum": [*ENTITY_TYPES, None]},
                "search_text": {"type": "string"},
            },
        },
    )
    return filter_intent_attributes(intent)


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
    allowed_attributes = attribute_keys_for_type(entity_type)
    return json_response(
        name="palate_enrichment",
        instructions=" ".join(
            [
                "Normalize noisy descriptive text into Palate's fixed attribute schema for the given entity type.",
                "Never invent new attribute keys.",
                "Each attribute must include value and interval_95.",
                "Each value must be in [0, 1]. Use 0 when not evidenced.",
                "Each interval_95 is the 95% interval for the true attribute value.",
                "Each interval_95 must include the value and stay within [0, 1].",
                "Use a narrow interval when evidence is explicit and a wide interval when weak or absent.",
                "For movie or series items, extract only explicitly evidenced media metadata.",
                "For music items, extract only explicitly evidenced music metadata.",
                "Use canonical genre values exactly as provided by the schema.",
                "Do not invent external ratings, external IDs, or watched status.",
            ]
        ),
        payload={
            "item_text": item_text,
            "entity_type": entity_type,
            "allowed_attributes": allowed_attributes,
            "allowed_attributes_by_type": ATTRIBUTE_KEYS_BY_TYPE,
            "allowed_media_genres": MEDIA_GENRES,
            "allowed_music_genres": MUSIC_GENRES,
        },
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["attributes", "notes", "metadata"],
            "properties": {
                "attributes": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": allowed_attributes,
                    "properties": {
                        key: attribute_value_schema()
                        for key in allowed_attributes
                    },
                },
                "notes": {"type": "string"},
                "metadata": metadata_schema_for_type(entity_type),
            },
        },
    )


def attribute_value_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["value", "interval_95"],
        "properties": {
            "value": {"type": "number", "minimum": 0, "maximum": 1},
            "interval_95": {
                "type": "object",
                "additionalProperties": False,
                "required": ["lower", "upper"],
                "properties": {
                    "lower": {"type": "number", "minimum": 0, "maximum": 1},
                    "upper": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
    }


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


def filter_intent_attributes(intent: dict[str, Any]) -> dict[str, Any]:
    allowed = set(attribute_keys_for_type(intent.get("entity_type")))
    intent["attributes"] = [
        attribute
        for attribute in intent.get("attributes") or []
        if attribute in allowed
    ]
    intent["context"] = {
        key: bool(value)
        for key, value in (intent.get("context") or {}).items()
        if key in allowed and value
    }
    return intent


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


def metadata_schema_for_type(entity_type: str) -> dict[str, Any]:
    if entity_type in {"movie", "series"}:
        return media_metadata_schema()
    if entity_type == "music":
        return music_metadata_schema()
    return empty_metadata_schema()


def empty_metadata_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {},
    }


def music_metadata_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["artist", "album", "personnel", "genre"],
        "properties": {
            "artist": {"type": ["string", "null"]},
            "album": {"type": ["string", "null"]},
            "personnel": {"type": "array", "items": {"type": "string"}},
            "genre": {
                "type": "array",
                "items": {"type": "string", "enum": MUSIC_GENRES},
            },
        },
    }


def media_metadata_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "synopsis",
            "main_actors",
            "director",
            "country",
            "language",
            "genre",
            "runtime",
            "seasons",
            "watched",
            "watched_at",
            "external_ids",
            "external_ratings",
            "ratings_source",
        ],
        "properties": {
            "synopsis": {"type": ["string", "null"]},
            "main_actors": {"type": "array", "items": {"type": "string"}},
            "director": {"type": ["string", "null"]},
            "country": {"type": "array", "items": {"type": "string"}},
            "language": {"type": "array", "items": {"type": "string"}},
            "genre": {
                "type": "array",
                "items": {"type": "string", "enum": MEDIA_GENRES},
            },
            "runtime": {"type": ["integer", "null"], "minimum": 0},
            "seasons": {"type": ["integer", "null"], "minimum": 0},
            "watched": {"type": "boolean"},
            "watched_at": {"type": ["string", "null"]},
            "external_ids": {
                "type": "object",
                "additionalProperties": False,
                "required": ["imdb_id"],
                "properties": {"imdb_id": {"type": ["string", "null"]}},
            },
            "external_ratings": {
                "type": "object",
                "additionalProperties": False,
                "required": ["imdb", "rotten_tomatoes"],
                "properties": {
                    "imdb": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["rating", "votes"],
                        "properties": {
                            "rating": {"type": ["number", "null"]},
                            "votes": {"type": ["integer", "null"]},
                        },
                    },
                    "rotten_tomatoes": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["critic_score"],
                        "properties": {
                            "critic_score": {"type": ["integer", "null"]}
                        },
                    },
                },
            },
            "ratings_source": {
                "type": "object",
                "additionalProperties": False,
                "required": ["provider", "fetched_at"],
                "properties": {
                    "provider": {"type": ["string", "null"]},
                    "fetched_at": {"type": ["string", "null"]},
                },
            },
        },
    }
