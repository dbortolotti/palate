from __future__ import annotations

import re
from typing import Any

from .media import (
    external_rating_facts,
    external_rating_tiebreak,
    is_media_type,
    metadata_search_text,
)


def retrieve_candidates(
    store: Any,
    intent: dict[str, Any],
    extracted_entities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    extracted_entities = extracted_entities or []

    if extracted_entities:
        option_names = [
            item.get("canonical_name") or item.get("name") or str(item)
            for item in extracted_entities
        ]
        matched = store.match_entities_by_names(option_names)
        return {
            "candidates": filter_by_type(matched["matched"], intent.get("entity_type")),
            "unmatched_options": matched["unmatched"],
            "constrained_to_options": True,
        }

    typed = filter_by_type(store.list_entities(), intent.get("entity_type"))
    searched = apply_search_text(typed, intent.get("search_text", ""))
    return {
        "candidates": searched,
        "unmatched_options": [],
        "constrained_to_options": False,
    }


def rank_candidates(candidates: list[dict[str, Any]], intent: dict[str, Any]) -> list[dict[str, Any]]:
    avoid_below = (intent.get("filters") or {}).get("min_rating")
    recommended_by = (intent.get("filters") or {}).get("recommended_by")
    required = intent.get("attributes") or []
    context = intent.get("context") or {}
    search_text = intent.get("search_text") or ""

    results = []
    for entity in candidates:
        facts = score_entity(
            entity,
            required=required,
            context=context,
            avoid_below=avoid_below,
            recommended_by=recommended_by,
            search_text=search_text,
        )
        if not facts["excluded"]:
            results.append({"entity": entity, "score": facts["total"], "facts": facts})

    return sorted(
        results,
        key=lambda result: (
            result["score"],
            result["facts"].get("external_rating_tiebreak", 0.0),
        ),
        reverse=True,
    )


def score_entity(
    entity: dict[str, Any],
    *,
    required: list[str],
    context: dict[str, Any],
    avoid_below: float | None,
    recommended_by: str | None,
    search_text: str,
) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "preference": 0.0,
        "attribute_match": 0.0,
        "context_match": 0.0,
        "search_match": 0.0,
        "provenance": 0.0,
        "familiarity": 0.0,
        "external_rating_tiebreak": 0.0,
        "penalties": 0.0,
        "matched_attributes": [],
        "negative_signals": [],
        "signal_facts": [],
        "excluded": False,
        "total": 0.0,
    }
    matched_recommended_by = False

    for signal in entity.get("signals") or []:
        signal_type = signal.get("type")
        value = signal.get("value")

        if signal_type == "rating":
            try:
                rating = float(value)
            except (TypeError, ValueError):
                rating = None
            if rating is not None:
                facts["preference"] = max(facts["preference"], rating_preference(rating))
                facts["signal_facts"].append(f"rating {rating:g}/10")
                if avoid_below and rating < avoid_below:
                    facts["excluded"] = True
                    facts["negative_signals"].append(f"rating below {avoid_below:g}")

        if signal_type == "dislike":
            facts["penalties"] -= 1.5
            facts["negative_signals"].append(str(value))

        if signal_type == "recommended_by":
            matches_requested_person = bool(
                recommended_by and normalize(value) == normalize(recommended_by)
            )
            matched_recommended_by = matched_recommended_by or matches_requested_person
            facts["provenance"] += 0.6 if matches_requested_person else 0.25
            facts["signal_facts"].append(f"recommended by {value}")

        if signal_type == "saved":
            facts["familiarity"] += 0.15
            facts["signal_facts"].append("saved")

        if signal_type == "tried":
            facts["familiarity"] += 0.1
            fact = (
                "watched before"
                if is_media_type(entity.get("type"))
                else "tried before"
            )
            facts["signal_facts"].append(fact)

    if recommended_by and not matched_recommended_by:
        facts["excluded"] = True
        facts["negative_signals"].append(f"not recommended by {recommended_by}")

    for attr in required:
        value = float((entity.get("attributes") or {}).get(attr) or 0)
        if value > 0:
            facts["attribute_match"] += value
            facts["matched_attributes"].append(
                format_attribute_fact(entity, attr, value)
            )

    for key, wanted in context.items():
        value = float((entity.get("attributes") or {}).get(key) or 0)
        if wanted is True and value > 0:
            facts["context_match"] += value * 0.5
            facts["matched_attributes"].append(
                format_attribute_fact(entity, key, value, prefix="context ")
            )

    facts["search_match"] = score_text_match(entity, search_text)
    if facts["search_match"] > 0:
        facts["signal_facts"].append(f"matched memory text: {facts['search_match']:.2f}")

    rating_facts = external_rating_facts(entity.get("metadata") or {})
    facts["signal_facts"].extend(rating_facts)
    facts["external_rating_tiebreak"] = external_rating_tiebreak(
        entity.get("metadata") or {}
    )

    facts["total"] = round(
        facts["preference"] * 1.4
        + facts["attribute_match"]
        + facts["context_match"]
        + facts["search_match"]
        + facts["provenance"]
        + facts["familiarity"]
        + facts["penalties"],
        2,
    )
    return facts


