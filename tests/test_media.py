from __future__ import annotations

import unittest

from palate.media import (
    MICHELIN_STATUSES,
    RESTAURANT_GENRES,
    normalize_google_rating_metadata,
    normalize_michelin_status,
    normalize_restaurant_cuisine,
    normalize_restaurant_genres,
    normalize_restaurant_metadata,
    restaurant_cuisine_search_terms,
    restaurant_google_search_terms,
    restaurant_genre_match,
    restaurant_michelin_search_terms,
)


class RestaurantCuisineGenreTest(unittest.TestCase):
    def test_restaurant_genres_are_controlled_enum_with_other(self) -> None:
        self.assertIn("italian", RESTAURANT_GENRES)
        self.assertIn("mexican", RESTAURANT_GENRES)
        self.assertIn("other", RESTAURANT_GENRES)

    def test_restaurant_genre_aliases_map_to_enum_values(self) -> None:
        self.assertEqual(
            normalize_restaurant_genres(["Pizzeria", "Sushi"]),
            ["italian", "japanese"],
        )
        self.assertEqual(
            normalize_restaurant_genres(["Peruvian", "Lebanese"]),
            ["latin_american", "middle_eastern"],
        )
        self.assertEqual(
            normalize_restaurant_cuisine(["Pizzeria", "Sushi"]),
            {
                "italian": {"value": 1.0, "interval_95": {"lower": 1.0, "upper": 1.0}},
                "japanese": {"value": 1.0, "interval_95": {"lower": 1.0, "upper": 1.0}},
            },
        )

    def test_restaurant_genre_uses_other_below_40_percent_certainty(self) -> None:
        self.assertEqual(restaurant_genre_match("nordic"), "other")
        self.assertNotEqual(restaurant_genre_match("nordic", threshold=0.0), "other")

    def test_restaurant_genre_uses_fuzzy_match_at_or_above_40_percent_certainty(self) -> None:
        self.assertEqual(restaurant_genre_match("mediteranean"), "mediterranean")
        self.assertEqual(restaurant_genre_match("veg vegan"), "vegetarian_vegan")

    def test_restaurant_metadata_migrates_legacy_genre_to_scored_cuisine(self) -> None:
        self.assertEqual(
            normalize_restaurant_metadata({"genre": ["Italian", "Vegan"]}),
            {
                "cuisine": {
                    "italian": {"value": 1.0, "interval_95": {"lower": 1.0, "upper": 1.0}},
                    "vegetarian_vegan": {
                        "value": 1.0,
                        "interval_95": {"lower": 1.0, "upper": 1.0},
                    },
                }
            },
        )

    def test_restaurant_cuisine_preserves_scores_and_drops_other_when_specific_exists(self) -> None:
        cuisine = normalize_restaurant_cuisine(
            {
                "italian": {"value": 0.9, "interval_95": {"lower": 0.75, "upper": 0.98}},
                "vegetarian_vegan": 0.7,
                "nordic": 0.6,
            }
        )

        self.assertEqual(set(cuisine), {"italian", "vegetarian_vegan"})
        self.assertEqual(cuisine["italian"]["value"], 0.9)
        self.assertEqual(
            cuisine["vegetarian_vegan"]["interval_95"],
            {"lower": 0.7, "upper": 0.7},
        )
        self.assertEqual(
            restaurant_cuisine_search_terms({"cuisine": cuisine}),
            ["italian", "vegetarian_vegan"],
        )

    def test_restaurant_michelin_status_normalizes_distinctions(self) -> None:
        self.assertIn("one_star", MICHELIN_STATUSES)
        self.assertEqual(
            normalize_michelin_status(
                {
                    "status": "1 Michelin Star",
                    "green_star": True,
                    "url": "https://guide.michelin.com/gb/en/test",
                    "checked_at": "2026-05-03",
                }
            ),
            {
                "status": "one_star",
                "stars": 1,
                "green_star": True,
                "source_url": "https://guide.michelin.com/gb/en/test",
                "source": "guide.michelin.com",
                "checked_at": "2026-05-03",
            },
        )

    def test_restaurant_metadata_preserves_michelin_status_for_search(self) -> None:
        metadata = normalize_restaurant_metadata(
            {
                "cuisine": ["British"],
                "michelin": {
                    "status": "Bib Gourmand",
                    "source_url": "https://guide.michelin.com/gb/en/test",
                },
            }
        )

        self.assertEqual(metadata["michelin"]["status"], "bib_gourmand")
        self.assertEqual(metadata["michelin"]["stars"], 0)
        self.assertEqual(
            restaurant_michelin_search_terms(metadata),
            ["michelin", "bib gourmand"],
        )

    def test_restaurant_google_rating_normalizes_review_count(self) -> None:
        self.assertEqual(
            normalize_google_rating_metadata(
                {
                    "rating": "4.64",
                    "userRatingCount": "1,234",
                    "url": "https://www.google.com/maps/place/test",
                    "checked_at": "2026-05-03",
                }
            ),
            {
                "rating": 4.6,
                "rating_count": 1234,
                "source_url": "https://www.google.com/maps/place/test",
                "source": "google",
                "checked_at": "2026-05-03",
            },
        )

    def test_restaurant_metadata_preserves_google_rating_for_search(self) -> None:
        metadata = normalize_restaurant_metadata(
            {
                "cuisine": ["Italian"],
                "google": {
                    "rating": 4.7,
                    "rating_count": 321,
                    "source_url": "https://maps.app.goo.gl/example",
                },
            }
        )

        self.assertEqual(metadata["google"]["rating"], 4.7)
        self.assertEqual(metadata["google"]["rating_count"], 321)
        self.assertEqual(
            restaurant_google_search_terms(metadata),
            ["google", "google rating 4.7", "321 google ratings"],
        )


if __name__ == "__main__":
    unittest.main()
