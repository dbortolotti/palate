from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .backup import backup_once, start_backup_scheduler
from .core import build_grounding, rank_candidates, retrieve_candidates
from .llm import explain_results, extract_entities, normalize_enrichment, parse_intent
from .media import (
    is_media_type,
    is_music_type,
    merge_media_metadata,
    merge_music_metadata,
    normalize_media_metadata,
    normalize_music_metadata,
    set_media_field,
    set_music_field,
)
from .oauth import build_auth_components, register_auth_routes
from .omdb import fetch_omdb_metadata
from .schema import ENTITY_TYPES, attribute_keys_for_type
from .storage import attribute_interval_95, attribute_value, open_store


load_dotenv()

store = open_store()
auth_settings, auth_provider = build_auth_components()
mcp = FastMCP(
    "palate",
    auth=auth_settings,
    auth_server_provider=auth_provider,
    host=os.getenv("PALATE_HOST", "127.0.0.1"),
    port=int(os.getenv("PALATE_PORT", "8000")),
    streamable_http_path=os.getenv("PALATE_MCP_PATH", "/mcp"),
    transport_security=TransportSecuritySettings(
        allowed_hosts=[
            host
            for host in os.getenv(
                "PALATE_ALLOWED_HOSTS",
                "127.0.0.1,127.0.0.1:8000,localhost,localhost:8000",
            ).split(",")
            if host
        ],
        allowed_origins=[
            origin
            for origin in os.getenv("PALATE_ALLOWED_ORIGINS", "").split(",")
            if origin
        ],
    ),
)
if auth_provider:
    register_auth_routes(mcp, auth_provider)
EntityType = Literal[
    "wine",
    "restaurant",
    "music",
    "cigar",
    "experience",
    "movie",
    "series",
]
USER_GUIDE_PATH = Path(__file__).resolve().parents[1] / "USER-GUIDE.md"


@mcp.tool()
def palate_how_to() -> dict[str, Any]:
    """Return the Palate user guide with prompt patterns for client LLMs."""
    return {
        "title": "Palate User Guide",
        "mime_type": "text/markdown",
        "content": read_user_guide(),
    }


@mcp.resource(
    "palate://how-to",
    name="palate_how_to",
    title="Palate User Guide",
    description="How to prompt a client LLM to use Palate's supported tasks.",
    mime_type="text/markdown",
)
def palate_how_to_resource() -> str:
    """Expose the Palate user guide as an MCP resource."""
    return read_user_guide()


@mcp.tool()
def palate_backup_now() -> dict[str, Any]:
    """Create an immediate SQLite and JSON backup, then clean up expired backups."""
    return backup_once()


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
    description: str,
    attributes: dict[str, Any] | None = None,
    attribute_intervals_95: dict[str, dict[str, float]] | None = None,
    rating: float | None = None,
    tried: bool | None = None,
    recommended_by: str | None = None,
    notes: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    personnel: list[str] | None = None,
    synopsis: str | None = None,
    main_actors: list[str] | None = None,
    director: str | None = None,
    country: list[str] | None = None,
    language: list[str] | None = None,
    genre: list[str] | None = None,
    runtime: int | None = None,
    seasons: int | None = None,
    watched: bool | None = None,
    watched_at: str | None = None,
    imdb_id: str | None = None,
    fetch_external_ratings: bool = True,
) -> dict[str, Any]:
    """Store memory; ask one 1-10 rating question, accepting "no" if not tried/watched."""
    memory = compute_memory_payload(
        type=type,
        canonical_name=canonical_name,
        description=description,
        rating=rating,
        tried=tried,
        recommended_by=recommended_by,
        notes=notes,
        artist=artist,
        album=album,
        personnel=personnel,
        synopsis=synopsis,
        main_actors=main_actors,
        director=director,
        country=country,
        language=language,
        genre=genre,
        runtime=runtime,
        seasons=seasons,
        watched=watched,
        watched_at=watched_at,
        imdb_id=imdb_id,
        fetch_external_ratings=fetch_external_ratings,
    )

    record = {"id": id, **memory["record"]}
    store.upsert_entity(record)

    return {
        "stored": True,
        "id": id,
        "normalized_attributes": memory["normalized_attributes"],
        "normalized_attribute_intervals_95": memory[
            "normalized_attribute_intervals_95"
        ],
        "metadata": memory["record"]["metadata"],
        "warnings": memory["warnings"],
    }