def build_grounding(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": result["entity"]["id"],
            "name": result["entity"]["canonical_name"],
            "type": result["entity"]["type"],
            "score": result["score"],
            "matched_attributes": result["facts"]["matched_attributes"],
            "attribute_intervals_95": result["entity"].get("attribute_intervals_95") or {},
            "attribute_details": result["entity"].get("attribute_details") or {},
            "signal_facts": result["facts"]["signal_facts"],
            "negative_signals": result["facts"]["negative_signals"],
            "metadata": result["entity"].get("metadata") or {},
        }
        for result in results[:5]
    ]


def filter_by_type(entities: list[dict[str, Any]], entity_type: str | None) -> list[dict[str, Any]]:
    if not entity_type:
        return entities
    return [entity for entity in entities if entity["type"] == entity_type]


def apply_search_text(entities: list[dict[str, Any]], search_text: str) -> list[dict[str, Any]]:
    if not tokenize(search_text):
        return entities

    matches = [entity for entity in entities if score_text_match(entity, search_text) > 0]
    return matches or entities


def score_text_match(entity: dict[str, Any], search_text: str) -> float:
    tokens = tokenize(search_text)
    if not tokens:
        return 0.0

    attributes = " ".join(
        key
        for key, value in (entity.get("attributes") or {}).items()
        if float(value) > 0.55
    )
    signals = " ".join(
        f"{signal.get('type')} {signal.get('value')} {signal.get('provenance') or ''}"
        for signal in entity.get("signals") or []
    )
    haystack = normalize(
        " ".join(
            str(part)
            for part in [
                entity.get("canonical_name"),
                entity.get("source_text"),
                entity.get("notes"),
                metadata_search_text(entity.get("metadata") or {}),
                attributes,
                signals,
            ]
            if part
        )
    )
    matched = [token for token in tokens if token in haystack]
    return len(matched) / len(tokens)


def tokenize(value: str) -> list[str]:
    return [
        token
        for token in normalize(value).split()
        if len(token) > 2 and token not in STOP_WORDS
    ]


def normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def format_attribute_fact(
    entity: dict[str, Any],
    key: str,
    value: float,
    *,
    prefix: str = "",
) -> str:
    interval = (entity.get("attribute_intervals_95") or {}).get(key) or {
        "lower": value,
        "upper": value,
    }
    lower = float(interval.get("lower", value))
    upper = float(interval.get("upper", value))
    return f"{prefix}{key}: {value:.2f} (95% interval {lower:.2f}-{upper:.2f})"


def rating_preference(rating: float) -> float:
    # Preserves old 1-5 behavior after migration:
    # 2/4/6/8/10 map to -1/-0.5/0/0.5/1.
    return max(-1.0, min(1.0, (rating - 6) / 4))


STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "what",
    "which",
    "thing",
    "things",
    "place",
    "places",
    "something",
}
