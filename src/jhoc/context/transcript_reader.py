"""JHOC Shared Robust Transcript Reader.

Implements Condition C8 from Multi-Model Co-Review:
- Backward block-seeking algorithm with JSONL line-boundary alignment.
- Scans up to 1MB or full file without naive 16KB tail truncation.
- Aggregates ALL assistant segments (MODEL/PLANNER_RESPONSE) and ALL tool calls
  between the latest USER_INPUT and EOF into a single consolidated TurnRecord.
- Strictly adheres to Rule 7 (Zero-Emoji Discipline) and Rule 2 (Fail-Closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class TurnRecord:
    user_prompt: str
    assistant_text: str
    tool_calls: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    has_user_input: bool = False
    has_assistant_response: bool = False
    turn_steps_count: int = 0
    is_truncated: bool = False


def extract_last_turn_from_transcript(
    transcript_path: Path | str,
    max_search_bytes: int = 64 * 1024 * 1024,  # Stream backward up to 64MB
    block_size: int = 128 * 1024,  # 128KB blocks
) -> TurnRecord:
    """Extracts the latest complete conversational turn from transcript.jsonl.

    Aggregates all assistant segments and tool calls between the latest USER_INPUT and EOF.
    Streams backward block-by-block until USER_INPUT is discovered.
    """
    p = Path(transcript_path)
    if not p.is_file():
        return TurnRecord(user_prompt="", assistant_text="", tool_calls=())

    try:
        file_size = p.stat().st_size
        if file_size == 0:
            return TurnRecord(user_prompt="", assistant_text="", tool_calls=())

        user_prompt = ""
        assistant_segments: list[str] = []
        collected_tool_calls: list[dict[str, Any]] = []
        steps_count = 0
        found_user = False
        reached_file_start = False
        bytes_searched = 0

        with open(p, "rb") as f:
            cursor = file_size
            remainder = b""
            while cursor > 0 and not found_user and bytes_searched < max_search_bytes:
                read_size = min(block_size, cursor)
                cursor -= read_size
                bytes_searched += read_size
                f.seek(cursor)
                chunk = f.read(read_size) + remainder
                raw_lines = chunk.split(b"\n")
                if cursor > 0:
                    remainder = raw_lines[0]
                    lines_to_process = raw_lines[1:]
                else:
                    remainder = b""
                    lines_to_process = raw_lines
                    reached_file_start = True

                for raw_l in reversed(lines_to_process):
                    l_str = raw_l.decode("utf-8", errors="replace").strip()
                    if not l_str:
                        continue
                    try:
                        data = json.loads(l_str)
                    except Exception:
                        continue

                    stype = str(data.get("type", "")).strip().upper()
                    steps_count += 1

                    if stype == "USER_INPUT":
                        content = str(data.get("content", "")).strip()
                        m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
                        user_prompt = m.group(1).strip() if m else content
                        found_user = True
                        break

                    if stype in {"MODEL", "PLANNER_RESPONSE"}:
                        content = str(data.get("content", "")).strip()
                        if content:
                            assistant_segments.append(content)

                    tcs = data.get("tool_calls")
                    if isinstance(tcs, list) and tcs:
                        for tc in tcs:
                            if isinstance(tc, dict):
                                collected_tool_calls.append(tc)
                    elif "tool" in data or "toolCall" in data or "tool_name" in data or "args" in data:
                        collected_tool_calls.append(data)

        assistant_segments.reverse()
        collected_tool_calls.reverse()
        consolidated_assistant_text = "\n\n".join(assistant_segments).strip()

        is_trunc = not found_user and (bytes_searched >= max_search_bytes or not reached_file_start)

        return TurnRecord(
            user_prompt=user_prompt,
            assistant_text=consolidated_assistant_text,
            tool_calls=tuple(collected_tool_calls),
            has_user_input=found_user,
            has_assistant_response=bool(consolidated_assistant_text),
            turn_steps_count=steps_count,
            is_truncated=is_trunc,
        )
    except Exception:
        return TurnRecord(user_prompt="", assistant_text="", tool_calls=(), is_truncated=True)
