from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from palate.omdb import fetch_omdb_metadata


class OmdbBehaviorTest(unittest.TestCase):
    def test_missing_api_key_fails_softly(self) -> None:
        with patch.dict("os.environ", {"OMDB_API_KEY": ""}):
            result = fetch_omdb_metadata(title="Heat", entity_type="movie")

        self.assertEqual(result["metadata"], {})
        self.assertIn("OMDB_API_KEY is not set", result["warnings"][0])

    def test_lookup_by_imdb_id_maps_external_ratings(self) -> None:
        payload = {
            "Response": "True",
            "Title": "Heat",
            "Plot": "A detective pursues a crew of thieves.",
            "Actors": "Al Pacino, Robert De Niro",
            "Director": "Michael Mann",
            "Country": "United States",
            "Genre": "Crime, Drama",
            "imdbID": "tt0113277",
            "imdbRating": "8.3",
            "imdbVotes": "740,000",
            "Ratings": [
                {"Source": "Internet Movie Database", "Value": "8.3/10"},
                {"Source": "Rotten Tomatoes", "Value": "83%"},
            ],
        }

        with patch("palate.omdb.urlopen", return_value=FakeResponse(payload)) as urlopen:
            result = fetch_omdb_metadata(
                title="Heat",
                entity_type="movie",
                imdb_id="tt0113277",
                api_key="test-key",
            )

        query = parse_qs(urlparse(urlopen.call_args.args[0].full_url).query)
        metadata = result["metadata"]

        self.assertEqual(query["i"], ["tt0113277"])
        self.assertNotIn("t", query)
        self.assertEqual(metadata["synopsis"], "A detective pursues a crew of thieves.")
        self.assertEqual(metadata["main_actors"], ["Al Pacino", "Robert De Niro"])
        self.assertEqual(metadata["director"], "Michael Mann")
        self.assertEqual(metadata["external_ids"]["imdb_id"], "tt0113277")
        self.assertEqual(metadata["external_ratings"]["imdb"]["rating"], 8.3)
        self.assertEqual(metadata["external_ratings"]["imdb"]["votes"], 740000)
        self.assertEqual(
            metadata["external_ratings"]["rotten_tomatoes"]["critic_score"],
            83,
        )
        self.assertEqual(result["warnings"], [])
        self.assertIn("context", urlopen.call_args.kwargs)

    def test_lookup_by_title_uses_media_type_and_warns_when_ratings_absent(self) -> None:
        payload = {
            "Response": "True",
            "Title": "Severance",
            "Plot": "Workers split their work and personal memories.",
            "Actors": "Adam Scott, Britt Lower",
            "Director": "Ben Stiller",
            "Country": "United States",
            "Genre": "Drama, Mystery",
            "imdbID": "tt11280740",
            "imdbRating": "N/A",
            "imdbVotes": "N/A",
            "Ratings": [],
        }

        with patch("palate.omdb.urlopen", return_value=FakeResponse(payload)) as urlopen:
            result = fetch_omdb_metadata(
                title="Severance",
                entity_type="series",
                api_key="test-key",
            )

        query = parse_qs(urlparse(urlopen.call_args.args[0].full_url).query)

        self.assertEqual(query["t"], ["Severance"])
        self.assertEqual(query["type"], ["series"])
        self.assertEqual(result["metadata"]["external_ids"]["imdb_id"], "tt11280740")
        self.assertIsNone(result["metadata"]["external_ratings"]["imdb"]["rating"])
        self.assertIn("OMDb returned no IMDb or Rotten Tomatoes rating", result["warnings"][0])


class FakeResponse:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
