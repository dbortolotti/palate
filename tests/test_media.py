from __future__ import annotations

import unittest

from palate.media import (
    RESTAURANT_GENRES,
    normalize_restaurant_cuisine,
    normalize_restaurant_genres,
    normalize_restaurant_metadata,
    restaurant_cuisine_search_terms,
    restaurant_genre_match,
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


if __name__ == "__main__":
    unittest.main()
