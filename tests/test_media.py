from __future__ import annotations

import unittest

from palate.media import (
    RESTAURANT_GENRES,
    normalize_restaurant_genres,
    restaurant_genre_match,
)


class RestaurantCuisineGenreTest(unittest.TestCase):
    def test_restaurant_genres_are_controlled_enum_with_other(self) -> None:
        self.assertIn("italian", RESTAURANT_GENRES)
        self.assertIn("mexican", RESTAURANT_GENRES)
        self.assertIn("other", RESTAURANT_GENRES)

    def test_restaurant_genre_aliases_map_to_enum_values(self) -> None:
        self.assertEqual(normalize_restaurant_genres(["Pizzeria", "Sushi"]), ["italian", "japanese"])
        self.assertEqual(normalize_restaurant_genres(["Peruvian", "Lebanese"]), ["latin_american", "middle_eastern"])

    def test_restaurant_genre_uses_other_below_40_percent_certainty(self) -> None:
        self.assertEqual(restaurant_genre_match("nordic"), "other")
        self.assertNotEqual(restaurant_genre_match("nordic", threshold=0.0), "other")

    def test_restaurant_genre_uses_fuzzy_match_at_or_above_40_percent_certainty(self) -> None:
        self.assertEqual(restaurant_genre_match("mediteranean"), "mediterranean")
        self.assertEqual(restaurant_genre_match("veg vegan"), "vegetarian_vegan")


if __name__ == "__main__":
    unittest.main()
