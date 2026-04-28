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
            {"type": "rating", "value": 5},
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
            {"type": "rating", "value": 4},
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
            {"type": "rating", "value": 5},
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
            {"type": "rating", "value": 3},
            {"type": "saved", "value": True},
        ],
    },
    {
        "id": "music_bach_goldberg_gould",
        "type": "music",
        "canonical_name": "Bach: Goldberg Variations - Glenn Gould",
        "notes": "Intellectual, precise, focused listening.",
        "attributes": {
            "intellectual": 0.95,
            "quiet": 0.88,
            "classic": 0.9,
            "comfort": 0.72,
        },
        "signals": [
            {"type": "rating", "value": 5},
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
            {"type": "rating", "value": 4},
            {"type": "recommended_by", "value": "Alex"},
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
