"""JHOC Process Lifecycle & Windows Job Object Management.

Enforces robust process execution, two-phase graceful termination,
pipe deadlock immunity via concurrent reader threads, and Windows Job Object
binding to eliminate orphan processes. Conforms to Rule 5 and Rule 7.
"""

from __future__ import annotations

from collections import deque
import ctypes
from ctypes import wintypes
from enum import Enum
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Mapping, Sequence

from .encoding import (
    CLIResultStatus,
    ProcessClassification,
    classify_process_result,
    get_subprocess_env,
)


class OpClass(float, Enum):
    FAST = 15.0         # Quick status, lint, token-stats
    NORMAL = 60.0       # Single unit test, tool invocation
    HEAVY = 180.0       # Full test discovery, git checkout, compilation
    DEEP_REVIEW = 300.0 # Multi-model adversarial co-review / deep reasoning


# Win32 Job Object ctypes structures (Windows only)
if sys.platform == "win32":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryLimit", ctypes.c_size_t),
            ("PeakJobMemoryLimit", ctypes.c_size_t),
        ]


class WindowsJobObject:
    """Encapsulates a Windows Job Object configured with KILL_ON_JOB_CLOSE."""

    def __init__(self) -> None:
        self.h_job: wintypes.HANDLE | None = None
        if sys.platform == "win32":
            try:
                h = kernel32.CreateJobObjectW(None, None)
                if h:
                    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                    if kernel32.SetInformationJobObject(h, 9, ctypes.byref(info), ctypes.sizeof(info)):
                        self.h_job = h
                    else:
                        kernel32.CloseHandle(h)
            except Exception:
                self.h_job = None

    def assign_process(self, proc_handle: int) -> bool:
        if self.h_job and sys.platform == "win32":
            try:
                return bool(kernel32.AssignProcessToJobObject(self.h_job, proc_handle))
            except Exception:
                return False
        return False

    def terminate(self, exit_code: int = 1) -> bool:
        if self.h_job and sys.platform == "win32":
            try:
                return bool(kernel32.TerminateJobObject(self.h_job, exit_code))
            except Exception:
                return False
        return False

    def close(self) -> None:
        if self.h_job and sys.platform == "win32":
            try:
                kernel32.CloseHandle(self.h_job)
            except Exception:
                pass
            finally:
                self.h_job = None


