"""JHOC Harness Encoding & Channel Separation Framework.

Strictly enforces Rule 7 (Zero-Emoji & Console ASCII Discipline) while guaranteeing
100% loss-free UTF-8 verbatim serialization for file storage and code persistence.
Provides structured CLI outcome classification without masking underlying exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import re
import sys
from typing import Mapping


class CLIResultStatus(str, Enum):
    EXIT_OK = "EXIT_OK"
    EMPTY_SUCCESS = "EMPTY_SUCCESS"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    TIMEOUT_EXPIRED = "TIMEOUT_EXPIRED"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"


@dataclass(frozen=True, slots=True)
class ProcessClassification:
    status: CLIResultStatus
    returncode: int
    is_success: bool
    diagnostic: str
    clean_stdout: str
    clean_stderr: str


def to_console_ascii(text: str) -> str:
    """Format text for console display: strictly ASCII-safe without emojis.
    
    Replaces non-ASCII or high-order Unicode with ASCII equivalents or escapes
    to guarantee crash-free rendering across legacy Windows consoles (CP936/GBK/OEM).
    """
    if not text:
        return ""

    # Filter common non-ASCII symbols into safe ASCII equivalents
    replacements = {
        "\u2705": "[PASS]",
        "\u274c": "[FAIL]",
        "\u26a0": "[WARN]",
        "\u2192": "->",
        "\u2190": "<-",
        "\u2014": "--",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u00a9": "(C)",
        "\u20ac": "EUR",
    }
    for orig, rep in replacements.items():
        text = text.replace(orig, rep)

    # Strip variation selectors, zero-width joiners/non-joiners, keycaps, and format controls
    text = re.sub(r"[\ufe00-\ufe0f\u200b-\u200f\u2028-\u202f\u20e3\u200c\u200d]", "", text)

    # Strip astral emojis (range 0x10000 - 0x10FFFF)
    text = re.sub(r"[\U00010000-\U0010ffff]+", "[EMOJI_FILTERED]", text)

    # Strip BMP emoji & symbol ranges (Dingbats, Misc symbols, Misc technical)
    text = re.sub(r"[\u2600-\u27bf\u2300-\u23ff]+", "[EMOJI_FILTERED]", text)

    # Collapse duplicate [EMOJI_FILTERED] tags
    text = re.sub(r"(\[EMOJI_FILTERED\])+", "[EMOJI_FILTERED]", text)

    return text


def to_file_utf8(text: str) -> bytes:
    """Encode text for file-channel persistence: verbatim UTF-8 bytes."""
    return text.encode("utf-8")


def read_file_utf8(file_path: Path | str) -> str:
    """Read file content with strict UTF-8 decoding, raising on corrupt byte streams."""
    path = Path(file_path)
    return path.read_text(encoding="utf-8")


def write_file_utf8(file_path: Path | str, content: str) -> int:
    """Write text content to file with strict UTF-8 encoding."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.write_text(content, encoding="utf-8")


SENSITIVE_SUBPROCESS_ENV_KEYS = frozenset({
    "JHOC_OPERATOR_TOKEN",
    "JHOC_OPERATOR_SECRET",
    "OPERATOR_TOKEN",
    "OPERATOR_SECRET",
})


def get_subprocess_env(extra_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Construct a clean, unified subprocess environment enforcing UTF-8 and scrubbing secrets."""
    base_env = os.environ.copy()
    for sensitive_key in SENSITIVE_SUBPROCESS_ENV_KEYS:
        base_env.pop(sensitive_key, None)

    base_env["PYTHONUTF8"] = "1"
    base_env["PYTHONIOENCODING"] = "utf-8"
    base_env["LC_ALL"] = "C.UTF-8"
    base_env["LANG"] = "C.UTF-8"
    if extra_env:
        base_env.update(extra_env)
    return base_env


def classify_process_result(
    returncode: int,
    stdout: str,
    stderr: str,
    *,
    timed_out: bool = False,
    timeout_seconds: float | None = None,
) -> ProcessClassification:
    """Classify process execution outcome without swallowing harness faults."""
    clean_out = stdout.strip() if stdout else ""
    clean_err = stderr.strip() if stderr else ""

    if timed_out:
        dur_msg = f" after {timeout_seconds:.1f}s" if timeout_seconds else ""
        return ProcessClassification(
            status=CLIResultStatus.TIMEOUT_EXPIRED,
            returncode=-1,
            is_success=False,
            diagnostic=f"Command execution timed out{dur_msg}.",
            clean_stdout=clean_out,
            clean_stderr=clean_err,
        )

    # Check transport errors (e.g. interpreter not found)
    # Note: 127 is a POSIX convention for 'command not found'; on Windows only map if stderr mentions it
    is_not_found = "is not recognized as an internal or external command" in clean_err
    if (returncode == 127 and sys.platform != "win32") or is_not_found:
        return ProcessClassification(
            status=CLIResultStatus.TRANSPORT_ERROR,
            returncode=returncode,
            is_success=False,
            diagnostic=f"Command binary not found or unreachable: {clean_err}",
            clean_stdout=clean_out,
            clean_stderr=clean_err,
        )

    # Map Windows NTSTATUS exit codes (access violation, control-c exit, dll missing)
    nt_signals = {
        -1073741819: "STATUS_ACCESS_VIOLATION (0xC0000005)",
        -1073741510: "STATUS_CONTROL_C_EXIT (0xC000013A)",
        -1073741515: "STATUS_DLL_NOT_FOUND (0xC0000135)",
    }
    if returncode in nt_signals:
        desc = nt_signals[returncode]
        diag = f"{desc}: {clean_err or clean_out or 'Process terminated abruptly.'}"
        return ProcessClassification(
            status=CLIResultStatus.EXECUTION_FAILURE,
            returncode=returncode,
            is_success=False,
            diagnostic=diag,
            clean_stdout=clean_out,
            clean_stderr=clean_err,
        )

    if returncode != 0:
        diag = clean_err or clean_out or f"Process exited with non-zero code {returncode}."
        return ProcessClassification(
            status=CLIResultStatus.EXECUTION_FAILURE,
            returncode=returncode,
            is_success=False,
            diagnostic=diag,
            clean_stdout=clean_out,
            clean_stderr=clean_err,
        )

    # Returncode is 0
    if not clean_out and not clean_err:
        return ProcessClassification(
            status=CLIResultStatus.EMPTY_SUCCESS,
            returncode=0,
            is_success=True,
            diagnostic="Command finished with empty output.",
            clean_stdout="",
            clean_stderr="",
        )

    return ProcessClassification(
        status=CLIResultStatus.EXIT_OK,
        returncode=0,
        is_success=True,
        diagnostic="Execution successful.",
        clean_stdout=clean_out,
        clean_stderr=clean_err,
    )
