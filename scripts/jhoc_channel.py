"""CLI boundary for AI Box and Verse Agent to enter JHOC locally."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.channel import ChannelGateway  # noqa: E402
from jhoc.relay import SQLiteRelay  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="JHOC SQLite runtime path")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health")
    send = commands.add_parser("send")
    send.add_argument("--source-id", required=True)
    send.add_argument("--event", required=True)
    send.add_argument("--payload-json", default="{}")
    send.add_argument("--correlation-id")
    send.add_argument("--message-id")
    receipt = commands.add_parser("receipt")
    receipt.add_argument("--message-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db_path = Path(args.db).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    relay = SQLiteRelay(str(db_path))
    try:
        gateway = ChannelGateway(relay)
        if args.command == "health":
            result = gateway.health().to_dict()
        elif args.command == "send":
            payload = json.loads(args.payload_json)
            if not isinstance(payload, dict):
                raise ValueError("payload JSON must be an object")
            result = gateway.accept(
                args.source_id,
                args.event,
                payload,
                correlation_id=args.correlation_id,
                message_id=args.message_id,
            ).to_dict()
        else:
            receipt = gateway.receipt(args.message_id)
            if receipt is None:
                print(json.dumps({"ok": False, "error": "receipt_not_found"}, sort_keys=True))
                return 3
            result = receipt.to_dict()
        print(json.dumps({"ok": True, **result}, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({"ok": False, "error": type(error).__name__, "detail": str(error)}, sort_keys=True))
        return 2
    finally:
        relay.close()


if __name__ == "__main__":
    raise SystemExit(main())
