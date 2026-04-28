from __future__ import annotations

from typing import Any, Literal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .core import build_grounding, rank_candidates, retrieve_candidates
from .llm import explain_results, extract_entities, normalize_enrichment, parse_intent
from .schema import ENTITY_TYPES
from .storage import open_store


load_dotenv()

store = open_store()
mcp = FastMCP("palate")
EntityType = Literal["wine", "restaurant", "music", "cigar", "experience"]


@mcp.tool()
def palate_query(
    query: str,
    context: dict[str, Any] | None = None,
    options_text: str | None = None,
    explain: bool = True,
) -> dict[str, Any]:
    """Interpret a taste query, rank matching memory deterministically, and explain results."""
    context = context or {}
    intent = parse_intent(query, context)
    extraction = (
        extract_entities(options_text, intent.get("entity_type"))
        if options_text
        else {"entities": []}
    )

    retrieval = retrieve_candidates(
        store,
        intent,
        extraction["entities"],
    )
    ranked = rank_candidates(retrieval["candidates"], intent)
    grounding = build_grounding(ranked)
    explanation = explain_results(query, intent, grounding) if explain else None

    decision_id = store.log_decision(
        query=query,
        context=context,
        options=extraction["entities"],
        ranked=grounding,
    )

    return {
        "decision_id": decision_id,
        "intent": intent,
        "extracted_entities": extraction["entities"],
        "retrieval": describe_retrieval(retrieval),
        "ranked_results": grounding,
        "explanation": explanation,
    }


@mcp.tool()
def palate_evaluate_options(
    query: str,
    options_text: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract entities from a pasted option set, then rank known matching options."""
    context = context or {}
    intent = parse_intent(query, context)
    extraction = extract_entities(options_text, intent.get("entity_type"))
    retrieval = retrieve_candidates(store, intent, extraction["entities"])
    ranked = rank_candidates(retrieval["candidates"], intent)
    grounding = build_grounding(ranked)
    explanation = explain_results(query, intent, grounding)

    decision_id = store.log_decision(
        query=query,
        context=context,
        options=extraction["entities"],
        ranked=grounding,
    )

    return {
        "decision_id": decision_id,
        "intent": intent,
        "extracted_entities": extraction["entities"],
        "retrieval": describe_retrieval(retrieval),
        "ranked_results": grounding,
        "explanation": explanation,
    }


@mcp.tool()
def palate_remember(
    id: str,
    type: EntityType,
    canonical_name: str,
    description: str | None = None,
    attributes: dict[str, float] | None = None,
    rating: float | None = None,
    recommended_by: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Store an explicit Palate memory and optionally normalize raw description text."""
    if type not in ENTITY_TYPES:
        raise ValueError(f"type must be one of: {', '.join(ENTITY_TYPES)}")

    enrichment = (
        normalize_enrichment(description, type)
        if description
        else {"attributes": {}, "notes": ""}
    )

    signals = []
    if rating is not None:
        signals.append({"type": "rating", "value": rating})
    if recommended_by:
        signals.append({"type": "recommended_by", "value": recommended_by})

    store.upsert_entity(
        {
            "id": id,
            "type": type,
            "canonical_name": canonical_name,
            "source_text": description,
            "notes": notes if notes is not None else enrichment["notes"],
            "attributes": {**enrichment["attributes"], **(attributes or {})},
            "signals": signals,
        }
    )

    return {
        "stored": True,
        "id": id,
        "normalized_attributes": enrichment["attributes"],
    }


@mcp.tool()
def palate_recall(
    query: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recall explicit Palate memory using LLM interpretation and deterministic ranking."""
    context = context or {}
    intent = parse_intent(query, context)
    retrieval = retrieve_candidates(store, intent)
    ranked = rank_candidates(retrieval["candidates"], intent)
    grounding = build_grounding(ranked)
    return {
        "intent": intent,
        "retrieval": describe_retrieval(retrieval),
        "results": grounding,
    }


@mcp.tool()
def palate_enrich_item(item_text: str, entity_type: EntityType) -> dict[str, Any]:
    """Normalize noisy item text into Palate's fixed attribute schema."""
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity_type must be one of: {', '.join(ENTITY_TYPES)}")
    return normalize_enrichment(item_text, entity_type)


@mcp.tool()
def palate_log_decision(
    chosen_entity_id: str,
    decision_id: int | None = None,
    query: str = "",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record what the user chose after a recommendation or evaluation."""
    updated_existing_decision = False

    if decision_id is not None:
        changes = store.update_decision_choice(decision_id, chosen_entity_id)
        if changes == 0:
            return {
                "logged": False,
                "error": f"No decision found for decision_id {decision_id}.",
            }
        new_decision_id = decision_id
        updated_existing_decision = True
    else:
        new_decision_id = store.log_decision(
            query=query,
            context=context or {},
            options=[],
            ranked=[],
            chosen_entity_id=chosen_entity_id,
        )

    store.add_signal(chosen_entity_id, "chosen", True)
    return {
        "logged": True,
        "decision_id": new_decision_id,
        "chosen_entity_id": chosen_entity_id,
        "updated_existing_decision": updated_existing_decision,
    }


def describe_retrieval(retrieval: dict[str, Any]) -> dict[str, Any]:
    return {
        "constrained_to_options": retrieval["constrained_to_options"],
        "unmatched_options": retrieval["unmatched_options"],
        "candidate_count": len(retrieval["candidates"]),
        "matched_candidates": [
            {
                "id": entity["id"],
                "name": entity["canonical_name"],
                "type": entity["type"],
            }
            for entity in retrieval["candidates"]
        ],
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
