from __future__ import annotations

from dotenv import load_dotenv

from .storage import open_store


ITEMS = [
    {
        "id": "wine_ridge_monte_bello_2018",
        "type": "wine",
        "canonical_name": "Ridge Monte Bello 2018",
        "notes": "Structured, premium, cedar and oak, long finish.",
        "attributes": {
            "oak": 0.82,
            "premium": 0.95,
            "richness": 0.78,
            "intensity": 0.84,
            "classic": 0.9,
            "indulgent": 0.75,
        },
        "signals": [
            {"type": "rating", "value": 10},
            {"type": "tried", "value": True},
            {"type": "saved", "value": True},
        ],
    },
    {
        "id": "wine_romanee_conti_echo_2020",
        "type": "wine",
        "canonical_name": "Echo de Lynch-Bages 2020",
        "notes": "Premium left-bank profile, cassis, oak, polished structure.",
        "attributes": {
            "oak": 0.68,
            "premium": 0.78,
            "richness": 0.72,
            "intensity": 0.76,
            "classic": 0.82,
        },
        "signals": [
            {"type": "rating", "value": 8},
            {"type": "recommended_by", "value": "Mike"},
        ],
    },
    {
        "id": "restaurant_clove_club",
        "type": "restaurant",
        "canonical_name": "The Clove Club",
        "notes": "Quiet, precise, intellectually interesting London tasting menu.",
        "attributes": {
            "quiet": 0.78,
            "intellectual": 0.92,
            "premium": 0.88,
            "indulgent": 0.62,
            "classic": 0.65,
        },
        "signals": [
            {"type": "rating", "value": 10},
            {"type": "saved", "value": True},
        ],
    },
    {
        "id": "restaurant_duck_waffle",
        "type": "restaurant",
        "canonical_name": "Duck & Waffle",
        "notes": "London view, lively room, late-night energy.",
        "attributes": {"view": 0.95, "lively": 0.86, "casual": 0.48, "novelty": 0.7},
        "signals": [
            {"type": "rating", "value": 6},
            {"type": "saved", "value": True},
        ],
    },
    {
        "id": "music_bach_goldberg_gould",
        "type": "music",
        "canonical_name": "Bach: Goldberg Variations - Glenn Gould",
        "notes": "Intellectual, precise, focused listening.",
        "metadata": {
            "artist": "Glenn Gould",
            "album": "Bach: Goldberg Variations",
            "personnel": ["Glenn Gould"],
            "genre": ["classical"],
        },
        "attributes": {
            "intellectual": 0.95,
            "quiet": 0.88,
            "classic": 0.9,
            "comfort": 0.72,
        },
        "signals": [
            {"type": "rating", "value": 10},
            {"type": "tried", "value": True},
        ],
    },
    {
        "id": "cigar_partagas_series_d_no4",
        "type": "cigar",
        "canonical_name": "Partagas Serie D No. 4",
        "notes": "Rich, classic, medium-full cigar.",
        "attributes": {"richness": 0.82, "intensity": 0.76, "classic": 0.8, "indulgent": 0.7},
        "signals": [
            {"type": "rating", "value": 8},
            {"type": "recommended_by", "value": "Alex"},
        ],
    },
    {
        "id": "movie_heat_1995",
        "type": "movie",
        "canonical_name": "Heat",
        "notes": "Precise, intense crime film with classic Los Angeles atmosphere.",
        "metadata": {
            "synopsis": "A career criminal and a driven detective move toward a collision in Los Angeles.",
            "main_actors": ["Al Pacino", "Robert De Niro", "Val Kilmer"],
            "director": "Michael Mann",
            "country": ["United States"],
            "language": ["English", "Spanish"],
            "genre": ["crime", "drama", "thriller"],
            "runtime": 170,
            "seasons": None,
            "watched": True,
            "watched_at": None,
            "external_ids": {"imdb_id": "tt0113277"},
            "external_ratings": {
                "imdb": {"rating": 8.3, "votes": 740000},
                "rotten_tomatoes": {"critic_score": 83},
            },
            "ratings_source": {"provider": "omdb", "fetched_at": None},
        },
        "attributes": {
            "intense": 0.9,
            "classic": 0.82,
            "cerebral": 0.68,
            "action": 0.74,
        },
        "signals": [
            {"type": "rating", "value": 10},
            {"type": "tried", "value": True},
        ],
    },
    {
        "id": "series_severance",
        "type": "series",
        "canonical_name": "Severance",
        "notes": "Quietly unsettling, intellectual workplace mystery.",
        "metadata": {
            "synopsis": "Office workers separate their work and personal memories and uncover a deeper conspiracy.",
            "main_actors": ["Adam Scott", "Britt Lower", "Patricia Arquette"],
            "director": "Ben Stiller",
            "country": ["United States"],
            "language": ["English"],
            "genre": ["drama", "mystery", "sci_fi"],
            "runtime": 50,
            "seasons": 2,
            "watched": False,
            "watched_at": None,
            "external_ids": {"imdb_id": "tt11280740"},
            "external_ratings": {
                "imdb": {"rating": 8.7, "votes": 250000},
                "rotten_tomatoes": {"critic_score": 97},
            },
            "ratings_source": {"provider": "omdb", "fetched_at": None},
        },
        "attributes": {
            "slow_burn": 0.72,
            "cerebral": 0.92,
            "dark": 0.76,
            "novelty": 0.84,
        },
        "signals": [
            {"type": "saved", "value": True},
        ],
    },
]


def main() -> None:
    load_dotenv()
    store = open_store()
    for item in ITEMS:
        store.upsert_entity(item)
    print(f"Seeded {len(ITEMS)} Palate entities.")


if __name__ == "__main__":
    main()
