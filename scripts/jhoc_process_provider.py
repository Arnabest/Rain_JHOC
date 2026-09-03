"""Run an external CLI as a native JHOC provider.

The adapter has no dependency on the retired Agent Bus. Commands are passed
as an argv JSON array (never a shell string) and are executed once per JHOC
request over one persistent provider connection.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.provider import JHOCProviderClient  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-id", required=True, choices=("codex-cli", "agy-cli", "deepseek-harness"))
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument("--command-json", help="JSON argv array, e.g. [\"codex\",\"exec\"]")
    commands.add_argument("--executable", help="Executable path; combine with repeated --command-arg")
    parser.add_argument("--command-arg", action="append", default=[])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--cwd", default=str(ROOT))
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = json.loads(args.command_json) if args.command_json else [args.executable, *args.command_arg]
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        raise SystemExit("--command-json must be a non-empty JSON argv array of strings")
    import shutil
    resolved_exe = shutil.which(command[0])
    if resolved_exe:
        command[0] = resolved_exe
    cwd = str(Path(args.cwd).expanduser().resolve())
    timeout = max(1.0, float(args.timeout))

    def invoke(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        prompt = payload.get("prompt", payload.get("text", payload.get("task", json.dumps(dict(payload), ensure_ascii=False))))
        context = payload.get("context")
        if context and isinstance(context, Mapping):
            header = f"[JHOC Governance Context | Policy: {context.get('policy_ref', 'jhoc-v1')} | Snapshot: {context.get('snapshot_id', 'none')}]\n"
            full_prompt = f"{header}{prompt}"
        else:
            full_prompt = str(prompt)
        completed = subprocess.run(
            [*command, full_prompt],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "status": "accepted" if completed.returncode == 0 else "failed",
            "final": True,
            "model_reply": completed.returncode == 0,
            "evidence_level": "jhoc-native-cli-final",
            "exit_code": completed.returncode,
            "text": completed.stdout.strip(),
            "stderr": completed.stderr.strip()[-4000:],
            "provider_id": args.provider_id,
        }

    client = JHOCProviderClient(args.provider_id, invoke, host=args.host, port=args.port)
    print(f"Starting provider {args.provider_id} on {args.host}:{args.port}...", flush=True)
    try:
        client.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        client.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
