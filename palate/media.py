from __future__ import annotations

from difflib import SequenceMatcher
import re
from copy import deepcopy
from math import isfinite
from typing import Any


MEDIA_ENTITY_TYPES = {"movie", "series"}
MUSIC_ENTITY_TYPE = "music"
RESTAURANT_ENTITY_TYPE = "restaurant"

MEDIA_GENRES = [
    "action",
    "adventure",
    "animation",
    "biography",
    "comedy",
    "crime",
    "documentary",
    "drama",
    "family",
    "fantasy",
    "history",
    "horror",
    "music",
    "musical",
    "mystery",
    "romance",
    "sci_fi",
    "sport",
    "thriller",
    "war",
    "western",
]

MUSIC_GENRES = [
    "ambient",
    "blues",
    "classical",
    "country",
    "dance",
    "electronic",
    "experimental",
    "folk",
    "funk",
    "hip_hop",
    "jazz",
    "latin",
    "metal",
    "pop",
    "punk",
    "r_and_b",
    "reggae",
    "rock",
    "soul",
    "soundtrack",
    "world",
]

RESTAURANT_GENRES = [
    "american",
    "barbecue",
    "british",
    "chinese",
    "eastern_european",
    "french",
    "greek",
    "indian",
    "italian",
    "japanese",
    "korean",
    "latin_american",
    "mediterranean",
    "mexican",
    "middle_eastern",
    "modern_european",
    "seafood",
    "south_east_asian",
    "spanish",
    "thai",
    "vegetarian_vegan",
    "vietnamese",
    "other",
]

MEDIA_GENRE_ALIASES = {
    "children": "family",
    "kids": "family",
    "science_fiction": "sci_fi",
    "sci_fi": "sci_fi",
    "sci_fy": "sci_fi",
    "superhero": "action",
    "sports": "sport",
    "film_noir": "crime",
    "noir": "crime",
    "rom_com": "comedy",
    "romcom": "comedy",
    "tv_movie": "drama",
}

MUSIC_GENRE_ALIASES = {
    "bebop": "jazz",
    "classical_music": "classical",
    "edm": "electronic",
    "electronica": "electronic",
    "hard_bop": "jazz",
    "hip_hop": "hip_hop",
    "hiphop": "hip_hop",
    "modal_jazz": "jazz",
    "rap": "hip_hop",
    "r_b": "r_and_b",
    "rhythm_and_blues": "r_and_b",
    "singer_songwriter": "folk",
    "soundtracks": "soundtrack",
    "world_music": "world",
}

RESTAURANT_GENRE_ALIASES = {
    "asian_fusion": "south_east_asian",
    "bbq": "barbecue",
    "bistro": "french",
    "british": "british",
    "cantonese": "chinese",
    "central_european": "eastern_european",
    "deli": "american",
    "dim_sum": "chinese",
    "eastern_european": "eastern_european",
    "european": "modern_european",
    "filipino": "south_east_asian",
    "gastropub": "british",
    "georgian": "eastern_european",
    "greek": "greek",
    "indian": "indian",
    "indonesian": "south_east_asian",
    "italia": "italian",
    "italian": "italian",
    "japanese": "japanese",
    "korean": "korean",
    "latin": "latin_american",
    "latin_american": "latin_american",
    "lebanese": "middle_eastern",
    "malaysian": "south_east_asian",
    "mediterranean": "mediterranean",
    "mexican": "mexican",
    "middle_eastern": "middle_eastern",
    "modern_european": "modern_european",
    "new_american": "american",
    "peruvian": "latin_american",
    "pizzeria": "italian",
    "portuguese": "spanish",
    "seafood": "seafood",
    "singaporean": "south_east_asian",
    "spanish": "spanish",
    "sushi": "japanese",
    "thai": "thai",
    "trattoria": "italian",
    "turkish": "middle_eastern",
    "vegan": "vegetarian_vegan",
    "vegetarian": "vegetarian_vegan",
    "vietnamese": "vietnamese",
}

