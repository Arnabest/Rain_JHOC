"""JHOC Provisioner - Provisions JHOC governance into an external project workspace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

JHOC_ROOT = Path(__file__).resolve().parents[1]


def provision_workspace(target_path: Path) -> int:
    target_root = target_path.resolve()
    print(f"=== [JHOC CROSS-PROJECT PROVISIONER] ===")
    print(f"[INFO] Target Workspace: {target_root}")

    if not target_root.exists() or not target_root.is_dir():
        print(f"[FAIL] Target directory does not exist: {target_root}")
        return 1

    project_name = target_root.name
    slug = re.sub(r"[^\w\-]", "_", project_name).lower() or "external_project"

    # 1. Provision .agents/ directory and hooks.json
    agents_dir = target_root / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    hooks_file = agents_dir / "hooks.json"
    hooks_content = {
        "jhoc-gate": {
            "enabled": True,
            "PreInvocation": [
                {
                    "type": "command",
                    "command": f'python "{JHOC_ROOT / "scripts" / "jhoc_pre_inject.py"}"',
                    "timeout": 5,
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "write_to_file",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'python "{JHOC_ROOT / "scripts" / "jhoc_hook_gate.py"}"',
                            "timeout": 5,
                        }
                    ],
                },
                {
                    "matcher": "replace_file_content",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'python "{JHOC_ROOT / "scripts" / "jhoc_hook_gate.py"}"',
                            "timeout": 5,
                        }
                    ],
                },
                {
                    "matcher": "multi_replace_file_content",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'python "{JHOC_ROOT / "scripts" / "jhoc_hook_gate.py"}"',
                            "timeout": 5,
                        }
                    ],
                },
                {
                    "matcher": "run_command",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'python "{JHOC_ROOT / "scripts" / "jhoc_hook_gate.py"}"',
                            "timeout": 5,
                        }
                    ],
                },
            ],
            "Stop": [
                {
                    "type": "command",
                    "command": f'python "{JHOC_ROOT / "scripts" / "jhoc_stop_guard.py"}"',
                    "timeout": 5,
                }
            ],
        }
    }
    hooks_file.write_text(json.dumps(hooks_content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[PASS] Created IDE Lifecycle Hooks: {hooks_file}")

    # 2. Provision AGENTS.md (for IDE, agy, codex, deepseek)
    agents_md = target_root / "AGENTS.md"
    agents_content = f"""# AGENTS.md — {project_name} Governance

> **Parent Authority**: Governed under [JHOC Constitution](file:///{JHOC_ROOT.as_posix()}/AGENTS.md)
> **Universal Principles**: Rules 0 - 7 (Rule 0: Meta-Cognitive Distillation; Rule 7: Zero-Emoji Discipline)
> **Global Shelf Skills**: Inherited from `{JHOC_ROOT.as_posix()}/.agents/skills/`

---

## 1. Project Scoping
- **Project Name**: `{project_name}`
- **Workspace Root**: `{target_root}`
- **Governed Core**: JHOC (Jian Harness Operating Core)

## 2. Mandatory Lifecycle Commands
- **Task Start (Kaigong)**:
  ```powershell
  python "{JHOC_ROOT / "scripts" / "jhoc_kaigong.py"}" --title "task_description"
  ```
- **Task Close (Shougong)**:
  ```powershell
  python "{JHOC_ROOT / "scripts" / "jhoc_shougong.py"}"
  ```

## 3. File Persistence Routing (五级落盘细分规范)
- **Zone 1 (源码)**: 正式代码放入 `src/` 或业务包目录；
- **Zone 2 (单测)**: 单元测试放入 `tests/`；
- **Zone 3 (草稿)**: 临时实验探针脚本放入 `scratch/`，**严禁在项目根目录下抛掷零碎测试脚本**；
- **Zone 4 (项目记忆)**: 任务状态写入 `<workspace>/memory/`；
- **Zone 5 (全局经验)**: 跨项目通用错题归档入 `G:/JHOC/docs/lessons/`。

## 4. Strict Red Lines
- **Zero-Emoji Discipline**: Never use Emoji icons or non-BMP characters in code, documents, or responses.
- **Verification First**: Verify through executable commands before claiming task completion.
"""
    agents_md.write_text(agents_content.strip() + "\n", encoding="utf-8")
    print(f"[PASS] Created Multi-Model Constitution: {agents_md}")

    # 3. Provision CLAUDE.md (for Claude Code)
    claude_md = target_root / "CLAUDE.md"
    claude_content = f"""# CLAUDE.md — {project_name}

> Governed under JHOC Constitution (`{JHOC_ROOT.as_posix()}/AGENTS.md`).
> Zero-Emoji Discipline (Rule 7) enforced: Flat ASCII output only (`[PASS]`, `[WARN]`, `[FAIL]`, `[INFO]`, `->`).
> File Persistence Routing enforced: Ad-hoc scripts must go to `scratch/`, never project root.

## Lifecycle Commands
- **Kaigong**: `python "{JHOC_ROOT / "scripts" / "jhoc_kaigong.py"}" --title "task_description"`
- **Shougong**: `python "{JHOC_ROOT / "scripts" / "jhoc_shougong.py"}"`
"""
    claude_md.write_text(claude_content.strip() + "\n", encoding="utf-8")
    print(f"[PASS] Created Claude Code Bootstrap: {claude_md}")

    # 4. Register Project in Graph Topology (p19-graph.sqlite)
    graph_db = JHOC_ROOT / "logs" / "p19-graph.sqlite"
    if graph_db.is_file():
        try:
            import sqlite3
            with sqlite3.connect(graph_db) as conn:
                node_id = f"project:{slug}"
                conn.execute(
                    "INSERT OR REPLACE INTO jhoc_graph_node (node_id, node_type) VALUES (?, ?)",
                    (node_id, "Project"),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO jhoc_graph_relation (relation_id, source_node, target_node, relation_type, confidence, source_ref, verification_status, quality) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"rel:proj:{slug}", node_id, "project:jhoc", "depends_on", 1.0, "jhoc_provision", "VERIFIED", "VERIFIED"),
                )
            print(f"[PASS] Registered in Graph Store: node_id={node_id}, relation=depends_on -> project:jhoc")
        except Exception as e:
            print(f"[WARN] Graph registration skipped: {e}")

    print("[SUCCESS] Project successfully provisioned under JHOC cross-project governance!")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision an external workspace under JHOC governance")
    parser.add_argument("--target", required=True, help="Target workspace path")
    args = parser.parse_args()

    sys.exit(provision_workspace(Path(args.target)))


if __name__ == "__main__":
    main()
