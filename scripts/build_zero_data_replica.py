"""JHOC Zero-Data Replica Generator.

Extracts all core code, tests, schemas, governance rules, and documentation
from G:\\JHOC into an independent, pristine G:\\JHOC-clean repository.
All private local runtime databases, audit logs, task states, and secrets are strictly excluded.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE_ROOT = Path(__file__).resolve().parent.parent
TARGET_ROOT = SOURCE_ROOT.parent / "JHOC-clean"

EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    "backups",
    "runtime",
    "logs",
    "memory",
    "scratch",
    "temp",
    "tmp",
    ".idea",
    ".vscode",
    "migration",
    "session",
    "acceptance",
    # Task-generated research materials and content-generation skills
    "research",
    "beautiful-article",
    "web-video-presentation",
    "content-generative-harness",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".sqlite",
    ".sqlite-wal",
    ".sqlite-shm",
    ".db",
    ".log",
}

EXCLUDE_FILENAMES = {
    ".operator_secret",
    "write_freeze.lock",
    "$null",
    "codex_review_r4.txt",
    # Task-specific batch research scripts
    "batch_download_papers.py",
    "batch_transcribe_videos.py",
    "deep_read_paper_vs_video.py",
}

GITIGNORE_CONTENT = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual Environments
venv/
.venv/
env/
ENV/

# IDE & Editors
.vscode/
.idea/
*.swp
*.swo
*~

# Testing & Coverage
.pytest_cache/
.coverage
htmlcov/

# JHOC Runtime Transient Data (Zero-Data Invariant)
runtime/*
!runtime/.gitkeep

# JHOC Logs, Audit Trails & BlackBox Traces (Zero-Data Invariant)
logs/*
!logs/.gitkeep

# JHOC Local Task Memory & Private Timeline (Zero-Data Invariant)
memory/*
!memory/.gitkeep

# Temporary Files
scratch/
tmp/
temp/
"""


def copy_tree_filtered(src: Path, dst: Path) -> int:
    copied_count = 0
    dst.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        if item.name in EXCLUDE_DIRS or item.name in EXCLUDE_FILENAMES:
            continue
        if item.suffix in EXCLUDE_EXTENSIONS:
            continue
        if item.name.startswith("$"):
            continue

        target = dst / item.name
        if item.is_dir():
            copied_count += copy_tree_filtered(item, target)
        elif item.is_file():
            shutil.copy2(item, target)
            copied_count += 1

    return copied_count


