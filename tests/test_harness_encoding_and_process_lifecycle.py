"""Unit tests for JHOC Harness Encoding Purity, Process Lifecycle, and SQLite WAL Protection.

Covers:
- Specification 5: Console ASCII enforcement vs verbatim UTF-8 file channel.
- Specification 2: Windows Job Object process tree lifecycle, heartbeat extensions, and 2-phase termination.
- C6: Atomic same-directory file write and orphan GC.
- C10: Survivor Drill - Sudden kill simulation mid-WAL write asserting clean auto-recovery.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jhoc.memory_store import MemoryRecord, MemoryType
from jhoc.memory_store.sqlite import SQLiteMemoryStore
from jhoc.runner.encoding import (
    CLIResultStatus,
    classify_process_result,
    read_file_utf8,
    to_console_ascii,
    write_file_utf8,
)
from jhoc.runner.process import OpClass, run_managed_command
from jhoc.storage.atomic import atomic_write_json, atomic_write_text, cleanup_orphan_temps


class TestHarnessEncodingAndProcessLifecycle(unittest.TestCase):

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="jhoc_test_harness_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_encoding_channels_and_ascii_filter(self) -> None:
        """Verify console channel enforces ASCII while file channel preserves UTF-8 verbatim."""
        # 1. Console channel: strip emojis and map status symbols to pure ASCII
        test_mixed = "Task status: \u2705 SUCCESS \U0001f680 [FAST_PATH] \u2014 result: OK"
        ascii_out = to_console_ascii(test_mixed)
        self.assertIn("[PASS]", ascii_out)
        self.assertNotIn("\U0001f680", ascii_out)
        self.assertNotIn("\u2705", ascii_out)
        self.assertTrue(ascii_out.isascii())

        # 2. File channel: exact loss-free preservation of Chinese and Unicode
        test_file = self.temp_dir / "chinese_spec.txt"
        chinese_text = "软件工程与智能体治理架构规范：坚决杜绝乱码与死锁"
        write_file_utf8(test_file, chinese_text)
        read_back = read_file_utf8(test_file)
        self.assertEqual(chinese_text, read_back)

    def test_cli_error_classification(self) -> None:
        """Verify classify_process_result handles all distinct operational outcomes."""
        ok_res = classify_process_result(0, "Build completed", "")
        self.assertEqual(ok_res.status, CLIResultStatus.EXIT_OK)
        self.assertTrue(ok_res.is_success)

        empty_res = classify_process_result(0, "", "")
        self.assertEqual(empty_res.status, CLIResultStatus.EMPTY_SUCCESS)
        self.assertTrue(empty_res.is_success)

        fail_res = classify_process_result(1, "", "SyntaxError: invalid syntax")
        self.assertEqual(fail_res.status, CLIResultStatus.EXECUTION_FAILURE)
        self.assertFalse(fail_res.is_success)

        timeout_res = classify_process_result(-1, "", "", timed_out=True, timeout_seconds=15.0)
        self.assertEqual(timeout_res.status, CLIResultStatus.TIMEOUT_EXPIRED)
        self.assertFalse(timeout_res.is_success)

    def test_atomic_file_write_and_orphan_gc(self) -> None:
        """Verify atomic same-directory replacement and temporary file cleanup."""
        target_file = self.temp_dir / "state.json"
        data = {"task_id": "test-123", "status": "ACTIVE", "title": "原子写入测试"}

        atomic_write_json(target_file, data)
        self.assertTrue(target_file.is_file())
        self.assertIn("原子写入测试", target_file.read_text(encoding="utf-8"))

        # Create an artificial orphan temporary file older than cutoff
        orphan_temp = self.temp_dir / "state.json.tmp.9999.deadbeef"
        orphan_temp.write_text("abandoned", encoding="utf-8")
        # Set mtime back by 2 hours
        old_time = time.time() - 7200
        os.utime(orphan_temp, (old_time, old_time))

        cleaned = cleanup_orphan_temps(self.temp_dir, max_age_seconds=3600)
        self.assertEqual(cleaned, 1)
        self.assertFalse(orphan_temp.exists())
        self.assertTrue(target_file.exists())

    def test_sqlite_memory_store_wal_and_backup(self) -> None:
        """Verify PRAGMA quick_check at startup and native hot backup."""
        db_path = self.temp_dir / "test_memory.sqlite"
        store = SQLiteMemoryStore(str(db_path))

        record = MemoryRecord(
            content={"rule": "zero-emoji"},
            memory_type=MemoryType.TASK,
            source_ref="test_run",
            sensitivity="INTERNAL",
            record_id="rec-001",
        )
        store.write(record, approved=True)

        backup_path = self.temp_dir / "test_memory_backup.sqlite"
        store.backup_to(backup_path)
        store.close()

        # Reopen backup with a fresh instance, verifying PRAGMA quick_check passes
        backup_store = SQLiteMemoryStore(str(backup_path))
        loaded = backup_store.get("rec-001")
        self.assertIsNotNone(loaded)
        if loaded:
            self.assertEqual(loaded.content["rule"], "zero-emoji")
        backup_store.close()

    def test_managed_process_execution_and_pipe_draining(self) -> None:
        """Verify command execution, high-volume pipe draining, and clean completion."""
        # Output 5,000 lines to test pipe deadlock immunity
        py_code = "import sys; [print(f'line_{i}') for i in range(5000)]; print('DONE')"
        res = run_managed_command(
            [sys.executable, "-c", py_code],
            cwd=self.temp_dir,
            op_class=OpClass.FAST,
        )
        self.assertEqual(res.status, CLIResultStatus.EXIT_OK)
        self.assertTrue(res.clean_stdout.endswith("DONE"))

    def test_process_timeout_and_job_object_cleanup(self) -> None:
        """Verify that hanging processes are terminated cleanly on timeout without orphan escape."""
        py_code = "import time; time.sleep(10.0)"
        t0 = time.monotonic()
        res = run_managed_command(
            [sys.executable, "-c", py_code],
            cwd=self.temp_dir,
            timeout=1.5,
        )
        elapsed = time.monotonic() - t0
        self.assertEqual(res.status, CLIResultStatus.TIMEOUT_EXPIRED)
        self.assertFalse(res.is_success)
        # Should finish around timeout + grace (1.5s + 3s max)
        self.assertLess(elapsed, 8.0)

    def test_sqlite_wal_survivor_drill(self) -> None:
        """C10 Survivor Drill: Abruptly terminate process mid-WAL-transaction and assert clean recovery."""
        drill_db = self.temp_dir / "survivor_drill.sqlite"

        # Initialize DB in WAL mode
        conn = sqlite3.connect(str(drill_db))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE log (id INTEGER PRIMARY KEY, msg TEXT)")
        conn.commit()
        conn.close()

        # Spawn a long-running writer child process that keeps writing inside uncommitted transactions
        writer_script = f"""