MEDIA_METADATA_PATHS: tuple[tuple[str, ...], ...] = (
    ("synopsis",),
    ("main_actors",),
    ("director",),
    ("country",),
    ("language",),
    ("genre",),
    ("runtime",),
    ("seasons",),
    ("watched",),
    ("watched_at",),
    ("external_ids", "imdb_id"),
    ("external_ratings", "imdb", "rating"),
    ("external_ratings", "imdb", "votes"),
    ("external_ratings", "rotten_tomatoes", "critic_score"),
    ("ratings_source", "provider"),
    ("ratings_source", "fetched_at"),
)

MUSIC_METADATA_PATHS: tuple[tuple[str, ...], ...] = (
    ("artist",),
    ("album",),
    ("personnel",),
    ("genre",),
)

RESTAURANT_METADATA_PATHS: tuple[tuple[str, ...], ...] = (("genre",),)


def is_media_type(entity_type: str | None) -> bool:
    return entity_type in MEDIA_ENTITY_TYPES


def is_music_type(entity_type: str | None) -> bool:
    return entity_type == MUSIC_ENTITY_TYPE


def is_restaurant_type(entity_type: str | None) -> bool:
    return entity_type == RESTAURANT_ENTITY_TYPE


def empty_media_metadata() -> dict[str, Any]:
    return {
        "synopsis": None,
        "main_actors": [],
        "director": None,
        "country": [],
        "language": [],
        "genre": [],
        "runtime": None,
        "seasons": None,
        "watched": False,
        "watched_at": None,
        "external_ids": {"imdb_id": None},
        "external_ratings": {
            "imdb": {"rating": None, "votes": None},
            "rotten_tomatoes": {"critic_score": None},
        },
        "ratings_source": {"provider": None, "fetched_at": None},
    }


def empty_music_metadata() -> dict[str, Any]:
    return {
        "artist": None,
        "album": None,
        "personnel": [],
        "genre": [],
    }


def empty_restaurant_metadata() -> dict[str, Any]:
    return {"genre": []}


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


def normalize_music_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    result = empty_music_metadata()
    if not isinstance(metadata, dict):
        return result

    for path in MUSIC_METADATA_PATHS:
        raw = get_path(metadata, path)
        if raw is None:
            continue
        set_path(result, path, normalize_music_value(path, raw))

    return result


def normalize_restaurant_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    result = empty_restaurant_metadata()
    if not isinstance(metadata, dict):
        return result

    raw = metadata.get("genre")
    if raw is not None:
        result["genre"] = normalize_restaurant_genres(raw)

    return result


def set_media_field(
    metadata: dict[str, Any],
    path: tuple[str, ...],
    value: Any,
) -> dict[str, Any]:
    result = normalize_media_metadata(metadata)
    set_path(result, path, normalize_media_value(path, value))
    return result


def set_music_field(
    metadata: dict[str, Any],
    path: tuple[str, ...],
    value: Any,
) -> dict[str, Any]:
    result = normalize_music_metadata(metadata)
    set_path(result, path, normalize_music_value(path, value))
    return result


def set_restaurant_field(
    metadata: dict[str, Any],
    path: tuple[str, ...],
    value: Any,
) -> dict[str, Any]:
    result = normalize_restaurant_metadata(metadata)
    if path == ("genre",):
        set_path(result, path, normalize_restaurant_genres(value))
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


