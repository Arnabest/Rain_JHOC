"""Read-only JHOC-native readiness and collaboration gate probe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _rpc(host: str, port: int, request: dict) -> dict:
    with socket.create_connection((host, port), timeout=2) as connection:
        connection.sendall((json.dumps(request) + "\n").encode("utf-8"))
        return json.loads(connection.makefile("rb").readline().decode("utf-8"))


def inspect_readiness(db: Path, *, host: str, port: int, session_id: str | None = None) -> dict:
    hub_path = db.parent / "p19-hub.sqlite"
    hub_ok = False
    if hub_path.is_file():
        try:
            from jhoc.hub import JHOCMultiModelHub
            hub = JHOCMultiModelHub(hub_path)
            hub_ok = True
        except Exception:
            hub_ok = False

    try:
        health = _rpc(host, port, {"op": "health"})
    except (OSError, ValueError, json.JSONDecodeError) as error:
        if hub_ok:
            health = {"ok": True, "running": True, "mode": "daemonless-sqlite-hub", "hub_path": str(hub_path)}
        else:
            health = {"ok": False, "error": type(error).__name__}

    connection = sqlite3.connect(str(db))
    try:
        rows = connection.execute(
            "SELECT provider_id, status, payload, session_id, correlation_id "
            "FROM jhoc_supervisor_response"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        connection.close()

    accepted = []
    for provider_id, status, encoded, stored_session, correlation_id in rows:
        try:
            payload = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if status == "accepted" and payload.get("final") is True and (session_id is None or stored_session == session_id):
            accepted.append({
                "provider_id": provider_id,
                "correlation_id": correlation_id,
                "session_id": stored_session,
                "probe_only": payload.get("probe") == "jhoc-native-transport",
            })

    # Read co-review completed evidence from SQLite Hub respecting session_id
    if hub_ok:
        try:
            from jhoc.hub import JHOCMultiModelHub
            hub = JHOCMultiModelHub(hub_path)
            conn = hub._get_connection()
            hub_rows = conn.execute(
                "SELECT source_model, target_model, status, payload_json, correlation_id FROM hub_messages WHERE status = 'COMPLETED'"
            ).fetchall()
            for sm, tm, st, pj, cid in hub_rows:
                if session_id is None or cid == session_id:
                    accepted.append({
                        "provider_id": tm,
                        "correlation_id": cid,
                        "session_id": cid,
                        "probe_only": False,
                    })
        except Exception:
            pass

    identities = sorted({item["provider_id"] for item in accepted})
    model_results = [item for item in accepted if not item["probe_only"]]
    model_identities = sorted({item["provider_id"] for item in model_results})
    return {
        "schema_version": "jhoc-readiness/v1",
        "runtime": health,
        "session_id": session_id,
        "accepted_final_results": accepted,
        "accepted_final_provider_identities": identities,
        "accepted_final_provider_count": len(identities),
        "model_final_results": model_results,
        "model_final_provider_identities": model_identities,
        "model_final_provider_count": len(model_identities),
        "transport_gate": bool(health.get("ok") and health.get("running")),
        "workflow_gate": len(model_identities) >= 2,
        "collaboration_gate": bool(health.get("ok") and health.get("running") and len(model_identities) >= 2),
        "model_evidence": bool(model_results),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--session-id")
    args = parser.parse_args(argv)
    result = inspect_readiness(args.db, host=args.host, port=args.port, session_id=args.session_id)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["collaboration_gate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
