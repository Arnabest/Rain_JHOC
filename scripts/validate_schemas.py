"""Validate every checked-in JHOC schema against the JSON Schema meta-schema."""

from pathlib import Path
import json

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    schemas = sorted((ROOT / "schemas").glob("*.json"))
    if not schemas:
        raise SystemExit("no schemas found")
    for path in schemas:
        document = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(document)
        print(f"OK {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

