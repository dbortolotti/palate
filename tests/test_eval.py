from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from palate.eval import evaluate_cases, ndcg_at_k, sweep_weights
from palate.storage import open_store


class RankingEvalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="palate-eval-"))
        self.store = open_store(str(self.temp_dir / "test.sqlite"))
        self.store.upsert_entity(
            {
                "id": "wine_a",
                "type": "wine",
                "canonical_name": "Wine A",
                "attributes": {"oak": 0.9},
                "signals": [{"type": "rating", "value": 8}],
            }
        )
        self.store.upsert_entity(
            {
                "id": "wine_b",
                "type": "wine",
                "canonical_name": "Wine B",
                "attributes": {"oak": 0.4},
                "signals": [{"type": "rating", "value": 8}],
            }
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ndcg_rewards_correct_order(self) -> None:
        self.assertEqual(ndcg_at_k(["a", "b"], ["a", "b"]), 1.0)
        self.assertLess(ndcg_at_k(["b", "a"], ["a", "b"]), 1.0)

    def test_evaluate_cases_reports_mean_scores(self) -> None:
        score = evaluate_cases(
            self.store,
            [
                {
                    "name": "oaky wine",
                    "query": "oaky wine",
                    "intent": {
                        "attributes": ["oak"],
                        "context": {},
                        "filters": {"min_rating": None, "recommended_by": None},
                        "entity_type": "wine",
                        "search_text": "",
                    },
                    "expected_top_3": ["wine_a", "wine_b"],
                }
            ],
        )

        self.assertEqual(score["case_count"], 1)
        self.assertEqual(score["mean_ndcg_at_3"], 1.0)
        self.assertEqual(score["cases"][0]["actual_top_3"], ["wine_a", "wine_b"])

    def test_sweep_weights_returns_best_first(self) -> None:
        results = sweep_weights(
            self.store,
            [
                {
                    "query": "oaky wine",
                    "intent": {
                        "attributes": ["oak"],
                        "context": {},
                        "filters": {"min_rating": None, "recommended_by": None},
                        "entity_type": "wine",
                        "search_text": "",
                    },
                    "expected_top_3": ["wine_a"],
                }
            ],
            grid={"attribute_match_cap": [0.0, 1.0]},
        )

        self.assertEqual(len(results), 2)
        self.assertGreaterEqual(results[0]["mean_ndcg_at_3"], results[1]["mean_ndcg_at_3"])


if __name__ == "__main__":
    unittest.main()
