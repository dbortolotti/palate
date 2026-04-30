from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any


MEDIA_ENTITY_TYPES = {"movie", "series"}

MEDIA_METADATA_PATHS: tuple[tuple[str, ...], ...] = (
    ("synopsis",),
    ("main_actors",),
    ("director",),
    ("country",),
    ("genre",),
    ("watched",),
    ("watched_at",),
    ("external_ids", "imdb_id"),
    ("external_ratings", "imdb", "rating"),
    ("external_ratings", "imdb", "votes"),
    ("external_ratings", "rotten_tomatoes", "critic_score"),
    ("ratings_source", "provider"),
    ("ratings_source", "fetched_at"),
)


def is_media_type(entity_type: str | None) -> bool:
    return entity_type in MEDIA_ENTITY_TYPES


def empty_media_metadata() -> dict[str, Any]:
    return {
        "synopsis": None,
        "main_actors": [],
        "director": None,
        "country": None,
        "genre": [],
        "watched": False,
        "watched_at": None,
        "external_ids": {"imdb_id": None},
        "external_ratings": {
            "imdb": {"rating": None, "votes": None},
            "rotten_tomatoes": {"critic_score": None},
        },
        "ratings_source": {"provider": None, "fetched_at": None},
    }


def normalize_media_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    result = empty_media_metadata()
    if not isinstance(metadata, dict):
        return result

    for path in MEDIA_METADATA_PATHS:
        raw = get_path(metadata, path)
        if raw is None:
            continue
        set_path(result, path, normalize_media_value(path, raw))

    return result


def set_media_field(
    metadata: dict[str, Any],
    path: tuple[str, ...],
    value: Any,
) -> dict[str, Any]:
    result = normalize_media_metadata(metadata)
    set_path(result, path, normalize_media_value(path, value))
    return result


def merge_media_metadata(
    base: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
    *,
    overwrite: bool = False,
    protected_paths: set[tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    result = normalize_media_metadata(base)
    source = normalize_media_metadata(incoming)
    protected_paths = protected_paths or set()

    for path in MEDIA_METADATA_PATHS:
        if path in protected_paths:
            continue
        value = get_path(source, path)
        if is_empty_metadata_value(value):
            continue
        current = get_path(result, path)
        if overwrite or is_empty_metadata_value(current):
            set_path(result, path, value)

    return result


def external_rating_tiebreak(metadata: dict[str, Any] | None) -> float:
    normalized = normalize_media_metadata(metadata)
    scores = []

    imdb_rating = get_path(normalized, ("external_ratings", "imdb", "rating"))
    if imdb_rating is not None:
        scores.append(float(imdb_rating) / 10)

    rt_score = get_path(
        normalized,
        ("external_ratings", "rotten_tomatoes", "critic_score"),
    )
    if rt_score is not None:
        scores.append(float(rt_score) / 100)

    if not scores:
        return 0.0
    return round((sum(scores) / len(scores)) * 0.05, 3)


def external_rating_facts(metadata: dict[str, Any] | None) -> list[str]:
    normalized = normalize_media_metadata(metadata)
    facts = []

    imdb_rating = get_path(normalized, ("external_ratings", "imdb", "rating"))
    imdb_votes = get_path(normalized, ("external_ratings", "imdb", "votes"))
    if imdb_rating is not None:
        suffix = f", {imdb_votes:,} votes" if imdb_votes is not None else ""
        facts.append(f"IMDb {float(imdb_rating):g}/10{suffix}")

    rt_score = get_path(
        normalized,
        ("external_ratings", "rotten_tomatoes", "critic_score"),
    )
    if rt_score is not None:
        facts.append(f"Rotten Tomatoes critic {int(rt_score)}%")

    return facts


def metadata_search_text(metadata: dict[str, Any] | None) -> str:
    normalized = normalize_media_metadata(metadata)
    parts: list[str] = []

    for key in ["synopsis", "director", "country", "watched_at"]:
        value = normalized.get(key)
        if value:
            parts.append(str(value))

    parts.extend(normalized["main_actors"])
    parts.extend(normalized["genre"])

    imdb_id = normalized["external_ids"].get("imdb_id")
    if imdb_id:
        parts.extend(["imdb", imdb_id])

    if normalized["watched"]:
        parts.append("watched")

    for fact in external_rating_facts(normalized):
        parts.append(fact)

    return " ".join(parts)


def get_path(mapping: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def set_path(mapping: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = mapping
    for key in path[:-1]:
        nested = current.get(key)
        if not isinstance(nested, dict):
            nested = {}
            current[key] = nested
        current = nested
    current[path[-1]] = deepcopy(value)


def normalize_media_value(path: tuple[str, ...], value: Any) -> Any:
    if path in {("main_actors",), ("genre",)}:
        return normalize_string_list(value)

    if path == ("watched",):
        return normalize_bool(value)

    if path == ("external_ratings", "imdb", "rating"):
        return normalize_float(value)

    if path in {
        ("external_ratings", "imdb", "votes"),
        ("external_ratings", "rotten_tomatoes", "critic_score"),
    }:
        return normalize_int(value)

    return normalize_string(value)


def normalize_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return None
    return text


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list):
        values = value
    else:
        values = [value]
    return [text for item in values if (text := normalize_string(item))]


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "watched"}
    return bool(value)


def normalize_float(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if not isfinite(result):
        return None
    return result


def normalize_int(value: Any) -> int | None:
    try:
        result = int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None
    return result


def is_empty_metadata_value(value: Any) -> bool:
    return value is None or value is False or value == "" or value == [] or value == {}
