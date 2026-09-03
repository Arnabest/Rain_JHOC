"""Run a fresh-process-style JHOC closed-loop acceptance probe.

The default providers are deterministic local probe handlers. Their evidence
proves the JHOC runtime contract only; it must not be counted as model review
evidence. Real Codex/AGY/DeepSeek handlers can be substituted by starting
native provider clients against the same endpoint and running the request
portion of this probe.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from threading import Thread
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))

from jhoc.application import ApplicationConfig, JHOCApplication  # noqa: E402
from jhoc.supervisor import JHOCSupervisorServer  # noqa: E402


PROVIDERS = ("codex-cli", "agy-cli", "deepseek-harness")


def _probe_handler(provider_id: str):
    def handle(payload):
        return {
            "status": "accepted",
            "final": True,
            "provider_id": provider_id,
            "echo": payload.get("prompt", ""),
            "probe": "jhoc-native-transport",
        }
    return handle


def run_probe(db_path: Path | None = None, providers: tuple[str, ...] = PROVIDERS) -> dict:
    temporary = tempfile.TemporaryDirectory() if db_path is None else None
    path = db_path or (Path(temporary.name) / "jhoc.db")
    session_id = f"jhoc-probe-{uuid4()}"
    app = JHOCApplication(ApplicationConfig(path))
    endpoint = None
    app_started = False
    started_at = datetime.now(timezone.utc)
    try:
        app.start()
        app_started = True
        endpoint = JHOCSupervisorServer(app.supervisor, port=0)
        host, port = endpoint.start()
        clients = []
        threads = []
        for provider_id in providers:
            from jhoc.provider import JHOCProviderClient
            client = JHOCProviderClient(provider_id, _probe_handler(provider_id), host=host, port=port, reconnect_delay=0.01)
            thread = Thread(target=client.run_forever, daemon=True)
            client.run_thread = thread
            thread.start()
            clients.append(client)
            threads.append(thread)
        deadline = time.monotonic() + 3
        while len(app.supervisor.providers()) < len(providers) and time.monotonic() < deadline:
            time.sleep(0.01)
        rows = []
        for provider_id in providers:
            correlation = app.supervisor.submit(
                {"session_id": session_id, "prompt": f"closed-loop probe for {provider_id}"},
                provider_id=provider_id,
            )
            response = app.supervisor.await_response(correlation, timeout=3)
            record = app.relay.get(response.request_id) if response else None
            rows.append({
                "provider_id": provider_id,
                "correlation_id": correlation,
                "request_id": response.request_id if response else None,
                "status": response.status if response else "timeout",
                "final": bool(response and response.payload.get("final")),
                "session_id": response.session_id if response else None,
                "relay_status": record.status.value if record else None,
                "probe_only": True,
            })
        result_ok = (
            len(rows) >= 2
            and all(row["status"] == "accepted" and row["final"] and row["relay_status"] == "ACKED" for row in rows)
            and len({row["provider_id"] for row in rows}) == len(rows)
        )
        app.stop()
        app_started = False
        for client in clients:
            client.stop()
        for thread in threads:
            thread.join(timeout=1)
        # Re-open the durable runtime to prove response records survive restart.
        restored = JHOCApplication(ApplicationConfig(path))
        restored_responses = sum(restored.supervisor.response(row["correlation_id"]) is not None for row in rows)
        restored.stop()
        return {
            "schema_version": "jhoc-closed-loop/v1",
            "probe_only": True,
            "session_id": session_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "endpoint": {"host": host, "port": port},
            "providers": rows,
            "provider_count": len(rows),
            "accepted_final_count": sum(row["status"] == "accepted" and row["final"] for row in rows),
            "restored_response_count": restored_responses,
            "transport_closed_loop": result_ok and restored_responses == len(rows),
            "model_review_evidence": False,
        }
    finally:
        if endpoint is not None:
            endpoint.stop()
        if app_started:
            app.stop()
        if temporary is not None:
            temporary.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--artifact", type=Path, default=ROOT / "docs" / "acceptance" / "artifacts" / "jhoc-closed-loop-latest.json")
    args = parser.parse_args(argv)
    result = run_probe(args.db)
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
    markdown = [
        "# JHOC Closed-Loop Probe",
        "",
        f"- Session: `{result['session_id']}`",
        f"- Transport closed loop: `{result['transport_closed_loop']}`",
        f"- Model review evidence: `{result['model_review_evidence']}`",
        f"- Restored responses: `{result['restored_response_count']}/{result['provider_count']}`",
        "",
        "| Provider | Correlation | Final | Relay | Status |",
        "|---|---|---:|---|---|",
    ]
    markdown.extend(
        f"| {row['provider_id']} | `{row['correlation_id']}` | {row['final']} | {row['relay_status']} | {row['status']} |"
        for row in result["providers"]
    )
    args.artifact.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["transport_closed_loop"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
