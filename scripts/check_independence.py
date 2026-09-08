"""Run the P20 source independence check."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jhoc.independence import check_source


ROOT = Path(__file__).resolve().parents[1]
report = check_source(ROOT / "src")
if report.passed:
    print("INDEPENDENT: no forbidden runtime references")
else:
    print("DEPENDENCY VIOLATIONS:")
    print("\n".join(report.violations))
    raise SystemExit(1)

