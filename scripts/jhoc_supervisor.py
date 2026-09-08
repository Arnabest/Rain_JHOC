"""Run the single persistent JHOC supervisor process.

This is the only long-lived runtime entrypoint.  Provider adapters connect via
the Python ``JHOCSupervisor`` API and may reconnect without restarting JHOC.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import signal
import sys
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.application import ApplicationConfig, JHOCApplication  # noqa: E402
from jhoc.supervisor import JHOCSupervisorServer  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="JHOC SQLite runtime path")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    app = JHOCApplication(ApplicationConfig(Path(args.db).expanduser().resolve()))
    stopping = Event()
    endpoint = None
    for name in ("SIGINT", "SIGTERM"):
        value = getattr(signal, name, None)
        if value is not None:
            signal.signal(value, lambda *_: stopping.set())
    try:
        health = app.start()
        endpoint = JHOCSupervisorServer(app.supervisor, host=args.host, port=args.port)
        endpoint.start()
        print(json.dumps({"ok": True, **asdict(health)}, default=str, sort_keys=True), flush=True)
        stopping.wait()
        return 0
    finally:
        if endpoint is not None:
            endpoint.stop()
        app.stop()


if __name__ == "__main__":
    raise SystemExit(main())