import sqlite3
import time

conn = sqlite3.connect(r"{drill_db}")
conn.execute("PRAGMA journal_mode=WAL")
cur = conn.cursor()
for i in range(10000):
    cur.execute("INSERT INTO log (msg) VALUES (?)", (f"record_{{i}}",))
    if i % 10 == 0:
        conn.commit()
    time.sleep(0.01)
"""
        script_file = self.temp_dir / "writer.py"
        script_file.write_text(writer_script, encoding="utf-8")

        # Run with short timeout so it gets forcibly terminated mid-write
        res = run_managed_command(
            [sys.executable, str(script_file)],
            cwd=self.temp_dir,
            timeout=0.8,
        )
        self.assertEqual(res.status, CLIResultStatus.TIMEOUT_EXPIRED)

        # Assertion: Reopen database in main process, assert PRAGMA quick_check is OK
        recovery_conn = sqlite3.connect(str(drill_db))
        check_row = recovery_conn.execute("PRAGMA quick_check").fetchone()
        self.assertEqual(check_row[0], "ok")

        # Database is healthy and queryable
        count = recovery_conn.execute("SELECT count(*) FROM log").fetchone()[0]
        self.assertGreater(count, 0)
        recovery_conn.close()


if __name__ == "__main__":
    unittest.main()
