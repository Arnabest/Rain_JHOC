"""Local Asset Inverted Index Builder.

Scans:
1. .agents/skills/*/SKILL.md via SkillShelfLoader
2. docs/lessons/*.md via LessonsStore
3. scripts/jhoc_*.py CLI tools

Outputs:
.agents/plugins/governance-engine/data/local_asset_index.json
(with copy/backup in memory/local_asset_index.json)

Guarantees:
- Atomic file replacement (tempfile + os.replace).
- Computes SHA-256 digest of entire index.
- Pre-indexes character 2-grams for deterministic CJK matching.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jhoc.shelf.loader import SkillShelfLoader
from jhoc.lessons.store import LessonsStore
try:
    from .schema import AssetRecord, AssetType
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from schema import AssetRecord, AssetType


def compute_char_bigrams(text: str) -> list[str]:
    """Extracts alphanumeric and CJK 2-grams for deterministic lexical overlap."""
    clean = re.sub(r"[^\w\u4e00-\u9fff]", "", text.lower())
    if len(clean) < 2:
        return [clean] if clean else []
    return [clean[i : i + 2] for i in range(len(clean) - 1)]


class AssetIndexer:
    """Builds and serializes the local asset inverted index."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.root = workspace_root or ROOT
        self.output_dir = self.root / ".agents" / "plugins" / "governance-engine" / "data"
        self.memory_copy = self.root / "memory" / "local_asset_index.json"

    def build_index(self) -> dict:
        assets: list[dict] = []
        bigram_index: dict[str, list[str]] = {}  # bigram -> [asset_id, ...]

        # 1. Index Skills
        loader = SkillShelfLoader(self.root / ".agents" / "skills", self.root / ".agents" / "plugins")
        try:
            skills = loader.discover_skills(include_plugins=True)
            for sk in skills:
                # Associated executable tools
                tools: list[str] = []
                if "shougong" in sk.name:
                    tools.append("py -3 scripts/jhoc_shougong.py")
                elif "kaigong" in sk.name:
                    tools.append("py -3 scripts/jhoc_kaigong.py")
                elif "codex-plan-review" in sk.name or "plan" in sk.name:
                    tools.append("py -3 scripts/jhoc_co_review.py")
                elif "token-stats" in sk.name:
                    tools.append("py -3 scripts/jhoc_token_stats.py")

                # Map associated negative lessons
                neg_lessons: list[dict[str, str]] = []
                if "plan" in sk.name or "review" in sk.name:
                    neg_lessons.append({
                        "lesson_id": "147",
                        "symptom": "Roleplaying external models rather than invoking real CLI tools",
                        "rule": "Never roleplay Codex/Claude; must invoke real CLI or state offline review",
                    })
                elif "kaigong" in sk.name:
                    neg_lessons.append({
                        "lesson_id": "InquiryGate",
                        "symptom": "Modifying code before counter-questioning probe alignment",
                        "rule": "Hook Gate physically blocks business edits while inquiry is PENDING",
                    })

                rec = AssetRecord(
                    asset_id=sk.name,
                    asset_type=AssetType.SKILL,
                    title=sk.name,
                    path=str(sk.path.relative_to(self.root)).replace("\\", "/"),
                    intent_affinity=(sk.category.upper(),),
                    triggers=sk.triggers + sk.when_to_use,
                    executable_tools=tuple(tools),
                    negative_lessons=tuple(neg_lessons),
                    content_summary=sk.description,
                    source_sha256="",
                )
                assets.append(rec.to_dict())

                # Index bigrams from triggers and name
                trigger_text = " ".join(sk.triggers + sk.when_to_use + (sk.name,))
                for bg in set(compute_char_bigrams(trigger_text)):
                    bigram_index.setdefault(bg, []).append(sk.name)
        except Exception as e:
            print(f"[WARN] Failed to index skills: {e}")

        # 2. Index Lessons
        try:
            lstore = LessonsStore(self.root / "docs" / "lessons")
            lstore.load()
            for entry in lstore._entries:
                src_str = f"docs/lessons/{entry.source_file}" if not str(entry.source_file).startswith("docs") else str(entry.source_file)
                rec = AssetRecord(
                    asset_id=f"lesson-{entry.lesson_id}",
                    asset_type=AssetType.LESSON,
                    title=entry.title,
                    path=src_str.replace("\\", "/"),
                    intent_affinity=(entry.category.upper(),),
                    triggers=(entry.title, entry.symptom[:40]),
                    negative_lessons=({
                        "lesson_id": entry.lesson_id,
                        "symptom": entry.symptom,
                        "rule": entry.rule,
                    },),
                    content_summary=entry.rule,
                    source_sha256="",
                )
                assets.append(rec.to_dict())

                lesson_text = f"{entry.title} {entry.symptom} {entry.rule}"
                for bg in set(compute_char_bigrams(lesson_text)):
                    bigram_index.setdefault(bg, []).append(rec.asset_id)
        except Exception as e:
            print(f"[WARN] Failed to index lessons: {e}")

        # 3. Add explicit governance tools
        gov_tools = [
            ("jhoc_co_review", "py -3 scripts/jhoc_co_review.py", ["多模型协审", "拉起协审", "商讨方案", "codex", "claude", "co-review", "对齐计划"]),
            ("jhoc_kaigong", "py -3 scripts/jhoc_kaigong.py", ["开工", "启动任务", "门禁", "kaigong"]),
            ("jhoc_shougong", "py -3 scripts/jhoc_shougong.py", ["收工", "收尾", "闭环", "交付", "shougong", "36协审"]),
            ("jhoc_trace", "py -3 scripts/jhoc_trace.py", ["溯源", "trace", "日志查询", "信封追踪"]),
            ("jhoc_token_stats", "py -3 scripts/jhoc_token_stats.py", ["额度", "配额", "token-stats", "5h", "weekly"]),
        ]
        for name, cmd, triggers in gov_tools:
            rec = AssetRecord(
                asset_id=f"tool-{name}",
                asset_type=AssetType.SCRIPT,
                title=name,
                path=cmd,
                intent_affinity=("GOVERNANCE_TOOL",),
                triggers=tuple(triggers),
                executable_tools=(cmd,),
                content_summary=f"Official JHOC Governance Tool: {name}",
            )
            assets.append(rec.to_dict())
            for bg in set(compute_char_bigrams(" ".join(triggers))):
                bigram_index.setdefault(bg, []).append(rec.asset_id)

        index_payload = {
            "schema_version": "jhoc-asset-index/v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "asset_count": len(assets),
            "assets": assets,
            "bigram_index": bigram_index,
        }

        # Calculate digest
        raw = json.dumps(index_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        sha256_hash = hashlib.sha256(raw).hexdigest()
        index_payload["sha256"] = sha256_hash
        return index_payload

    def save_index(self, index_payload: dict) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target_file = self.output_dir / "local_asset_index.json"

        # Atomic write via tempfile in same folder
        with tempfile.NamedTemporaryFile("w", dir=str(self.output_dir), delete=False, encoding="utf-8") as tf:
            json.dump(index_payload, tf, indent=2, ensure_ascii=False)
            temp_name = tf.name

        os.replace(temp_name, str(target_file))

        # Also write memory backup
        try:
            self.memory_copy.parent.mkdir(parents=True, exist_ok=True)
            self.memory_copy.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        return target_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Build JHOC local asset inverted index.")
    parser.add_argument("--workspace", type=str, default=str(ROOT))
    args = parser.parse_args()

    indexer = AssetIndexer(Path(args.workspace))
    payload = indexer.build_index()
    out = indexer.save_index(payload)
    print(f"[PASS] Asset Index successfully published: {out} (Assets: {payload['asset_count']}, SHA-256: {payload['sha256'][:16]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