def handle_remove_readonly(func, path, exc):
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def build_replica(commit_msg: str | None = None, push: bool = False) -> int:
    print(f"=== [BUILDING JHOC ZERO-DATA REPLICA] ===")
    print(f"[INFO] Source Root: {SOURCE_ROOT}")
    print(f"[INFO] Target Root: {TARGET_ROOT}")

    has_git = (TARGET_ROOT / ".git").is_dir()
    if TARGET_ROOT.exists():
        print(f"[INFO] Synchronizing clean target directory: {TARGET_ROOT}")
        for p in TARGET_ROOT.iterdir():
            if p.name == ".git":
                continue
            if p.is_dir():
                shutil.rmtree(p, onexc=handle_remove_readonly)
            else:
                try:
                    p.unlink()
                except Exception:
                    pass

    TARGET_ROOT.mkdir(parents=True, exist_ok=True)

    # 1. Copy filtered directory tree
    print("[INFO] Copying clean source code, tests, schemas, and documentation...")
    total_files = copy_tree_filtered(SOURCE_ROOT, TARGET_ROOT)
    print(f"[PASS] Copied {total_files} clean files.")

    # 2. Re-create empty directories with .gitkeep
    for empty_dir in ["runtime", "logs", "memory"]:
        d = TARGET_ROOT / empty_dir
        d.mkdir(parents=True, exist_ok=True)
        (d / ".gitkeep").write_text("", encoding="utf-8")
        print(f"[PASS] Created zero-data placeholder: {empty_dir}/.gitkeep")

    # 2.5 Write clean generic taxonomy catalog (zero historical personal records)
    clean_catalog = {
        "schema_version": "jhoc-memory-catalog/v1",
        "generated_at": "2026-09-04T00:00:00Z",
        "total_records": 4,
        "tier_summary": {"L1": 1, "L2": 3, "L3": 0},
        "domain_summary": {
            "Governance & Constitution": 1,
            "Network & Proxy Routing": 1,
            "Multi-Model & Provider Interop": 1,
            "Architecture & Infrastructure": 1,
        },
        "records": [
            {
                "record_id": "core:jhoc-constitution",
                "tier": "L1",
                "domain": "Governance & Constitution",
                "title": "JHOC Agent Operating Core Constitution (Rule 0-7)",
                "abstract": "Supreme behavioral invariants and zero-trust engineering boundaries governing all autonomous agents.",
                "relative_path": "AGENTS.md",
                "source_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                "sensitivity": "PUBLIC",
            },
            {
                "record_id": "core:network-proxy-routing",
                "tier": "L2",
                "domain": "Network & Proxy Routing",
                "title": "排查网络代理与 urllib 环境变量配置规范",
                "abstract": "Deterministic socket polling and proxy routing invariants across autonomous runtimes.",
                "relative_path": "docs/architecture/network-proxy-spec.md",
                "source_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                "sensitivity": "PUBLIC",
            },
            {
                "record_id": "core:multi-model-hub",
                "tier": "L2",
                "domain": "Multi-Model & Provider Interop",
                "title": "多模型协同分发与 provider 状态机管理",
                "abstract": "Bearer-tokenized file mutex lease locking and message envelope routing across Antigravity, Claude, and Codex.",
                "relative_path": "src/jhoc/hub/store.py",
                "source_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                "sensitivity": "PUBLIC",
            },
            {
                "record_id": "core:architecture-infrastructure",
                "tier": "L2",
                "domain": "Architecture & Infrastructure",
                "title": "系统重构与微内核架构设计原则",
                "abstract": "Dual-plane physical isolation, anti-self-mutation, and five-tuple blackbox hash chaining.",
                "relative_path": "src/jhoc/supervisor.py",
                "source_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                "sensitivity": "PUBLIC",
            },
        ],
    }
    taxonomy_dir = TARGET_ROOT / "docs" / "taxonomy"
    taxonomy_dir.mkdir(parents=True, exist_ok=True)
    (taxonomy_dir / "jhoc-memory-taxonomy-catalog.json").write_text(json.dumps(clean_catalog, indent=2, ensure_ascii=True), encoding="utf-8")
    print("[PASS] Generated clean minimal taxonomy catalog template (zero legacy records).")

    # 2.6 Clean SHELF.md in clean replica to match 8 core harness skills
    clean_shelf_md = TARGET_ROOT / ".agents" / "skills" / "SHELF.md"
    if clean_shelf_md.exists():
        shelf_txt = clean_shelf_md.read_text(encoding="utf-8")
        cleaned_lines = []
        for line in shelf_txt.splitlines():
            if any(k in line for k in ["beautiful-article", "web-video-presentation", "content-generative-harness"]):
                if line.strip().startswith("| `"):
                    continue
                line = line.replace(", content-generative-harness", "").replace(", web-video-presentation", "").replace(", beautiful-article", "")
            cleaned_lines.append(line)
        cleaned_shelf_content = "\n".join(cleaned_lines)
        cleaned_shelf_content = cleaned_shelf_content.replace("准入技能总数**: 11 项", "准入技能总数**: 8 项")
        clean_shelf_md.write_text(cleaned_shelf_content, encoding="utf-8")
        print("[PASS] Synchronized SHELF.md in clean replica to 8 core harness skills.")

    # 3. Write battle-hardened .gitignore
    gitignore_file = TARGET_ROOT / ".gitignore"
    gitignore_file.write_text(GITIGNORE_CONTENT.strip() + "\n", encoding="utf-8")
    print(f"[PASS] Generated zero-data .gitignore")

    # 4. Verify tests inside the clean replica
    print("\n=== [VERIFYING REPLICA INDEPENDENCE] ===")
    py_bin = sys.executable

    print("[CHECK] Running Schema Validation in clean replica...")
    r1 = subprocess.run([py_bin, "scripts/validate_schemas.py"], cwd=str(TARGET_ROOT), capture_output=True, text=True)
    if r1.returncode != 0:
        print(f"[FAIL] Schema validation failed in replica:\n{r1.stderr or r1.stdout}")
        return 1
    print("[PASS] Schema validation passed.")

    print("[CHECK] Running 353 Unit Tests in clean replica...")
    r2 = subprocess.run([py_bin, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], cwd=str(TARGET_ROOT), capture_output=True, text=True)
    if r2.returncode != 0:
        print(f"[FAIL] Unit tests failed in replica:\n{r2.stderr or r2.stdout}")
        return 1
    print("[PASS] All unit tests passed in zero-data replica.")

    print("[CHECK] Running Acceptance Probes in clean replica...")
    r3 = subprocess.run([py_bin, "scripts/validate_acceptance_artifacts.py"], cwd=str(TARGET_ROOT), capture_output=True, text=True)
    if r3.returncode != 0:
        print(f"[FAIL] Acceptance probes failed in replica:\n{r3.stderr or r3.stdout}")
        return 1
    print("[PASS] Acceptance probes passed.")

    # 4.5 Clean up transient test files generated during self-check
    for p in (TARGET_ROOT / "runtime").glob("*"):
        if p.name != ".gitkeep":
            p.unlink()
    for p in (TARGET_ROOT / "logs").rglob("*"):
        if p.is_file() and p.name != ".gitkeep":
            p.unlink()
    for p in (TARGET_ROOT / "memory").glob("*"):
        if p.name != ".gitkeep":
            p.unlink()
    audit_dir = TARGET_ROOT / "logs" / "audit"
    if audit_dir.exists():
        shutil.rmtree(audit_dir)
    print("[PASS] Transient test runtime files purged.")

    # 5. Git repository commit
    print("\n=== [COMMITTING TO GIT REPOSITORY] ===")
    if not has_git:
        subprocess.run(["git", "init", "-b", "main"], cwd=str(TARGET_ROOT), check=True)
        subprocess.run(["git", "config", "user.name", "JHOC Contributor"], cwd=str(TARGET_ROOT), check=True)
        subprocess.run(["git", "config", "user.email", "jhoc@localhost"], cwd=str(TARGET_ROOT), check=True)
    subprocess.run(["git", "add", "."], cwd=str(TARGET_ROOT), check=True)
    diff_check = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=str(TARGET_ROOT), capture_output=True, text=True)
    if diff_check.stdout.strip():
        final_msg = commit_msg or "feat: synchronize clean replica with updated research knowledgebase and skills"
        subprocess.run(["git", "commit", "-m", final_msg], cwd=str(TARGET_ROOT), check=True)
        print(f"[PASS] Clean commit created: {final_msg}")
    else:
        print("[INFO] Working tree clean, no changes to commit.")

    if push:
        print("\n=== [PUSHING TO GITHUB] ===")
        push_res = subprocess.run(["git", "push", "origin", "main"], cwd=str(TARGET_ROOT), capture_output=True, text=True)
        if push_res.returncode != 0:
            print(f"[FAIL] Git push failed:\n{push_res.stderr or push_res.stdout}")
            return 1
        print("[PASS] Successfully pushed clean replica to GitHub (origin/main).")

    print("\n======================================================================")
    print("      JHOC ZERO-DATA REPLICA READY FOR GITHUB UPLOAD                   ")
    print("======================================================================")
    print(f"Location: {TARGET_ROOT}")
    if not push:
        print("To push to GitHub, run:")
        print(f"  cd \"{TARGET_ROOT}\"")
        print("  git push origin main")
    print("======================================================================")
    return 0


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="JHOC Zero-Data Clean Replica Generator & Publisher")
    parser.add_argument("-m", "--message", type=str, default=None, help="Custom git commit message for the replica")
    parser.add_argument("--push", action="store_true", help="Automatically push to GitHub origin main after clean verification")
    args = parser.parse_args()

    return build_replica(commit_msg=args.message, push=args.push)


if __name__ == "__main__":
    sys.exit(main())

