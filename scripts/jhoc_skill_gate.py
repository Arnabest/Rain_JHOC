"""JHOC Skill Promotion Gate - Identifies, Audits, and Promotes Project Skills to Global Shelf."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import sys

JHOC_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(JHOC_ROOT / "src"))

from jhoc.plugins.gatekeeper import PluginGatekeeper
from jhoc.registry import CapabilityRegistry
from jhoc.shelf import SkillShelfLoader, SQLiteShelf

_EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]")


@dataclass(frozen=True, slots=True)
class CandidateSkill:
    name: str
    path: Path
    is_on_shelf: bool
    version: str


def scan_candidate_skills(workspace_root: Path) -> list[CandidateSkill]:
    candidates: list[CandidateSkill] = []
    target_skills_dir = workspace_root / ".agents" / "skills"
    if not target_skills_dir.is_dir():
        return candidates

    canonical_skills_dir = JHOC_ROOT / ".agents" / "skills"
    canonical_names = {p.name for p in canonical_skills_dir.iterdir() if p.is_dir()}

    for child in sorted(target_skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue

        name = child.name
        is_on_shelf = name in canonical_names

        # Parse version
        version = "1.0.0"
        try:
            txt = skill_md.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"version:\s*([^\r\n]+)", txt)
            if m:
                version = m.group(1).strip("\"' ")
        except Exception:
            pass

        candidates.append(CandidateSkill(name=name, path=child, is_on_shelf=is_on_shelf, version=version))

    return candidates


def audit_skill(skill_dir: Path) -> tuple[bool, list[str]]:
    violations: list[str] = []
    skill_md = skill_dir / "SKILL.md"

    # Gate 1: SKILL.md Existence and Manifest parsing
    if not skill_md.is_file():
        violations.append(f"[FAIL] Missing required {skill_dir / 'SKILL.md'}")
        return False, violations

    try:
        loader = SkillShelfLoader(skill_dir.parent)
        loaded = loader.load_skill(skill_md)
        if not loaded.name or not loaded.triggers or not loaded.description:
            violations.append("[FAIL] Incomplete frontmatter: name, trigger, and description are required")
    except Exception as e:
        violations.append(f"[FAIL] YAML Frontmatter parse error: {e}")

    # Gate 2: Zero-Emoji Discipline (Rule 7)
    for f in skill_dir.rglob("*"):
        if f.is_file() and f.suffix.lower() in (".md", ".py", ".json", ".yaml", ".yml", ".txt"):
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
                matches = _EMOJI_RE.findall(txt)
                if matches:
                    violations.append(f"[FAIL] Rule 7 Violation: {f.name} contains {len(matches)} emojis")
            except Exception as e:
                violations.append(f"[FAIL] Error reading {f.name}: {e}")

    # Gate 3: AST Static Safety Gate (using PluginGatekeeper)
    for py_file in skill_dir.rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            ast_violations = PluginGatekeeper.inspect_source(source, filename=py_file.name)
            for v in ast_violations:
                violations.append(f"[FAIL] AST Safety Violation in {py_file.name}: {v}")
        except Exception as e:
            violations.append(f"[FAIL] SyntaxError/AST error in {py_file.name}: {e}")

    # Gate 4: Falsifiable Verification Checklist
    # Check if skill defines executable commands or has an accompanying test
    has_test = False
    tests_dir = skill_dir.parent.parent.parent / "tests"
    if tests_dir.is_dir():
        has_test = any(f.name.startswith(f"test_{skill_dir.name}") for f in tests_dir.glob("*.py"))
    
    txt = skill_md.read_text(encoding="utf-8", errors="ignore")
    has_code_block = "```" in txt
    if not (has_test or has_code_block):
        violations.append("[FAIL] Rule 1 Violation: Skill must contain verifiable execution commands or test suites")

    is_ok = len(violations) == 0
    return is_ok, violations


def promote_skill_to_shelf(skill_dir: Path) -> int:
    print(f"=== [JHOC SKILL PROMOTION GATE] ===")
    print(f"[INFO] Evaluating Candidate: {skill_dir.name} ({skill_dir})")

    ok, violations = audit_skill(skill_dir)
    for v in violations:
        print(v)

    if not ok:
        print("[DENIED] Skill failed promotion gates. Admission to global shelf aborted.")
        return 1

    print("[PASS] Gate 1: Manifest & YAML Frontmatter verified")
    print("[PASS] Gate 2: Zero-Emoji Discipline verified")
    print("[PASS] Gate 3: AST Static Safety Gate verified")
    print("[PASS] Gate 4: Verification Checklist verified")

    canonical_skills_dir = JHOC_ROOT / ".agents" / "skills"
    dest_dir = canonical_skills_dir / skill_dir.name

    if dest_dir.resolve() != skill_dir.resolve():
        dest_dir.mkdir(parents=True, exist_ok=True)
        for item in skill_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, dest_dir / item.name)
            elif item.is_dir():
                shutil.copytree(item, dest_dir / item.name, dirs_exist_ok=True)
        print(f"[PASS] Synchronized to JHOC Canonical Directory: {dest_dir}")

    # Sync to Shelf Database and SHELF.md
    shelf_db_path = JHOC_ROOT / "logs" / "p19-shelf.sqlite"
    registry = CapabilityRegistry()
    shelf = SQLiteShelf(str(shelf_db_path))

    loader = SkillShelfLoader(canonical_skills_dir)
    admitted = loader.sync_to_shelf(registry, shelf)

    shelf_md = canonical_skills_dir / "SHELF.md"
    shelf_md.write_text(loader.generate_shelf_markdown(), encoding="utf-8")
    print(f"[PASS] Synchronized to Shelf Database ({shelf_db_path.name}) & SHELF.md")
    print(f"[SUCCESS] Skill '{skill_dir.name}' formally admitted onto JHOC Universal Shelf (Total: {len(admitted)} skills)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="JHOC Skill Promotion & Shelf Admission Gate")
    parser.add_argument("--scan", help="Scan candidate skills in target workspace root")
    parser.add_argument("--audit", help="Audit candidate skill directory without promoting")
    parser.add_argument("--promote", help="Audit and promote candidate skill directory to global shelf")
    args = parser.parse_args()

    if args.scan:
        ws = Path(args.scan).resolve()
        candidates = scan_candidate_skills(ws)
        print(f"=== [JHOC SKILL SCANNER: {ws.name}] ===")
        print(f"Found {len(candidates)} local skills:")
        for c in candidates:
            status = "ON_SHELF" if c.is_on_shelf else "CANDIDATE"
            print(f"  [{status}] {c.name} (v{c.version}) -> {c.path}")
        sys.exit(0)

    if args.audit:
        skill_path = Path(args.audit).resolve()
        ok, violations = audit_skill(skill_path)
        print(f"=== [JHOC SKILL AUDIT: {skill_path.name}] ===")
        for v in violations:
            print(v)
        if ok:
            print("[PASS] Skill 100% compliant with JHOC shelf standards.")
            sys.exit(0)
        else:
            print(f"[FAIL] {len(violations)} violations found.")
            sys.exit(1)

    if args.promote:
        skill_path = Path(args.promote).resolve()
        sys.exit(promote_skill_to_shelf(skill_path))

    parser.print_help()


if __name__ == "__main__":
    main()
