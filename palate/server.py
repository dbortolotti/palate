from __future__ import annotations

from functools import wraps
import inspect
import os
from pathlib import Path
import time
from typing import Any, Literal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from .backup import backup_once, start_backup_scheduler
from .core import build_grounding, rank_candidates, retrieve_candidates
from .llm import (
    explain_results,
    extract_entities,
    normalize_enrichment,
    normalize_restaurant_enrichment,
    parse_intent,
)
from .media import (
    is_media_type,
    is_music_type,
    is_restaurant_type,
    merge_media_metadata,
    merge_music_metadata,
    merge_restaurant_metadata,
    normalize_media_metadata,
    normalize_music_metadata,
    normalize_restaurant_genres,
    normalize_restaurant_metadata,
    set_media_field,
    set_music_field,
    set_restaurant_field,
)
from .oauth import build_auth_components, register_auth_routes
from .omdb import fetch_omdb_metadata
from .schema import ENTITY_TYPES, INTENTS, attribute_keys_for_type
from .storage import (
    attribute_interval_95,
    attribute_value,
    clamp01,
    name_match_confidence,
    normalize_name_for_match,
    open_store,
)


load_dotenv(os.getenv("PALATE_ENV_PATH"))

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


def logged_tool(func):
    """Record structured tool inputs, outputs, errors, and latency for evals."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        inputs = bind_tool_inputs(func, args, kwargs)
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            safe_log_application_event(
                tool_name=func.__name__,
                status="error",
                duration_ms=duration_ms,
                inputs=inputs,
                error={
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        safe_log_application_event(
            tool_name=func.__name__,
            status="success",
            duration_ms=duration_ms,
            inputs=inputs,
            output=loggable_tool_output(func.__name__, result),
            metadata=tool_log_metadata(result),
        )
        return result

    return wrapper


def bind_tool_inputs(func, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    signature = inspect.signature(func)
    bound = signature.bind_partial(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def safe_log_application_event(
    *,
    tool_name: str,
    status: str,
    duration_ms: float,
    inputs: dict[str, Any],
    output: Any | None = None,
    error: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        store.log_application_event(
            tool_name=tool_name,
            status=status,
            duration_ms=duration_ms,
            inputs=inputs,
            output=output,
            error=error,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001 - logging must not break tool calls.
        print(f"Palate application logging failed: {exc}", flush=True)


def loggable_tool_output(tool_name: str, result: Any) -> Any:
    if tool_name == "palate_how_to" and isinstance(result, dict):
        content = result.get("content") or ""
        return {
            "title": result.get("title"),
            "mime_type": result.get("mime_type"),
            "content_length": len(content),
        }
    return result


def tool_log_metadata(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    metadata: dict[str, Any] = {}
    for key in (
        "stored",
        "source",
        "found_existing",
        "decision_id",
        "deleted",
        "logged",
        "updated_existing_decision",
    ):
        if key in result:
            metadata[key] = result[key]
    if "server_llm_used" in result:
        metadata["server_llm_used"] = result["server_llm_used"]
    if "ranked_results" in result:
        metadata["ranked_count"] = len(result.get("ranked_results") or [])
    if "results" in result:
        metadata["result_count"] = len(result.get("results") or [])
    retrieval = result.get("retrieval")
    if isinstance(retrieval, dict):
        metadata["candidate_count"] = retrieval.get("candidate_count")
        metadata["unmatched_option_count"] = len(retrieval.get("unmatched_options") or [])
        metadata["needs_confirmation_count"] = len(retrieval.get("needs_confirmation") or [])
    return metadata


@mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
async def healthz(_request: Request) -> JSONResponse:
    """Return a lightweight readiness signal for local deployment checks."""
    try:
        store.conn.execute("SELECT 1").fetchone()
    except Exception as exc:  # noqa: BLE001 - deployment health should report any failure.
        return JSONResponse(
            {"status": "error", "database": "unavailable", "error": str(exc)},
            status_code=503,
        )

    return JSONResponse({"status": "ok", "database": "ok"})


@mcp.tool()
@logged_tool
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
@logged_tool
def palate_backup_now() -> dict[str, Any]:
    """Create an immediate SQLite and JSON backup, then clean up expired backups."""
    return backup_once()


@mcp.tool()
@logged_tool
def palate_query(
    query: str,
    context: dict[str, Any] | None = None,
    options_text: str | None = None,
    explain: bool = False,
    intent: dict[str, Any] | None = None,
    extracted_entities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Recommend or rank saved Palate memories for an open-ended taste query."""
    context = context or {}
    intent, parsed_intent_with_llm = resolve_intent(query, context, intent)
    extraction, extracted_with_llm = resolve_extraction(
        options_text,
        intent.get("entity_type"),
        extracted_entities,
    )

    retrieval = retrieve_candidates(
        store,
        intent,
        extraction["entities"],
    )
    decision_feedback = store.decision_feedback(
        query,
        [entity["id"] for entity in retrieval["candidates"]],
    )
    ranked = rank_candidates(
        retrieval["candidates"],
        intent,
        decision_feedback=decision_feedback,
    )
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
        "server_llm_used": {
            "intent": parsed_intent_with_llm,
            "entity_extraction": extracted_with_llm,
            "explanation": bool(explain),
        },
    }


