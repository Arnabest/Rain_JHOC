from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from jhoc.contracts.errors import ContractError


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    expected: Any
    evaluator: Callable[[Any, Any], bool]


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    total: int
    passed: int
    failed: tuple[str, ...]

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


class Bench:
    """Deterministic replay evaluator; it never promotes a Forge candidate."""

    def run(self, cases: tuple[BenchmarkCase, ...], executor: Callable[[BenchmarkCase], Any]) -> BenchmarkResult:
        if not cases:
            raise ContractError("benchmark requires at least one case")
        failed = []
        for case in cases:
            actual = executor(case)
            if not case.evaluator(actual, case.expected):
                failed.append(case.case_id)
        return BenchmarkResult(len(cases), len(cases) - len(failed), tuple(failed))

