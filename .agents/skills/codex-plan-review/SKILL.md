---
name: codex-plan-review
canonical_id: codex-plan-review
aliases: ["plan-review", "规划复核", "方案评审", "架构对齐", "plan-alignment", "co-review", "lifecycle-co-review", "multi-model-co-review", "双阶段协审", "开工协审", "收工协审"]
description: "双阶段多模型协审与方案规划对齐技能 — 在任务开工前执行前置红队审查锁定 C1-Cn 约束条件，在任务收尾前执行闭环终审复核实证与字符纯度。"
version: 2.0.0
category: collaboration
trigger: ["codex-plan-review", "plan-review", "规划复核", "方案评审", "架构对齐", "对齐计划", "co-review", "协审", "开工协审", "收工协审"]
when_to_use: ["复杂架构设计或重大功能研发前执行开工前置协审", "多模型协同中由外部独立模型（如 Claude Code CLI）对执行步骤与影响路径进行反向挑刺", "任务收尾前复核 C1-Cn 约束达成度、全量测试满绿度与 Rule 7 字符纯度"]
skill_tier: core
---

# 双阶段多模型协审与方案规划对齐技能 (Multi-Model Lifecycle Co-Review Protocol)

> **Authority**: Governed under **JHOC Agent 宪法体系** ([AGENTS.md`](AGENTS.md))、[`cognitive-tier0-protocol.md`](.agents/rules/cognitive-tier0-protocol.md) 与 [`anti-metaphysical-protocol.md`](.agents/rules/anti-metaphysical-protocol.md)
> **Physical Location**: .agents\skills\codex-plan-review\`

---

## 1. 核心宪法依据与第一性原理

1. **Rule 0 反顺从契约 (Anti-Sycophancy)**：
   - 严禁单一模型自编自演或盲跑自夸。复杂架构方案与代码变更，必须引入异构外部模型（如 Claude Code CLI、OpenAI Codex CLI）执行冷酷、客观的对抗式反向挑刺。
2. **Rule 1 物理真实与单机实证 (Physical Reality)**：
   - 协审不看空洞承诺，只看单机可复现的物理实证（AST 语法解析、真实子进程退出码、物理文件 SHA-256、实时 TOCTOU 校验）。
3. **Rule 2 零信任 Fail-Closed 外部拦截 (Zero-Trust Gate)**：
   - 安全防线物理驻留在外部 Harness。未取得前置协审批准（`APPROVED` 或 `APPROVED_WITH_CONDITIONS`）并生成带真实 SHA-256 的协审报告前，外部 Hook Gate 物理阻断一切生产业务代码修改。
4. **Rule 7 字符纯度铁律 (Zero-Emoji Discipline)**：
   - 协审全流程（包括报告、脚本、日志与代码产物）严格遵循 100% 纯 ASCII 与零 Emoji，杜绝一切终端编码异常。

---

## 2. 双阶段协审生命周期拓扑 (Two-Phase Co-Review DAG)

```text
[阶段 0: INCEPTION 需求澄清]
    |
    v
[阶段 1: ELABORATION 方案起草] -> 产出 implementation_plan.md
    |
    v
======================= [开工前置协审 (Opening Co-Review)] =======================
  - 调度外部模型 (如 Claude Code CLI) 进行对抗式方案红队审查
  - 重点审查: DOWN/UP/FORK 三维影响路径推演、反向挑刺、证伪方案、异常兜底
  - 产出物: logs/co-review/<timestamp>-phaseX-opening-co-review.json
  - 裁决必须为 APPROVED 或 APPROVED_WITH_CONDITIONS，锁定约束集合 (C1 - Cn)
================================================================================
    |
    v (仅在取得开工协审报告后放行)
[阶段 2: ARM & EXECUTION 编码实施]
    | -> 严格遵循 C1 - Cn 约束编写代码
    | -> 使用 EvidencePackageEngine 编译物理探针证据
    | -> 编写对应单元测试套件
    |
    v
[阶段 3: VERIFICATION 单测验收] -> 本地单测 100% 满绿
    |
    v
======================= [收工闭环协审 (Closing Co-Review)] =======================
  - 调度外部模型 (如 Claude Code CLI) 针对真实产物执行终审验收
  - 核心核验清单:
    1. C1 - Cn 约束逐条对照核验 (必须 100% 落实，无遗漏无降级)
    2. 物理代码 Diff 与测试用例充分性审计
    3. 运行对应全量测试套件 (Assert 100% Green)
    4. Rule 7 纯 ASCII / 零 Emoji 扫描
    5. TOCTOU 实时防篡改复核
  - 产出物: logs/co-review/<timestamp>-phaseX-closing-co-review.json
  - 裁决必须为 APPROVED 或 APPROVED_WITH_CONDITIONS
================================================================================
    |
    v (仅在取得收工协审通过后放行)
[阶段 4: CLOSURE 收工归档] -> 执行 python scripts/jhoc_shougong.py 任务闭环
```

---

## 3. 开工前置协审 Checklist (Opening Co-Review Gate)

起草的每一个技术方案，外部协审员必须核验：
1. **改动目标与边界范围**：清晰列出新增、修改、删除的具体文件清单；
2. **三维影响路径推演 (DOWN / UP / FORK)**：
   - **DOWN**（受影响下游）：现有接口、数据表、模型依赖如何兼容？
   - **UP**（调用方）：API 签名、参数类型是否有破坏性变更？
   - **FORK**（分支与异常）：超时、网络断开、空数据、竞态条件如何降级兜底？
3. **可证伪验证方案**：
   - 提供具体单测命令与断言基准；严禁使用假 Mock 充当端到端基准；
4. **约束条件冻结 (Conditions C1 - Cn)**：
   - 协审报告中必须提炼出明确的数字编号约束条目（如 C1 至 C15），作为后续编码实施与终审验收的唯一事实源。

---

## 4. 收工闭环协审 Checklist (Closing Co-Review Gate)

收工闭环阶段，外部协审员必须逐条核实：
1. **C1 - Cn 约束符合度**：逐项检查代码实现与开工约束的对齐情况；
2. **测试满绿断言**：运行新测试套件与全量回归测试，必须全绿通过；
3. **物理 Diff 清洁度**：杜绝未追踪临时文件、无用 Dump 脚本与根目录杂物；
4. **Rule 7 字符纯度**：扫描所有修改及新增文件，确保无高位 Unicode / Emoji 污染；
5. **TOCTOU 验证**：确认最终准备提交的物理文件哈希与测试时的哈希完全一致。

---

## 5. 标准执行调度模式 (Harness Tooling Contract)

为保证可重复性与自动化集成，双阶段协审采用标准脚本驱动模式：

```bash
# 1. 触发开工前置协审 (开工前)
python scripts/jhoc_phaseX_opening_co_review.py

# 2. 编码与本地测试完成后，触发收工闭环协审 (收工前)
python scripts/jhoc_phaseX_closing_co_review.py

# 3. 终审通过后，执行收工闭环流
python scripts/jhoc_shougong.py
```

协审报告自动沉淀至 `logs/co-review/`，并同步向 Multi-Model SQLite Hub (`logs/p19-hub.sqlite`) 登记协审事件，形成不可篡改的链式审计凭证。
