---
name: codex-plan-review
canonical_id: codex-plan-review
aliases: ["plan-review", "规划复核", "方案评审", "架构对齐", "plan-alignment"]
description: "方案规划评审与多模型反向对齐流程 — 在复杂编码、重构与架构任务开始前进行影响路径审查、边界确认与执行风险评估。"
version: 1.1.0
category: collaboration
trigger: ["codex-plan-review", "plan-review", "规划复核", "方案评审", "架构对齐", "对齐计划"]
when_to_use: ["复杂架构设计或大重构前对齐方案", "多模型协同或自审中审定执行步骤", "评估破坏性改动风险与 DOWN/UP/FORK 影响路径"]
skill_tier: core
---

# 方案规划评审与风险对齐技能 (codex-plan-review)

> **Authority**: Governed under **JHOC Agent 宪法体系** ([`g:\JHOC\AGENTS.md`](file:///g:/JHOC/AGENTS.md)) 与 [`cognitive-tier0-protocol.md`](file:///g:/JHOC/.agents/rules/cognitive-tier0-protocol.md)
> **Physical Location**: `g:\JHOC\.agents\skills\codex-plan-review\`

---

## 1. 触发条件

- **必须触发**：任何涉及核心模块修改、新增插件、Schema 变更、架构调整的任务，在草拟计划后、动手写代码前；
- **可跳过**：纯问答、纯信息检索、用户明确说明“直接做不用对齐”的单行小修复。

---

## 2. 规划清单自审结构 (Plan Review Checklist)

起草的每一个具体变更项，必须显式包含：

1. **改动目标与范围**：具体涉及哪些文件？新增还是修改？
2. **三维影响路径分析 (DOWN / UP / FORK)**：
   - **DOWN**（受影响下游）：会影响哪些已有接口与数据流？
   - **UP**（上游调用方）：调用方需要哪些参数适配？
   - **FORK**（分支与边界）：是否有网络断开、超时重试、空数据等边缘情况？
3. **验证与证伪方案**：
   - 必须给出具体的单测命令或自动化脚本（如 `python -m unittest ...`）；
   - 严禁写“编译通过即可”或“肉眼观察”这类虚假断言。
4. **回滚与自持方案**：
   - 一旦破坏性变更发生，如何一键无损回滚到上一个稳定快照？

---

## 3. 关联规约
- 配合 [`counter-questioning-probe`](file:///g:/JHOC/.agents/skills/counter-questioning-probe/SKILL.md) 共同构筑开工门禁；
- 严禁“先写代码，后补方案，测试通过再补合规”的流氓做法。