def merge_music_metadata(
    base: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
    *,
    overwrite: bool = False,
    protected_paths: set[tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    result = normalize_music_metadata(base)
    source = normalize_music_metadata(incoming)
    protected_paths = protected_paths or set()

    for path in MUSIC_METADATA_PATHS:
        if path in protected_paths:
            continue
        value = get_path(source, path)
        if is_empty_metadata_value(value):
            continue
        current = get_path(result, path)
        if overwrite or is_empty_metadata_value(current):
            set_path(result, path, value)

    return result


def merge_restaurant_metadata(
    base: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
    *,
    overwrite: bool = False,
    protected_paths: set[tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    result = normalize_restaurant_metadata(base)
    source = normalize_restaurant_metadata(incoming)
    protected_paths = protected_paths or set()

    for path in RESTAURANT_METADATA_PATHS:
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
    music = normalize_music_metadata(metadata)
    restaurant = normalize_restaurant_metadata(metadata)
    parts: list[str] = []

    for key in ["synopsis", "director", "watched_at"]:
        value = normalized.get(key)
        if value:
            parts.append(str(value))

    parts.extend(normalized["main_actors"])
    parts.extend(normalized["country"])
    parts.extend(normalized["language"])
    parts.extend(normalized["genre"])
    if normalized["runtime"]:
        parts.extend(["runtime", f"{normalized['runtime']} min"])
    if normalized["seasons"]:
        parts.extend(["seasons", str(normalized["seasons"])])

    imdb_id = normalized["external_ids"].get("imdb_id")
    if imdb_id:
        parts.extend(["imdb", imdb_id])

    if normalized["watched"]:
        parts.append("watched")

    for fact in external_rating_facts(normalized):
        parts.append(fact)

    for key in ["artist", "album"]:
        value = music.get(key)
        if value:
            parts.append(str(value))

    parts.extend(music["personnel"])
    parts.extend(music["genre"])
    parts.extend(restaurant["genre"])

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
    if path == ("main_actors",):
        return normalize_string_list(value)
    if path == ("country",):
        return normalize_string_list(value)
    if path == ("language",):
        return normalize_string_list(value)
    if path == ("genre",):
        return normalize_genres(value, allowed=MEDIA_GENRES, aliases=MEDIA_GENRE_ALIASES)
    if path == ("runtime",):
        return normalize_runtime(value)
    if path == ("seasons",):
        return normalize_int(value)

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


def normalize_music_value(path: tuple[str, ...], value: Any) -> Any:
    if path == ("personnel",):
        return normalize_string_list(value)
    if path == ("genre",):
        return normalize_genres(value, allowed=MUSIC_GENRES, aliases=MUSIC_GENRE_ALIASES)
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
        values = re.split(r"[,;]+", value)
    elif isinstance(value, list):
        values = value
    else:
        values = [value]
    return [text for item in values if (text := normalize_string(item))]


def normalize_genres(
    value: Any,
    *,
    allowed: list[str],
    aliases: dict[str, str],
) -> list[str]:
    allowed_set = set(allowed)
    result = []
    for item in normalize_string_list(value):
        key = normalize_genre_key(item)
        canonical = aliases.get(key, key)
        if canonical not in allowed_set or canonical in result:
            continue
        result.append(canonical)
    return result


def normalize_restaurant_genres(value: Any) -> list[str]:
    result = []
    for item in normalize_string_list(value):
        canonical = restaurant_genre_match(item)
        if canonical and canonical not in result:
            result.append(canonical)
    return result


def restaurant_genre_match(value: Any, *, threshold: float = 0.4) -> str:
    key = normalize_genre_key(value)
    if not key:
        return "other"
    if key in RESTAURANT_GENRE_ALIASES:
        return RESTAURANT_GENRE_ALIASES[key]
    if key in RESTAURANT_GENRES:
        return key

    best = max(
        RESTAURANT_GENRES,
        key=lambda genre: genre_similarity(key, genre),
    )
    confidence = genre_similarity(key, best)
    return best if confidence >= threshold else "other"


def genre_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    left_tokens = set(left.split("_"))
    right_tokens = set(right.split("_"))
    overlap = len(left_tokens & right_tokens)
    token_score = overlap / max(len(left_tokens), len(right_tokens))
    if token_score > 0:
        return max(token_score, SequenceMatcher(None, left, right).ratio())
    sequence_score = SequenceMatcher(None, left, right).ratio()
    if left[0] == right[0] and sequence_score >= 0.75:
        return sequence_score
    return 0.0


def normalize_genre_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


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


def normalize_runtime(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    match = re.search(r"\d+", str(value).replace(",", ""))
    if not match:
        return None
    return int(match.group(0))


def is_empty_metadata_value(value: Any) -> bool:
    return value is None or value is False or value == "" or value == [] or value == {}