@mcp.tool()
@logged_tool
def palate_evaluate_options(
    query: str,
    options_text: str,
    context: dict[str, Any] | None = None,
    explain: bool = False,
    intent: dict[str, Any] | None = None,
    extracted_entities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rank only the pasted/provided options against saved Palate memories."""
    context = context or {}
    intent, parsed_intent_with_llm = resolve_intent(query, context, intent)
    extraction, extracted_with_llm = resolve_extraction(
        options_text,
        intent.get("entity_type"),
        extracted_entities,
    )
    retrieval = retrieve_candidates(store, intent, extraction["entities"])
    decision_feedback = store.decision_feedback(
        query,
        [entity["id"] for entity in retrieval["candidates"]],
    )
    ranked = rank_candidates(
        retrieval["candidates"],
        intent,
        decision_feedback=decision_feedback,
    )
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
        "server_llm_used": {
            "intent": parsed_intent_with_llm,
            "entity_extraction": extracted_with_llm,
            "explanation": bool(explain),
        },
    }


@mcp.tool()
@logged_tool
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
    cuisine: dict[str, Any] | list[str] | None = None,
    michelin_status: str | None = None,
    michelin_url: str | None = None,
    michelin_green_star: bool | None = None,
    google_rating: float | None = None,
    google_rating_count: int | None = None,
    google_url: str | None = None,
    runtime: int | None = None,
    seasons: int | None = None,
    watched: bool | None = None,
    watched_at: str | None = None,
    imdb_id: str | None = None,
    fetch_external_ratings: bool = True,
) -> dict[str, Any]:
    """Store a taste memory only when the user asks to remember/save it."""
    memory = compute_memory_payload(
        type=type,
        canonical_name=canonical_name,
        description=description,
        attributes=attributes,
        attribute_intervals_95=attribute_intervals_95,
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
        cuisine=cuisine,
        michelin_status=michelin_status,
        michelin_url=michelin_url,
        michelin_green_star=michelin_green_star,
        google_rating=google_rating,
        google_rating_count=google_rating_count,
        google_url=google_url,
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
        "normalized_attribute_intervals_1sigma": memory[
            "normalized_attribute_intervals_1sigma"
        ],
        "metadata": memory["record"]["metadata"],
        "sources": memory["sources"],
        "server_llm_used": memory["server_llm_used"],
        "warnings": memory["warnings"],
    }


@mcp.tool()
@logged_tool
def palate_describe_item(
    item_text: str,
    entity_type: EntityType,
    canonical_name: str | None = None,
    attributes: dict[str, Any] | None = None,
    attribute_intervals_95: dict[str, dict[str, float]] | None = None,
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
    cuisine: dict[str, Any] | list[str] | None = None,
    michelin_status: str | None = None,
    michelin_url: str | None = None,
    michelin_green_star: bool | None = None,
    google_rating: float | None = None,
    google_rating_count: int | None = None,
    google_url: str | None = None,
    runtime: int | None = None,
    seasons: int | None = None,
    imdb_id: str | None = None,
    fetch_external_ratings: bool = True,
) -> dict[str, Any]:
    """Tell about an item without storing, even when the user says do not save."""
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity_type must be one of: {', '.join(ENTITY_TYPES)}")
    if not isinstance(item_text, str) or not item_text.strip():
        raise ValueError("item_text is required and must not be blank.")

    description = item_text.strip()
    name = (canonical_name or description).strip()
    if not name:
        raise ValueError("canonical_name must not be blank when provided.")

    existing = match_existing_memory(name, entity_type)
    if existing["record"] is not None:
        return {
            "stored": False,
            "source": "memory",
            "found_existing": True,
            "record": existing["record"],
            "match": existing["match"],
            "needs_confirmation": [],
            "enriched": None,
            "suggested_remember": None,
            "ask_user": None,
            "server_llm_used": {"enrichment": False},
            "warnings": [],
        }

    if existing["needs_confirmation"]:
        return {
            "stored": False,
            "source": "memory_confirmation_required",
            "found_existing": False,
            "record": None,
            "match": None,
            "needs_confirmation": existing["needs_confirmation"],
            "enriched": None,
            "suggested_remember": None,
            "ask_user": (
                "I found a possible existing Palate memory, but the name match is "
                "below 85%. Confirm the match before using or updating it."
            ),
            "server_llm_used": {"enrichment": False},
            "warnings": [],
        }

    memory = compute_memory_payload(
        type=entity_type,
        canonical_name=name,
        description=description,
        attributes=attributes,
        attribute_intervals_95=attribute_intervals_95,
        rating=None,
        tried=None,
        recommended_by=None,
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
        cuisine=cuisine,
        michelin_status=michelin_status,
        michelin_url=michelin_url,
        michelin_green_star=michelin_green_star,
        google_rating=google_rating,
        google_rating_count=google_rating_count,
        google_url=google_url,
        runtime=runtime,
        seasons=seasons,
        watched=None,
        watched_at=None,
        imdb_id=imdb_id,
        fetch_external_ratings=fetch_external_ratings,
    )
    suggested_arguments = remember_arguments_from_memory(
        suggested_id=suggest_entity_id(entity_type, name),
        memory=memory,
    )

    return {
        "stored": False,
        "source": "enrichment",
        "found_existing": False,
        "record": None,
        "match": None,
        "needs_confirmation": [],
        "enriched": memory["record"],
        "normalized_attributes": memory["normalized_attributes"],
        "normalized_attribute_intervals_95": memory[
            "normalized_attribute_intervals_95"
        ],
        "normalized_attribute_intervals_1sigma": memory[
            "normalized_attribute_intervals_1sigma"
        ],
        "suggested_remember": {
            "tool": "palate_remember",
            "arguments": suggested_arguments,
        },
        "sources": memory["sources"],
        "ask_user": "No matching Palate memory was found. Ask whether to remember this item.",
        "server_llm_used": memory["server_llm_used"],
        "warnings": memory["warnings"],
    }


def compute_memory_payload(
    *,
    type: EntityType,
    canonical_name: str,
    description: str,
    attributes: dict[str, Any] | None,
    attribute_intervals_95: dict[str, dict[str, float]] | None,
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
    cuisine: dict[str, Any] | list[str] | None,
    michelin_status: str | None,
    michelin_url: str | None,
    michelin_green_star: bool | None,
    google_rating: float | None,
    google_rating_count: int | None,
    google_url: str | None,
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
    enrichment, used_server_enrichment = resolve_enrichment(
        entity_type=type,
        attributes=attributes,
        attribute_intervals_95=attribute_intervals_95,
        description=description,
    )
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
    normalized_attribute_intervals_1sigma = normalize_attribute_intervals_1sigma(
        normalized_attribute_payload,
    )
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
        cuisine=cuisine,
        michelin_status=michelin_status,
        michelin_url=michelin_url,
        michelin_green_star=michelin_green_star,
        google_rating=google_rating,
        google_rating_count=google_rating_count,
        google_url=google_url,
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
            "notes": notes if notes is not None else enrichment.get("notes", description),
            "metadata": metadata,
            "attributes": normalized_attributes,
            "attribute_intervals_95": normalized_attribute_intervals_95,
            "signals": signals,
        },
        "normalized_attributes": normalized_attributes,
        "normalized_attribute_intervals_95": normalized_attribute_intervals_95,
        "normalized_attribute_intervals_1sigma": normalized_attribute_intervals_1sigma,
        "sources": enrichment.get("sources") or [],
        "server_llm_used": {"enrichment": used_server_enrichment},
        "warnings": metadata_warnings,
    }


def resolve_intent(
    query: str,
    context: dict[str, Any],
    supplied_intent: dict[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    if supplied_intent:
        return normalize_supplied_intent(supplied_intent), False
    return parse_intent(query, context), True


def normalize_supplied_intent(intent: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(intent, dict):
        raise ValueError("intent must be an object when provided.")
    entity_type = intent.get("entity_type")
    if entity_type not in ENTITY_TYPES:
        entity_type = None
    allowed_attributes = set(attribute_keys_for_type(entity_type))
    filters = intent.get("filters") if isinstance(intent.get("filters"), dict) else {}
    min_rating = filters.get("min_rating")
    if min_rating is not None:
        min_rating = float(min_rating)
        if not 1 <= min_rating <= 10:
            min_rating = None

    return {
        "intent": intent.get("intent") if intent.get("intent") in INTENTS else "hybrid_query",
        "attributes": [
            attribute
            for attribute in intent.get("attributes") or []
            if attribute in allowed_attributes
        ],
        "context": {
            key: bool(value)
            for key, value in (intent.get("context") or {}).items()
            if key in allowed_attributes and value
        },
        "filters": {
            "min_rating": min_rating,
            "recommended_by": filters.get("recommended_by"),
            "cuisine": (
                normalize_restaurant_genres(filters.get("cuisine", []))
                if entity_type == "restaurant"
                else []
            ),
        },
        "entity_type": entity_type,
        "search_text": str(intent.get("search_text") or ""),
    }


def resolve_extraction(
    options_text: str | None,
    expected_type: str | None,
    supplied_entities: list[dict[str, Any]] | None,
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    if supplied_entities is not None:
        return {"entities": normalize_supplied_entities(supplied_entities, expected_type)}, False
    if options_text:
        return extract_entities(options_text, expected_type), True
    return {"entities": []}, False


def normalize_supplied_entities(
    entities: list[dict[str, Any]],
    expected_type: str | None,
) -> list[dict[str, Any]]:
    if not isinstance(entities, list):
        raise ValueError("extracted_entities must be a list when provided.")
    normalized = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        canonical_name = str(entity.get("canonical_name") or entity.get("name") or "").strip()
        if not canonical_name:
            continue
        entity_type = entity.get("type") if entity.get("type") in ENTITY_TYPES else expected_type
        normalized.append(
            {
                "canonical_name": canonical_name,
                "type": entity_type,
                "source_text": str(entity.get("source_text") or canonical_name),
            }
        )
    return normalized


def resolve_enrichment(
    *,
    entity_type: str,
    attributes: dict[str, Any] | None,
    attribute_intervals_95: dict[str, dict[str, float]] | None,
    description: str,
) -> tuple[dict[str, Any], bool]:
    client_attributes = normalize_client_attributes(
        entity_type,
        attributes,
        attribute_intervals_95,
    )
    if client_attributes:
        return {
            "attributes": client_attributes,
            "notes": description,
            "metadata": {},
        }, False
    if entity_type == "restaurant":
        return normalize_restaurant_enrichment(description), True
    return normalize_enrichment(description, entity_type), True


def normalize_client_attributes(
    entity_type: str,
    attributes: dict[str, Any] | None,
    attribute_intervals_95: dict[str, dict[str, float]] | None,
) -> dict[str, Any]:
    if not isinstance(attributes, dict):
        return {}
    allowed = set(attribute_keys_for_type(entity_type))
    intervals = attribute_intervals_95 if isinstance(attribute_intervals_95, dict) else {}
    normalized = {}
    for key, value in attributes.items():
        if key not in allowed:
            continue
        try:
            point = clamp01(attribute_value(value))
        except (TypeError, ValueError):
            continue
        interval = intervals.get(key) if isinstance(intervals.get(key), dict) else None
        if isinstance(value, dict) and interval is None:
            interval = value.get("interval_95") or value
        normalized[key] = {
            "value": point,
            "interval_95": attribute_interval_95(
                {
                    "value": point,
                    "interval_95": interval or {"lower": point, "upper": point},
                }
            ),
        }
    return normalized


def normalize_attribute_intervals_1sigma(
    attributes: dict[str, Any],
) -> dict[str, dict[str, float]]:
    return {
        key: interval
        for key, value in attributes.items()
        if (interval := attribute_interval_for_level(value, "interval_1sigma"))
        is not None
    }


def attribute_interval_for_level(
    value: Any,
    key: str,
) -> dict[str, float] | None:
    if not isinstance(value, dict) or not isinstance(value.get(key), dict):
        return None
    try:
        return attribute_interval_95(
            {
                "value": attribute_value(value),
                "interval_95": value[key],
            }
        )
    except (TypeError, ValueError):
        return None


@mcp.tool()
@logged_tool
def palate_recall(
    query: str,
    context: dict[str, Any] | None = None,
    intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recall saved Palate memories by name or detail; use when not asking to rank."""
    context = context or {}
    intent, parsed_intent_with_llm = resolve_intent(query, context, intent)
    retrieval = retrieve_candidates(store, intent)
    ranked = rank_candidates(retrieval["candidates"], intent)
    grounding = build_grounding(ranked)
    return {
        "intent": intent,
        "retrieval": describe_retrieval(retrieval),
        "results": grounding,
        "server_llm_used": {"intent": parsed_intent_with_llm},
    }


@mcp.tool()
@logged_tool
def palate_delete_record(id: str) -> dict[str, Any]:
    """Delete by exact id/name or 99%+ high-confidence fuzzy name; below 99% returns candidates."""
    if not isinstance(id, str) or not id.strip():
        raise ValueError("id is required and must not be blank.")
    query = id.strip()

    exact = entity_by_any_id(query)
    if exact is not None:
        deleted = store.delete_entity(exact["id"])
        return deleted_record_response(query=query, deleted=deleted, match=None)

    matches = fuzzy_delete_candidates(query)
    if not matches:
        return {
            "deleted": False,
            "id": query,
            "query": query,
            "candidates": [],
            "needs_confirmation": [],
            "error": f"No Palate record found for id or name {query}.",
        }

    best = matches[0]
    if best["confidence"] >= 0.99:
        deleted = store.delete_entity(best["matched_id"])
        return deleted_record_response(query=query, deleted=deleted, match=best)

    return {
        "deleted": False,
        "id": query,
        "query": query,
        "candidates": matches,
        "needs_confirmation": matches,
        "ask_user": (
            "I found possible Palate memories, but no match was at least 99% "
            "confident. Ask the user to choose one by id before deleting."
        ),
        "error": "Delete requires confirmation below 99% match confidence.",
    }


def entity_by_any_id(entity_id: str) -> dict[str, Any] | None:
    for entity in store.list_entities():
        if entity.get("id") == entity_id:
            return entity
    return None


def fuzzy_delete_candidates(query: str) -> list[dict[str, Any]]:
    candidates = []
    for entity in store.list_entities():
        confidence = delete_match_confidence(query, entity.get("canonical_name", ""))
        if confidence < 0.5:
            continue
        candidates.append(
            {
                "input": query,
                "matched_id": entity["id"],
                "matched_name": entity["canonical_name"],
                "matched_type": entity["type"],
                "confidence": round(confidence, 3),
            }
        )
    return sorted(candidates, key=lambda match: match["confidence"], reverse=True)


def delete_match_confidence(query: str, canonical_name: str) -> float:
    query_norm = normalize_name_for_match(query)
    name_norm = normalize_name_for_match(canonical_name)
    if query_norm and query_norm == name_norm:
        return 1.0
    return min(name_match_confidence(query, canonical_name), 0.98)


def deleted_record_response(
    *,
    query: str,
    deleted: dict[str, Any] | None,
    match: dict[str, Any] | None,
) -> dict[str, Any]:
    if deleted is None:
        return {
            "deleted": False,
            "id": query,
            "query": query,
            "error": f"No Palate record found for id or name {query}.",
        }
    response = {
        "deleted": True,
        "id": deleted["id"],
        "query": query,
        "record": {
            "id": deleted["id"],
            "name": deleted["canonical_name"],
            "type": deleted["type"],
        },
    }
    if match is not None:
        response["match"] = match
    return response


def match_existing_memory(name: str, entity_type: str) -> dict[str, Any]:
    matches = store.match_entities_by_names([name])
    typed_matches = [
        match
        for match in matches.get("matches", [])
        if match.get("matched_id")
        and entity_by_id(match["matched_id"], entity_type) is not None
    ]
    if not typed_matches:
        return {"record": None, "match": None, "needs_confirmation": []}

    best = max(typed_matches, key=lambda match: float(match.get("confidence") or 0))
    record = entity_by_id(best["matched_id"], entity_type)
    if record is None:
        return {"record": None, "match": None, "needs_confirmation": []}
    if best.get("needs_confirmation"):
        return {"record": None, "match": None, "needs_confirmation": [best]}
    return {"record": record, "match": best, "needs_confirmation": []}


def entity_by_id(entity_id: str, entity_type: str) -> dict[str, Any] | None:
    for entity in store.list_entities():
        if entity.get("id") == entity_id and entity.get("type") == entity_type:
            return entity
    return None


def remember_arguments_from_memory(
    *,
    suggested_id: str,
    memory: dict[str, Any],
) -> dict[str, Any]:
    record = memory["record"]
    arguments = {
        "id": suggested_id,
        "type": record["type"],
        "canonical_name": record["canonical_name"],
        "description": record["source_text"],
        "attributes": memory["normalized_attributes"],
        "attribute_intervals_95": memory["normalized_attribute_intervals_95"],
        "notes": record.get("notes"),
        "fetch_external_ratings": False,
    }
    arguments.update(remember_metadata_arguments(record["type"], record.get("metadata") or {}))
    return {key: value for key, value in arguments.items() if value not in (None, [], {})}


def remember_metadata_arguments(entity_type: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if is_music_type(entity_type):
        return {
            "artist": metadata.get("artist"),
            "album": metadata.get("album"),
            "personnel": metadata.get("personnel"),
            "genre": metadata.get("genre"),
        }
    if is_restaurant_type(entity_type):
        michelin = metadata.get("michelin") or {}
        michelin_status = michelin.get("status")
        return {
            "cuisine": metadata.get("cuisine"),
            "michelin_status": (
                michelin_status if michelin_status not in {None, "unknown"} else None
            ),
            "michelin_url": michelin.get("source_url"),
            "michelin_green_star": (
                michelin.get("green_star") if michelin.get("green_star") else None
            ),
            "google_rating": (metadata.get("google") or {}).get("rating"),
            "google_rating_count": (metadata.get("google") or {}).get("rating_count"),
            "google_url": (metadata.get("google") or {}).get("source_url"),
        }
    if is_media_type(entity_type):
        return {
            "synopsis": metadata.get("synopsis"),
            "main_actors": metadata.get("main_actors"),
            "director": metadata.get("director"),
            "country": metadata.get("country"),
            "language": metadata.get("language"),
            "genre": metadata.get("genre"),
            "runtime": metadata.get("runtime"),
            "seasons": metadata.get("seasons"),
            "imdb_id": (metadata.get("external_ids") or {}).get("imdb_id"),
            "fetch_external_ratings": False,
        }
    return {}


def suggest_entity_id(entity_type: str, canonical_name: str) -> str:
    base = "_".join(
        part
        for part in "".join(
            char.lower() if char.isalnum() else " "
            for char in canonical_name
        ).split()
    )
    if not base:
        base = "item"
    return f"{entity_type}_{base}"


@mcp.tool()
@logged_tool
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
    cuisine: dict[str, Any] | list[str] | None,
    michelin_status: str | None,
    michelin_url: str | None,
    michelin_green_star: bool | None,
    google_rating: float | None,
    google_rating_count: int | None,
    google_url: str | None,
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
    if is_restaurant_type(entity_type):
        return prepare_restaurant_metadata(
            enrichment_metadata=enrichment_metadata,
            genre=genre,
            cuisine=cuisine,
            michelin_status=michelin_status,
            michelin_url=michelin_url,
            michelin_green_star=michelin_green_star,
            google_rating=google_rating,
            google_rating_count=google_rating_count,
            google_url=google_url,
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


def prepare_restaurant_metadata(
    *,
    enrichment_metadata: dict[str, Any],
    genre: list[str] | None,
    cuisine: dict[str, Any] | list[str] | None,
    michelin_status: str | None,
    michelin_url: str | None,
    michelin_green_star: bool | None,
    google_rating: float | None,
    google_rating_count: int | None,
    google_url: str | None,
) -> tuple[dict[str, Any], list[str]]:
    metadata = normalize_restaurant_metadata(enrichment_metadata)
    manual_paths: set[tuple[str, ...]] = set()

    if cuisine is not None:
        metadata = set_restaurant_field(metadata, ("cuisine",), cuisine)
        manual_paths.add(("cuisine",))
    elif genre is not None:
        metadata = set_restaurant_field(metadata, ("genre",), genre)
        manual_paths.add(("cuisine",))

    if any(
        value is not None
        for value in (michelin_status, michelin_url, michelin_green_star)
    ):
        michelin = dict(metadata.get("michelin") or {})
        if michelin_status is not None:
            michelin["status"] = michelin_status
        if michelin_url is not None:
            michelin["source_url"] = michelin_url
        if michelin_green_star is not None:
            michelin["green_star"] = michelin_green_star
        metadata = set_restaurant_field(metadata, ("michelin",), michelin)
        manual_paths.add(("michelin",))

    if any(
        value is not None
        for value in (google_rating, google_rating_count, google_url)
    ):
        google = dict(metadata.get("google") or {})
        if google_rating is not None:
            google["rating"] = google_rating
        if google_rating_count is not None:
            google["rating_count"] = google_rating_count
        if google_url is not None:
            google["source_url"] = google_url
        metadata = set_restaurant_field(metadata, ("google",), google)
        manual_paths.add(("google",))

    return merge_restaurant_metadata(metadata, {}, protected_paths=manual_paths), []


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
        "option_matches": retrieval.get("option_matches", []),
        "needs_confirmation": retrieval.get("needs_confirmation", []),
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