@mcp.tool()
def palate_lookup(
    type: EntityType,
    canonical_name: str,
    description: str,
    do_not_store: bool,
    rating: float | None = None,
    tried: bool | None = None,
    recommended_by: str | None = None,
    notes: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    personnel: list[str] | None = None,
    synopsis: str | None = None,
    main_actors: list[str] | None = None,
    director: str | None = None,
    country: list[str] | None = None,
    language: list[str] | None = None,
    genre: list[str] | None = None,
    runtime: int | None = None,
    seasons: int | None = None,
    watched: bool | None = None,
    watched_at: str | None = None,
    imdb_id: str | None = None,
    fetch_external_ratings: bool = True,
) -> dict[str, Any]:
    """Compute a Palate memory preview without storing; call only when the user explicitly says not to store."""
    if do_not_store is not True:
        raise ValueError(
            "palate_lookup requires do_not_store=true and should only be used "
            "when the user explicitly says not to store the result."
        )

    memory = compute_memory_payload(
        type=type,
        canonical_name=canonical_name,
        description=description,
        rating=rating,
        tried=tried,
        recommended_by=recommended_by,
        notes=notes,
        artist=artist,
        album=album,
        personnel=personnel,
        synopsis=synopsis,
        main_actors=main_actors,
        director=director,
        country=country,
        language=language,
        genre=genre,
        runtime=runtime,
        seasons=seasons,
        watched=watched,
        watched_at=watched_at,
        imdb_id=imdb_id,
        fetch_external_ratings=fetch_external_ratings,
    )

    return {
        "stored": False,
        "record": memory["record"],
        "normalized_attributes": memory["normalized_attributes"],
        "normalized_attribute_intervals_95": memory[
            "normalized_attribute_intervals_95"
        ],
        "warnings": memory["warnings"],
    }


