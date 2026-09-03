import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.bench import Bench, BenchmarkCase  # noqa: E402


class BenchTests(unittest.TestCase):
    def test_deterministic_baseline_reports_failed_cases(self):
        cases = (
            BenchmarkCase("pass", 1, lambda actual, expected: actual == expected),
            BenchmarkCase("fail", 2, lambda actual, expected: actual == expected),
        )
        result = Bench().run(cases, lambda case: 1)
        self.assertEqual(result.pass_rate, 0.5)
        self.assertEqual(result.failed, ("fail",))


if __name__ == "__main__":
    unittest.main()

