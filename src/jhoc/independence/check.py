from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_FORBIDDEN = ("ai" + "box", "vers" + "-rule", "legacy " + "agent " + "bus", "legacy_" + "agent_" + "bus", "agent_" + "bus")


@dataclass(frozen=True, slots=True)
class IndependenceReport:
    passed: bool
    violations: tuple[str, ...]


def check_source(source_root: str | Path) -> IndependenceReport:
    root = Path(source_root)
    violations: list[str] = []
    for path in root.rglob("*.py"):
        content = path.read_text(encoding="utf-8").lower()
        for forbidden in _FORBIDDEN:
            if forbidden in content:
                violations.append(f"{path}:{forbidden}")
    return IndependenceReport(not violations, tuple(violations))
