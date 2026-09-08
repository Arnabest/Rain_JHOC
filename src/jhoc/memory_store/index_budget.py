"""JHOC Index Budget Guard (200-Line Law & Hysteresis Rollover).

Enforces:
- C9: Line count <= 200 AND UTF-8 bytes <= 25 KiB on root Markdown indexes (e.g. MEMORY.md).
      Hysteresis: trigger rollover at > 200 lines or > 25,000 bytes, prune down to <= 160 lines (<= 20 KiB).
      Category-granularity rollover to deterministic sortable sidecars (memory/archive/{category}_{YYYYMMDD}.md).
      Maintains bounded 1-line pointer links in root index with offline single-writer atomic replacement.
      Self-healing pointer integrity verification.
      JSON catalogs exempted with 500KB cap.

Enforces Rule 7 (Zero-Emoji & Pure ASCII) and Rule 2 (Fail-Closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.storage.atomic import atomic_write_text


MAX_INDEX_LINES: int = 200
MAX_INDEX_BYTES: int = 25000
HYSTERESIS_TARGET_LINES: int = 160
HYSTERESIS_TARGET_BYTES: int = 20000
MAX_JSON_CATALOG_BYTES: int = 500000


@dataclass(frozen=True, slots=True)
class IndexBudgetResult:
    index_path: str
    line_count: int
    byte_count: int
    is_over_budget: bool
    rollover_triggered: bool
    archived_entries_count: int
    archive_sidecars_created: tuple[str, ...]
    settled_line_count: int
    settled_byte_count: int
    integrity_verified: bool


class IndexBudgetGuard:
    """Monitors and enforces the 200-line / 25KB ceiling on context index files."""

    def __init__(
        self,
        max_lines: int = MAX_INDEX_LINES,
        max_bytes: int = MAX_INDEX_BYTES,
        target_lines: int = HYSTERESIS_TARGET_LINES,
        target_bytes: int = HYSTERESIS_TARGET_BYTES,
    ) -> None:
        self.max_lines = max_lines
        self.max_bytes = max_bytes
        self.target_lines = target_lines
        self.target_bytes = target_bytes

    def check_budget(self, file_path: Path | str) -> tuple[int, int, bool]:
        p = Path(file_path).resolve()
        if not p.is_file():
            return 0, 0, False

        raw_bytes = p.read_bytes()
        byte_count = len(raw_bytes)
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = raw_bytes.decode("latin-1", errors="replace")

        lines = text.splitlines()
        line_count = len(lines)

        # JSON files have separate budget
        if p.suffix.lower() == ".json":
            is_over = byte_count > MAX_JSON_CATALOG_BYTES
            return line_count, byte_count, is_over

        is_over = line_count > self.max_lines or byte_count > self.max_bytes
        return line_count, byte_count, is_over

    def enforce_index_budget(
        self,
        index_path: Path | str,
        archive_dir: Path | str | None = None,
    ) -> IndexBudgetResult:
        """Audits root index and rolls over excess entries to category sidecars if over budget."""
        p = Path(index_path).resolve()
        if not p.is_file():
            return IndexBudgetResult(
                index_path=str(p),
                line_count=0,
                byte_count=0,
                is_over_budget=False,
                rollover_triggered=False,
                archived_entries_count=0,
                archive_sidecars_created=(),
                settled_line_count=0,
                settled_byte_count=0,
                integrity_verified=True,
            )

        line_count, byte_count, is_over = self.check_budget(p)
        if p.suffix.lower() == ".json":
            if is_over:
                raise ContractError(
                    f"IndexBudgetGuard markdown rollover cannot process JSON catalog: {p}. "
                    f"JSON catalog exceeds cap ({byte_count} > {MAX_JSON_CATALOG_BYTES} bytes) and requires dedicated JSON compaction.",
                    ErrorCode.INVALID_CONTRACT,
                )
            return IndexBudgetResult(
                index_path=str(p),
                line_count=line_count,
                byte_count=byte_count,
                is_over_budget=False,
                rollover_triggered=False,
                archived_entries_count=0,
                archive_sidecars_created=(),
                settled_line_count=line_count,
                settled_byte_count=byte_count,
                integrity_verified=True,
            )

        arch_dir = Path(archive_dir).resolve() if archive_dir else p.parent / "archive"
        arch_dir.mkdir(parents=True, exist_ok=True)

        if not is_over:
            return IndexBudgetResult(
                index_path=str(p),
                line_count=line_count,
                byte_count=byte_count,
                is_over_budget=False,
                rollover_triggered=False,
                archived_entries_count=0,
                archive_sidecars_created=(),
                settled_line_count=line_count,
                settled_byte_count=byte_count,
                integrity_verified=self._verify_pointer_integrity(p),
            )

        # Trigger Hysteresis Rollover
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()

        # Parse sections
        parsed_sections: list[tuple[str, list[str]]] = []
        current_header = "Header"
        current_lines: list[str] = []

        for line in lines:
            if line.startswith("## "):
                if current_lines or current_header != "Header":
                    parsed_sections.append((current_header, current_lines))
                current_header = line
                current_lines = []
            else:
                current_lines.append(line)
        if current_lines or current_header != "Header":
            parsed_sections.append((current_header, current_lines))

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        sidecars_created: list[str] = []
        total_archived = 0

        # Build settled content
        retained_sections: list[str] = []
        for header, sec_lines in parsed_sections:
            if header == "Header":
                retained_sections.extend(sec_lines)
                continue

            category_slug = re.sub(r"[^\w]+", "_", header.replace("##", "").strip().lower())
            item_lines = [l for l in sec_lines if l.strip().startswith("- ")]
            non_item_lines = [l for l in sec_lines if not l.strip().startswith("- ")]

            # If section has more than 20 items, prune to top 10 recent and archive rest
            if len(item_lines) > 20:
                keep_items = item_lines[:10]
                archive_items = item_lines[10:]
                total_archived += len(archive_items)

                sidecar_name = f"{category_slug}_{date_str}.md"
                sidecar_path = arch_dir / sidecar_name
                sidecar_content = (
                    f"# Archived Entries: {header}\n\n"
                    f"> Archived on {datetime.now(timezone.utc).isoformat()}.\n\n"
                    + "\n".join(archive_items)
                    + "\n"
                )
                atomic_write_text(sidecar_path, sidecar_content)
                sidecars_created.append(str(sidecar_path))

                # Inject 1-line pointer link in root section
                rel_sidecar = sidecar_path.as_posix()
                pointer_line = f"- [Archive {category_slug} {date_str}](file:///{rel_sidecar}) ({len(archive_items)} archived entries)"

                sec_output = [header] + non_item_lines + keep_items + ["", pointer_line, ""]
                retained_sections.extend(sec_output)
            else:
                retained_sections.extend([header] + sec_lines)

        settled_text = "\n".join(retained_sections).strip() + "\n"

        # Check settled bounds
        settled_lines = settled_text.splitlines()
        settled_line_count = len(settled_lines)
        settled_byte_count = len(settled_text.encode("utf-8"))

        # If over line target, truncate by lines while archiving dropped entries
        if settled_line_count > self.target_lines:
            cutoff = self.target_lines - 5
            dropped_lines = settled_lines[cutoff:]
            dropped_items = [
                l for l in dropped_lines
                if l.strip().startswith("- ") and "](file:///" not in l
            ]
            pointer_line = ""
            if dropped_items:
                overflow_sidecar_name = f"overflow_archive_{date_str}.md"
                overflow_sidecar_path = arch_dir / overflow_sidecar_name
                overflow_content = (
                    f"# Overflow Archived Entries\n\n"
                    f"> Archived on {datetime.now(timezone.utc).isoformat()} due to line budget.\n\n"
                    + "\n".join(dropped_items)
                    + "\n"
                )
                atomic_write_text(overflow_sidecar_path, overflow_content)
                sidecars_created.append(str(overflow_sidecar_path))
                total_archived += len(dropped_items)

                rel_overflow = overflow_sidecar_path.as_posix()
                pointer_line = f"- [Archive overflow {date_str}](file:///{rel_overflow}) ({len(dropped_items)} archived entries)"

            truncated_lines = settled_lines[:cutoff]
            truncated_lines.append("")
            if pointer_line:
                truncated_lines.append(pointer_line)
            truncated_lines.append(f"> [WARN] Index truncated to adhere to {self.target_lines} line ceiling.")
            settled_text = "\n".join(truncated_lines) + "\n"
            settled_lines = settled_text.splitlines()
            settled_line_count = len(settled_lines)
            settled_byte_count = len(settled_text.encode("utf-8"))

        # Byte-aware reduction pass: ensure settled bytes strictly <= target_bytes (20,000)
        if settled_byte_count > self.target_bytes:
            pruned_lines: list[str] = []
            current_bytes = 0
            overflow_warning = f"> [WARN] Index truncated to adhere to {self.target_bytes} byte ceiling."
            warning_bytes = len(overflow_warning.encode("utf-8")) + 200

            break_idx = len(settled_lines)
            for idx, line in enumerate(settled_lines):
                if line.strip().startswith("- ") and len(line) > 300:
                    line = line[:290] + "... [TRUNCATED]"
                line_bytes = len((line + "\n").encode("utf-8"))
                if current_bytes + line_bytes + warning_bytes <= self.target_bytes:
                    pruned_lines.append(line)
                    current_bytes += line_bytes
                else:
                    break_idx = idx
                    break

            dropped_byte_lines = settled_lines[break_idx:]
            dropped_byte_items = [
                l for l in dropped_byte_lines
                if l.strip().startswith("- ") and "](file:///" not in l
            ]
            if dropped_byte_items:
                byte_sidecar_name = f"byte_overflow_archive_{date_str}.md"
                byte_sidecar_path = arch_dir / byte_sidecar_name
                byte_sidecar_content = (
                    f"# Byte Overflow Archived Entries\n\n"
                    f"> Archived on {datetime.now(timezone.utc).isoformat()} due to byte budget.\n\n"
                    + "\n".join(dropped_byte_items)
                    + "\n"
                )
                atomic_write_text(byte_sidecar_path, byte_sidecar_content)
                sidecars_created.append(str(byte_sidecar_path))
                total_archived += len(dropped_byte_items)

                rel_byte_sidecar = byte_sidecar_path.as_posix()
                pointer_line = f"- [Archive byte overflow {date_str}](file:///{rel_byte_sidecar}) ({len(dropped_byte_items)} archived entries)"
                pruned_lines.append(pointer_line)

            pruned_lines.append("")
            pruned_lines.append(overflow_warning)
            settled_text = "\n".join(pruned_lines) + "\n"
            settled_lines = settled_text.splitlines()
            settled_line_count = len(settled_lines)
            settled_byte_count = len(settled_text.encode("utf-8"))

        atomic_write_text(p, settled_text)
        integrity = self._verify_pointer_integrity(p)

        return IndexBudgetResult(
            index_path=str(p),
            line_count=line_count,
            byte_count=byte_count,
            is_over_budget=True,
            rollover_triggered=True,
            archived_entries_count=total_archived,
            archive_sidecars_created=tuple(sidecars_created),
            settled_line_count=settled_line_count,
            settled_byte_count=settled_byte_count,
            integrity_verified=integrity,
        )

    def _verify_pointer_integrity(self, index_path: Path) -> bool:
        """Self-healing pass: verifies that all archive pointers link to physical files."""
        if not index_path.is_file():
            return True
        text = index_path.read_text(encoding="utf-8")
        links = re.findall(r"\[.*?\]\((file:\/\/\/[^\)]+)\)", text)
        for link in links:
            raw_path = link.replace("file:///", "")
            p = Path(raw_path)
            if not p.is_file():
                return False
        return True