def compute_memory_payload(
    *,
    type: EntityType,
    canonical_name: str,
    description: str,
    rating: float | None,
    tried: bool | None,
    recommended_by: str | None,
    notes: str | None,
    artist: str | None,
    album: str | None,
    personnel: list[str] | None,
    synopsis: str | None,
    main_actors: list[str] | None,
    director: str | None,
    country: list[str] | None,
    language: list[str] | None,
    genre: list[str] | None,
    runtime: int | None,
    seasons: int | None,
    watched: bool | None,
    watched_at: str | None,
    imdb_id: str | None,
    fetch_external_ratings: bool,
) -> dict[str, Any]:
    if type not in ENTITY_TYPES:
        raise ValueError(f"type must be one of: {', '.join(ENTITY_TYPES)}")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description is required and must not be blank.")
    description = description.strip()
    if rating is not None:
        try:
            rating = float(rating)
        except (TypeError, ValueError):
            raise ValueError("rating must be a number between 1 and 10.") from None
        if not 1 <= rating <= 10:
            raise ValueError("rating must be between 1 and 10.")
    validate_experience_signal(
        entity_type=type,
        rating=rating,
        tried=tried,
        watched=watched,
        watched_at=watched_at,
    )
    enrichment = normalize_enrichment(description, type)
    allowed_attributes = set(attribute_keys_for_type(type))
    normalized_attribute_payload = {
        key: value
        for key, value in (enrichment.get("attributes") or {}).items()
        if key in allowed_attributes
    }
    normalized_attributes = {
        key: attribute_value(value)
        for key, value in normalized_attribute_payload.items()
    }
    normalized_attribute_intervals_95 = {
        key: attribute_interval_95(value)
        for key, value in normalized_attribute_payload.items()
    }
    metadata, metadata_warnings = prepare_entity_metadata(
        entity_type=type,
        canonical_name=canonical_name,
        enrichment_metadata=enrichment.get("metadata") or {},
        rating=rating,
        artist=artist,
        album=album,
        personnel=personnel,
        synopsis=synopsis,
        main_actors=main_actors,
        director=director,
        country=country,
        language=language,
        genre=genre,
        runtime=runtime,
        seasons=seasons,
        watched=watched,
        watched_at=watched_at,
        imdb_id=imdb_id,
        fetch_external_ratings=fetch_external_ratings,
    )

    signals = []
    if rating is not None:
        signals.append({"type": "rating", "value": rating})
    if should_store_tried_signal(
        entity_type=type,
        rating=rating,
        tried=tried,
        watched=watched,
        watched_at=watched_at,
    ):
        signals.append({"type": "tried", "value": True})
    if recommended_by:
        signals.append({"type": "recommended_by", "value": recommended_by})

    return {
        "record": {
            "type": type,
            "canonical_name": canonical_name,
            "source_text": description,
            "notes": notes if notes is not None else enrichment["notes"],
            "metadata": metadata,
            "attributes": normalized_attributes,
            "attribute_intervals_95": normalized_attribute_intervals_95,
            "signals": signals,
        },
        "normalized_attributes": normalized_attributes,
        "normalized_attribute_intervals_95": normalized_attribute_intervals_95,
        "warnings": metadata_warnings,
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
def palate_delete_record(id: str) -> dict[str, Any]:
    """Delete one explicit Palate memory by exact entity id."""
    deleted = store.delete_entity(id)
    if deleted is None:
        return {
            "deleted": False,
            "id": id,
            "error": f"No Palate record found for id {id}.",
        }

    return {
        "deleted": True,
        "id": id,
        "record": {
            "id": deleted["id"],
            "name": deleted["canonical_name"],
            "type": deleted["type"],
        },
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


def prepare_entity_metadata(
    *,
    entity_type: str,
    canonical_name: str,
    enrichment_metadata: dict[str, Any],
    rating: float | None,
    artist: str | None,
    album: str | None,
    personnel: list[str] | None,
    synopsis: str | None,
    main_actors: list[str] | None,
    director: str | None,
    country: list[str] | None,
    language: list[str] | None,
    genre: list[str] | None,
    runtime: int | None,
    seasons: int | None,
    watched: bool | None,
    watched_at: str | None,
    imdb_id: str | None,
    fetch_external_ratings: bool,
) -> tuple[dict[str, Any], list[str]]:
    if is_music_type(entity_type):
        return prepare_music_metadata(
            enrichment_metadata=enrichment_metadata,
            artist=artist,
            album=album,
            personnel=personnel,
            genre=genre,
        )

    return prepare_media_metadata(
        entity_type=entity_type,
        canonical_name=canonical_name,
        enrichment_metadata=enrichment_metadata,
        rating=rating,
        synopsis=synopsis,
        main_actors=main_actors,
        director=director,
        country=country,
        language=language,
        genre=genre,
        runtime=runtime,
        seasons=seasons,
        watched=watched,
        watched_at=watched_at,
        imdb_id=imdb_id,
        fetch_external_ratings=fetch_external_ratings,
    )


def validate_experience_signal(
    *,
    entity_type: str,
    rating: float | None,
    tried: bool | None,
    watched: bool | None,
    watched_at: str | None,
) -> None:
    has_media_experience = is_media_type(entity_type) and (
        watched is True or watched_at is not None
    )
    has_generic_experience = tried is True
    if rating is None and (has_media_experience or has_generic_experience):
        experience = "watched" if has_media_experience else "tried"
        raise ValueError(f"rating is required when {experience} is true.")
    if rating is not None and tried is False:
        raise ValueError("tried cannot be false when rating is provided.")
    if rating is not None and is_media_type(entity_type) and watched is False:
        raise ValueError("watched cannot be false when rating is provided.")


def should_store_tried_signal(
    *,
    entity_type: str,
    rating: float | None,
    tried: bool | None,
    watched: bool | None,
    watched_at: str | None,
) -> bool:
    if tried is True:
        return True
    if rating is not None:
        return True
    return is_media_type(entity_type) and (watched is True or watched_at is not None)


def prepare_music_metadata(
    *,
    enrichment_metadata: dict[str, Any],
    artist: str | None,
    album: str | None,
    personnel: list[str] | None,
    genre: list[str] | None,
) -> tuple[dict[str, Any], list[str]]:
    metadata = normalize_music_metadata(enrichment_metadata)
    manual_paths: set[tuple[str, ...]] = set()

    def apply_manual(path: tuple[str, ...], value: Any) -> None:
        nonlocal metadata
        if value is None:
            return
        metadata = set_music_field(metadata, path, value)
        manual_paths.add(path)

    apply_manual(("artist",), artist)
    apply_manual(("album",), album)
    apply_manual(("personnel",), personnel)
    apply_manual(("genre",), genre)

    return merge_music_metadata(metadata, {}, protected_paths=manual_paths), []


def prepare_media_metadata(
    *,
    entity_type: str,
    canonical_name: str,
    enrichment_metadata: dict[str, Any],
    rating: float | None,
    synopsis: str | None,
    main_actors: list[str] | None,
    director: str | None,
    country: list[str] | None,
    language: list[str] | None,
    genre: list[str] | None,
    runtime: int | None,
    seasons: int | None,
    watched: bool | None,
    watched_at: str | None,
    imdb_id: str | None,
    fetch_external_ratings: bool,
) -> tuple[dict[str, Any], list[str]]:
    if not is_media_type(entity_type):
        return {}, []

    metadata = normalize_media_metadata(enrichment_metadata)
    manual_paths: set[tuple[str, ...]] = set()

    def apply_manual(path: tuple[str, ...], value: Any) -> None:
        nonlocal metadata
        if value is None:
            return
        metadata = set_media_field(metadata, path, value)
        manual_paths.add(path)

    apply_manual(("synopsis",), synopsis)
    apply_manual(("main_actors",), main_actors)
    apply_manual(("director",), director)
    apply_manual(("country",), country)
    apply_manual(("language",), language)
    apply_manual(("genre",), genre)
    apply_manual(("runtime",), runtime)
    apply_manual(("seasons",), seasons)
    apply_manual(("watched",), watched)
    apply_manual(("watched_at",), watched_at)
    apply_manual(("external_ids", "imdb_id"), imdb_id)

    if watched_at is not None and watched is None:
        metadata = set_media_field(metadata, ("watched",), True)
        manual_paths.add(("watched",))

    if rating is not None:
        metadata = set_media_field(metadata, ("watched",), True)
        manual_paths.add(("watched",))

    warnings = []
    if fetch_external_ratings:
        lookup = fetch_omdb_metadata(
            title=canonical_name,
            entity_type=entity_type,
            imdb_id=metadata["external_ids"].get("imdb_id"),
        )
        warnings.extend(lookup["warnings"])
        metadata = merge_media_metadata(
            metadata,
            lookup["metadata"],
            protected_paths=manual_paths,
        )

    return metadata, warnings


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


def read_user_guide() -> str:
    return USER_GUIDE_PATH.read_text(encoding="utf-8")


def main() -> None:
    transport = os.getenv("PALATE_TRANSPORT", "stdio")
    if transport not in {"stdio", "sse", "streamable-http"}:
        raise ValueError("PALATE_TRANSPORT must be one of: stdio, sse, streamable-http")
    start_backup_scheduler()
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
