from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time

from jhoc.contracts.errors import ContractError
from .store import LessonEntry, LessonsStore


class LessonsAccumulator:
    """Atomic, lock-protected accumulator for persisting canonical JHOC lessons."""

    CATEGORY_MAP = {
        "cognitive": "01-cognitive-and-sycophancy.md",
        "sycophancy": "01-cognitive-and-sycophancy.md",
        "process": "02-process-and-concurrency.md",
        "concurrency": "02-process-and-concurrency.md",
        "tool": "03-tool-and-storage.md",
        "storage": "03-tool-and-storage.md",
        "testing": "04-testing-and-isolation.md",
        "isolation": "04-testing-and-isolation.md",
    }

    def __init__(self, lessons_dir: Path | str | None = None) -> None:
        if lessons_dir is None:
            self._root = Path(__file__).resolve().parents[3] / "docs" / "lessons"
        else:
            self._root = Path(lessons_dir)
        self._lock_file = self._root / ".lessons.lock"

    def _resolve_target_file(self, category: str) -> Path:
        normalized = category.lower().strip()
        if normalized in self.CATEGORY_MAP:
            target_name = self.CATEGORY_MAP[normalized]
        else:
            # Check if direct match
            candidates = list(self._root.glob(f"*{normalized}*.md"))
            if candidates:
                target_name = candidates[0].name
            else:
                target_name = f"05-{normalized}.md"
        return self._root / target_name

    def append_lesson(
        self,
        *,
        category: str,
        title: str,
        symptom: str,
        root_cause: str,
        rule: str,
        lesson_id: str | None = None,
        timeout: float = 5.0,
    ) -> LessonEntry:
        if not title.strip() or not symptom.strip() or not root_cause.strip() or not rule.strip():
            raise ContractError("Lesson requires non-empty title, symptom, root_cause, and rule")

        self._root.mkdir(parents=True, exist_ok=True)
        target_file = self._resolve_target_file(category)

        # Acquire lock
        lock_fd = self._acquire_lock(timeout)
        try:
            # Read existing content
            if target_file.exists():
                existing_text = target_file.read_text(encoding="utf-8")
            else:
                existing_text = f"# {target_file.stem} - 错题集\n\n"

            # Parse highest existing item number
            matches = re.findall(r"\n##\s+(\d+)\.\s+LESSON", existing_text)
            next_num = max([int(m) for m in matches], default=0) + 1

            if not lesson_id:
                # Find all IDs across all lessons to ensure uniqueness
                store = LessonsStore(self._root)
                all_lessons = store.all_lessons()
                num_ids = [int(l.lesson_id) for l in all_lessons if l.lesson_id.isdigit()]
                next_id = str(max(num_ids, default=0) + 1)
            else:
                next_id = str(lesson_id).replace("#", "").strip()

            new_block = (
                f"\n\n---\n\n"
                f"## {next_num}. LESSON #{next_id}: {title.strip()}\n"
                f"- **症状**：{symptom.strip()}\n"
                f"- **根因**：{root_cause.strip()}\n"
                f"- **规约**：{rule.strip()}\n"
            )

            updated_text = existing_text.rstrip() + new_block

            # Write atomically via temp file
            temp_fd, temp_path = tempfile.mkstemp(dir=self._root, prefix="lesson_tmp_", suffix=".md")
            with open(temp_fd, "w", encoding="utf-8") as f:
                f.write(updated_text)

            # Atomic replace
            os.replace(temp_path, target_file)

            entry = LessonEntry(
                lesson_id=next_id,
                category=target_file.stem,
                title=title.strip(),
                symptom=symptom.strip(),
                root_cause=root_cause.strip(),
                rule=rule.strip(),
                source_file=target_file.name,
            )

            # 遵循 Rule 6 五元组存证与 Tier A 操作审计：持久化落地 op-log
            self._write_audit_log(entry)

            return entry
        finally:
            self._release_lock(lock_fd)

    def _write_audit_log(self, entry: LessonEntry) -> None:
        try:
            op_log_dir = self._root.resolve().parents[1] / "logs" / "op-log"
            if not op_log_dir.exists():
                return

            now = datetime.now(timezone.utc)
            date_str = now.strftime("%Y%m%d")
            time_iso = now.isoformat()

            # 1. 落地 Markdown 审计单
            op_file = op_log_dir / f"{date_str}-lesson-append-{entry.lesson_id}.md"
            audit_md = (
                f"# Operation Log — Canonical Lesson Append\n\n"
                f"- **Timestamp (UTC)**: `{time_iso}`\n"
                f"- **Actor**: `LessonsAccumulator`\n"
                f"- **Target File**: `docs/lessons/{entry.source_file}`\n"
                f"- **Lesson ID**: `#{entry.lesson_id}`\n"
                f"- **Title**: {entry.title}\n"
                f"- **Category**: {entry.category}\n"
                f"- **Rule Preview**: {entry.rule[:80]}...\n"
                f"- **Governance Status**: COMPLIANT (Tier A Audited)\n"
            )
            op_file.write_text(audit_md, encoding="utf-8")

            # 2. 追加至结构化 JSONL 事件流
            shadow_file = op_log_dir / "v3_lite_experience_shadow.jsonl"
            event = {
                "event": "LESSON_APPENDED",
                "timestamp": time_iso,
                "lesson_id": entry.lesson_id,
                "category": entry.category,
                "title": entry.title,
                "file": entry.source_file,
            }
            with open(shadow_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            # 审计写入失败不应阻断核心业务，但保留静默安全
            pass

    def _acquire_lock(self, timeout: float) -> int:
        start_time = time.monotonic()
        while True:
            try:
                # Open with O_CREAT | O_EXCL for atomic creation
                fd = os.open(str(self._lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                return fd
            except FileExistsError:
                if time.monotonic() - start_time >= timeout:
                    raise ContractError(f"Timed out acquiring lessons lock: {self._lock_file}")
                time.sleep(0.05)

    def _release_lock(self, fd: int) -> None:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            if self._lock_file.exists():
                self._lock_file.unlink()
        except OSError:
            pass