class ManagedProcessRunner:
    """Executes a command with heartbeat monitoring, pipe draining, and 2-phase cleanup."""

    def __init__(
        self,
        command: Sequence[str] | str,
        *,
        cwd: str | Path | None = None,
        timeout: float = OpClass.NORMAL.value,
        hard_cap: float | None = None,
        heartbeat_window: float = 15.0,
        grace_period: float = 3.0,
        input_text: str | None = None,
        extra_env: Mapping[str, str] | None = None,
    ) -> None:
        self.command = command
        self.cwd = str(cwd) if cwd else None
        self.timeout = float(timeout)
        self.hard_cap = float(hard_cap) if hard_cap else float(timeout * 2.5)
        self.heartbeat_window = float(heartbeat_window)
        self.grace_period = float(grace_period)
        self.input_text = input_text
        self.extra_env = extra_env

        self.stdout_chunks: list[str] = []
        self.stderr_chunks: list[str] = []
        self.last_output_time: float | None = None
        self.recent_lines = deque(maxlen=20)
        self.repeated_line_count = 0

    def _drain_stream(self, stream, target_list: list[str]) -> None:
        try:
            for line in iter(stream.readline, ""):
                target_list.append(line)
                clean = line.strip()
                now = time.monotonic()
                if clean:
                    if self.recent_lines and clean == self.recent_lines[-1]:
                        self.repeated_line_count += 1
                    else:
                        self.repeated_line_count = 0
                    self.recent_lines.append(clean)
                    # Only reset heartbeat if not stuck in infinite repetitive spinner
                    if self.repeated_line_count < 100:
                        self.last_output_time = now
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def run(self) -> ProcessClassification:
        start_time = time.monotonic()
        current_deadline = start_time + self.timeout
        absolute_cutoff = start_time + self.hard_cap

        job_obj = WindowsJobObject()
        env = get_subprocess_env(self.extra_env)

        creationflags = 0
        if sys.platform == "win32":
            creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            p = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                stdin=subprocess.PIPE if self.input_text is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creationflags,
            )
        except Exception as exc:
            job_obj.close()
            return ProcessClassification(
                status=CLIResultStatus.TRANSPORT_ERROR,
                returncode=-1,
                is_success=False,
                diagnostic=f"Failed to spawn process: {exc}",
                clean_stdout="",
                clean_stderr=str(exc),
            )

        if sys.platform == "win32" and hasattr(p, "_handle"):
            job_obj.assign_process(int(p._handle))

        # Spawn concurrent drain threads immediately before handling stdin
        t_out = threading.Thread(target=self._drain_stream, args=(p.stdout, self.stdout_chunks), daemon=True)
        t_err = threading.Thread(target=self._drain_stream, args=(p.stderr, self.stderr_chunks), daemon=True)
        t_out.start()
        t_err.start()

        # Write stdin asynchronously to prevent deadlocks when child floods stdout before reading stdin
        if self.input_text is not None and p.stdin:
            def _pump_stdin() -> None:
                try:
                    if p.stdin:
                        p.stdin.write(self.input_text)
                        p.stdin.flush()
                        p.stdin.close()
                except Exception:
                    pass
            t_in = threading.Thread(target=_pump_stdin, daemon=True)
            t_in.start()
        elif p.stdin:
            try:
                p.stdin.close()
            except Exception:
                pass

        timed_out = False
        while True:
            ret = p.poll()
            if ret is not None:
                break

            now = time.monotonic()
            if now > absolute_cutoff:
                timed_out = True
                break

            # Heartbeat extension logic: only extend if output was actually observed recently
            if self.last_output_time is not None and (now - self.last_output_time < self.heartbeat_window):
                extended = now + self.heartbeat_window
                if extended > current_deadline:
                    current_deadline = min(extended, absolute_cutoff)

            if now > current_deadline:
                timed_out = True
                break

            time.sleep(0.1)

        if timed_out:
            # Phase 1: Graceful attempt
            try:
                if sys.platform == "win32":
                    p.terminate()
                else:
                    p.send_signal(subprocess.signal.SIGTERM)
            except Exception:
                pass

            grace_start = time.monotonic()
            while time.monotonic() - grace_start < self.grace_period:
                if p.poll() is not None:
                    break
                time.sleep(0.1)

            # Phase 2: Force termination via Job Object or kill
            if p.poll() is None:
                if not job_obj.terminate(1):
                    try:
                        p.kill()
                    except Exception:
                        pass
                try:
                    p.wait(timeout=2.0)
                except Exception:
                    pass

        # Ensure drain threads finish
        t_out.join(timeout=1.0)
        t_err.join(timeout=1.0)

        raw_stdout = "".join(self.stdout_chunks)
        raw_stderr = "".join(self.stderr_chunks)
        final_rc = p.returncode if p.returncode is not None else -1

        job_obj.close()
        elapsed = time.monotonic() - start_time

        return classify_process_result(
            returncode=final_rc,
            stdout=raw_stdout,
            stderr=raw_stderr,
            timed_out=timed_out,
            timeout_seconds=elapsed,
        )


def run_managed_command(
    command: Sequence[str] | str,
    *,
    cwd: str | Path | None = None,
    op_class: OpClass = OpClass.NORMAL,
    timeout: float | None = None,
    input_text: str | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> ProcessClassification:
    """Primary entry point for running commands with full lifecycle guarantees."""
    eff_timeout = float(timeout) if timeout is not None else op_class.value
    runner = ManagedProcessRunner(
        command,
        cwd=cwd,
        timeout=eff_timeout,
        input_text=input_text,
        extra_env=extra_env,
    )
    return runner.run()
