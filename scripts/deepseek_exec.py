"""Local CLI executable for DeepSeek Harness.

Provides a standard command-line interface for the local DeepSeek harness
endpoint running at http://127.0.0.1:8768/v1/chat/completions.
"""

from __future__ import annotations

import json
import sys
import urllib.request


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.stderr.write("Error: prompt argument is required\n")
        return 1
    if sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    prompt = " ".join(args)
    system_prompt = (
        "You are an independent, objective governance validation node within the JHOC "
        "(Joint Hybrid Operations Center) ecosystem. Analyze code, policies, and tasks "
        "with strict factual evidence, adherence to fail-closed safety constraints, "
        "and deterministic verification."
    )
    payload = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8768/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            print(content.strip())
            return 0
    except Exception as exc:
        sys.stderr.write(f"DeepSeek Harness request failed: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
