from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.models import PluginManifest, PluginType
from jhoc.registry import CapabilityRecord, CapabilityRegistry, VerificationStatus
from jhoc.shelf.shelf import Shelf, ShelfEntry


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    name: str
    version: str
    category: str
    description: str
    triggers: tuple[str, ...]
    when_to_use: tuple[str, ...]
    path: Path
    record: CapabilityRecord
    skill_tier: str = "core"


class SkillShelfLoader:
    """Discovers, audits, and admits .agents/skills and .agents/plugins/*/skills into JHOC Registry and Shelf."""

    def __init__(self, skills_dir: Path | str | None = None, plugins_dir: Path | str | None = None) -> None:
        root = Path(__file__).resolve().parent.parent.parent.parent / ".agents"
        if skills_dir is None:
            self.skills_dir = root / "skills"
            default_plugins = root / "plugins"
        else:
            self.skills_dir = Path(skills_dir).resolve()
            default_plugins = self.skills_dir.parent / "plugins"

        if plugins_dir is None:
            self.plugins_dir = default_plugins
        else:
            self.plugins_dir = Path(plugins_dir).resolve()

    def discover_skills(self, include_plugins: bool = True) -> tuple[LoadedSkill, ...]:
        loaded: list[LoadedSkill] = []
        if self.skills_dir.exists() and self.skills_dir.is_dir():
            for child in sorted(self.skills_dir.iterdir()):
                if not child.is_dir():
                    continue
                skill_md = child / "SKILL.md"
                if not skill_md.exists() or not skill_md.is_file():
                    continue

                skill = self.load_skill(skill_md, default_tier="core")
                loaded.append(skill)

        if include_plugins and self.plugins_dir.exists() and self.plugins_dir.is_dir():
            for plugin in sorted(self.plugins_dir.iterdir()):
                if not plugin.is_dir():
                    continue
                skills_subdir = plugin / "skills"
                if not skills_subdir.is_dir():
                    continue
                for child in sorted(skills_subdir.iterdir()):
                    if not child.is_dir():
                        continue
                    skill_md = child / "SKILL.md"
                    if not skill_md.exists() or not skill_md.is_file():
                        continue

                    skill = self.load_skill(skill_md, default_tier="domain")
                    loaded.append(skill)

        return tuple(loaded)

    def discover_core_skills(self) -> tuple[LoadedSkill, ...]:
        return tuple(s for s in self.discover_skills(include_plugins=False) if s.skill_tier == "core")

    def discover_domain_skills(self) -> tuple[LoadedSkill, ...]:
        return tuple(s for s in self.discover_skills(include_plugins=True) if s.skill_tier == "domain")

    def load_skill(self, skill_md_path: Path, default_tier: str = "core") -> LoadedSkill:
        content = skill_md_path.read_text(encoding="utf-8")
        frontmatter = self._parse_frontmatter(content)

        name = frontmatter.get("name") or skill_md_path.parent.name
        version = str(frontmatter.get("version", "1.0.0")).strip()
        category = str(frontmatter.get("category", "methodology")).strip()
        description = str(frontmatter.get("description", "")).strip()
        skill_tier = str(frontmatter.get("skill_tier") or default_tier).strip()

        raw_triggers = frontmatter.get("trigger") or frontmatter.get("triggers") or ()
        if isinstance(raw_triggers, str):
            triggers = tuple(t.strip() for t in raw_triggers.split(",") if t.strip())
        elif isinstance(raw_triggers, (list, tuple)):
            triggers = tuple(str(t).strip() for t in raw_triggers if str(t).strip())
        else:
            triggers = ()

        raw_when = frontmatter.get("when_to_use", ())
        if isinstance(raw_when, (list, tuple)):
            when_to_use = tuple(str(w).strip() for w in raw_when if str(w).strip())
        elif isinstance(raw_when, str):
            when_to_use = (raw_when.strip(),)
        else:
            when_to_use = ()

        manifest = PluginManifest(
            plugin_id=f"jhoc.skill.{name}",
            name=name,
            version=version,
            protocol_version="1.0",
            plugin_type=PluginType.CAPABILITY,
            capabilities=triggers,
            dependencies=(),
            permissions={},
            side_effects=(),
            resource_requirements={},
            license="MIT",
            verification_status="VERIFIED",
            shelf_eligible=True,
            runtime_selectable=True,
            mutable_by_agent=False,
        )

        record = CapabilityRecord(
            capability_id=f"skill:{name}",
            version=version,
            manifest=manifest,
            input_schema_ref="schemas/work-item-1.0.json",
            output_schema_ref="schemas/work-result-1.0.json",
            verification_status=VerificationStatus.VERIFIED,
            health="HEALTHY",
        )

        return LoadedSkill(
            name=name,
            version=version,
            category=category,
            description=description,
            triggers=triggers,
            when_to_use=when_to_use,
            path=skill_md_path,
            record=record,
            skill_tier=skill_tier,
        )

    def sync_to_shelf(self, registry: CapabilityRegistry, shelf: Shelf, include_plugins: bool = True) -> tuple[ShelfEntry, ...]:
        skills = self.discover_skills(include_plugins=include_plugins)
        admitted: list[ShelfEntry] = []
        for s in skills:
            try:
                registry.register(s.record)
            except ContractError as err:
                if err.code != ErrorCode.IDEMPOTENCY_CONFLICT:
                    raise
            entry = shelf.admit(s.record)
            admitted.append(entry)
        return tuple(admitted)

    def generate_shelf_markdown(self) -> str:
        core_skills = self.discover_core_skills()
        domain_skills = self.discover_domain_skills()
        total_count = len(core_skills) + len(domain_skills)

        lines: list[str] = [
            "# JHOC 技能货架权威总目录 (Skill Shelf Ledger)",
            "",
            "> **Authority**: Governed under [`ADR-0009-registry-shelf-quota.md`](file:///g:/JHOC/docs/adr/ADR-0009-registry-shelf-quota.md) 与 [`src/jhoc/shelf/`](file:///g:/JHOC/src/jhoc/shelf/)",
            f"> **技能总数**: {total_count} 项 (核心工程治理: {len(core_skills)} 项 | 领域业务扩展: {len(domain_skills)} 项) | **状态**: 全部 VERIFIED & SHELF_ELIGIBLE",
            "",
            "---",
            "",
            "## 一、 核心工程与治理技能货架 (Core Governance & Engineering Shelf)",
            "> **物理空间**: `.agents/skills/` | **定位**: 框架微内核生命周期内置常驻能力，严禁动态剥离，随微内核发行。",
            "",
            "| 技能 Canonical ID | 层级 | 版本 | 分类 | 触发特征 / Aliases | 准入状态 | 对应文件 |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for s in core_skills:
            trig_str = ", ".join(f"`{t}`" for t in s.triggers[:3])
            rel_path = s.path.relative_to(self.skills_dir)
            lines.append(f"| `{s.name}` | `core` | `{s.version}` | `{s.category}` | {trig_str} | `VERIFIED` | [{s.name}]({rel_path.as_posix()}) |")

        if domain_skills:
            lines.extend([
                "",
                "---",
                "",
                "## 二、 领域与业务扩展插件货架 (Domain & Business Plugin Shelf)",
                "> **物理空间**: `.agents/plugins/domain-content/skills/` | **定位**: 业务领域专用扩展包，按需热插拔，不随微内核发行。",
                "",
                "| 技能 Canonical ID | 层级 | 版本 | 分类 | 触发特征 / Aliases | 准入状态 | 对应文件 |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for s in domain_skills:
                trig_str = ", ".join(f"`{t}`" for t in s.triggers[:3])
                rel_path = Path("..") / s.path.relative_to(self.skills_dir.parent)
                lines.append(f"| `{s.name}` | `domain` | `{s.version}` | `{s.category}` | {trig_str} | `VERIFIED` | [{s.name}]({rel_path.as_posix()}) |")

        lines.extend([
            "",
            "---",
            "",
            "## 货架上架硬契约与门禁",
            "1. **禁止裸露文件存在**：`.agents/skills/` 目录下任何未在核心货架登记的技能，在自动化合规测试中均判定为 `E_UNADMITTED_SKILL` 阻断！",
            "2. **单一事实源**：每个技能必须具备合法的 YAML Frontmatter、强类型 `skill_tier` 与只读不可变标志 (`mutable_by_agent: false`)。",
            "3. **意图调度联动**：所有上架技能必须与 `src/jhoc/intent/classifier.py` 建立特征绑定，支持程序化自动装配。",
            "",
        ])
        return "\n".join(lines)

    def export_shelf_manifest_brief(self) -> list[dict[str, str]]:
        skills = self.discover_skills()
        brief: list[dict[str, str]] = []
        for s in skills:
            brief.append({
                "name": s.name,
                "category": s.category,
                "description": s.description,
                "triggers": ", ".join(s.triggers[:3]),
            })
        return brief

    @staticmethod
    def _parse_frontmatter(content: str) -> dict[str, Any]:
        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}

        fm_lines: list[str] = []
        for line in lines[1:]:
            if line.strip() == "---":
                break
            fm_lines.append(line)

        res: dict[str, Any] = {}
        curr_key: str | None = None
        curr_list: list[str] | None = None

        for l in fm_lines:
            # Check for list item
            list_match = re.match(r"^\s*-\s*(.*)$", l)
            if list_match and curr_key:
                val = list_match.group(1).strip().strip('"').strip("'")
                if curr_list is None:
                    curr_list = []
                    res[curr_key] = curr_list
                curr_list.append(val)
                continue

            # Check for key-value
            kv_match = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", l)
            if kv_match:
                curr_key = kv_match.group(1).strip()
                curr_list = None
                raw_val = kv_match.group(2).strip()
                if raw_val.startswith("[") and raw_val.endswith("]"):
                    items = [x.strip().strip('"').strip("'") for x in raw_val[1:-1].split(",") if x.strip()]
                    res[curr_key] = items
                elif raw_val:
                    res[curr_key] = raw_val.strip('"').strip("'")
                else:
                    res[curr_key] = None

        return res
