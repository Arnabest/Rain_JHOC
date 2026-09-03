---
name: counter-questioning-probe
canonical_id: counter-questioning-probe
aliases: ["task-inquiry", "direction-probe", "开工反问", "多角度提问", "方向校准", "需求澄清", "探针提问"]
description: "多角度开工反问与方向基准探针套件 — 用户发起任务时根据输入从范围边界/架构取舍/异常降级/长期治理四大维度主动反问，丰富判断基准。"
version: 1.1.0
category: methodology
trigger: ["counter-questioning-probe", "task-inquiry", "direction-probe", "开工反问", "多角度提问", "方向校准", "需求澄清", "探针提问"]
when_to_use: ["用户发起新任务或提出新需求，进入规划与执行前", "需求存在多条可行技术路线、架构取舍或未决歧义需要与用户对齐", "复杂任务开工阶段主动生成多角度反问清单与交互式选项", "需要明确最小交付范围(MVP)、异常降级预期与系统联动影响"]
last_updated: "2026-09-03T18:24:00Z"
---

# 多角度开工反问与方向基准探针套件 (Counter-Questioning Probe)

> **Authority**: Governed under **JHOC Agent 宪法体系** ([`g:\JHOC\AGENTS.md`](file:///g:/JHOC/AGENTS.md)) 与 [`cognitive-tier0-protocol.md`](file:///g:/JHOC/.agents/rules/cognitive-tier0-protocol.md)
> **Physical Location**: `g:\JHOC\.agents\skills\counter-questioning-probe\`

---

## 1. 核心反问四大正交维度 (Four Orthogonal Inquiry Dimensions)

每当用户发起一轮新任务、重大重构或架构设计，进入生成计划与执行前，**必须显式从以下四大正交维度进行方向解构与交互反问**：

```
                             开工多角度反问维度矩阵
                                       │
    ┌──────────────────────────────────┼──────────────────────────────────┐
    ▼                                  ▼                                  ▼
【1. 范围与边界 (Scope & MVP)】       【2. 架构取舍与偏好 (Trade-offs)】   【3. 异常与降级预期 (Fallbacks)】
• 哪些属于本轮必须完成的 MVP？         • 偏好极简自持还是完整扩展机制？     • 依赖服务/外部 API 故障时如何降级？
• 哪些属于后续迭代或不可触碰区域？     • 新旧接口的兼容与迁移策略是什么？   • 是 Fail-Closed 熔断还是静默兜底？
                                       │
                                       ▼
                       【4. 联动影响与长期治理 (Impact & Governance)】
                       • 是否破坏 DOWN/UP/FORK 下游依赖与调用方契约？
                       • 是否涉及 JHOC 规则、Schema 契约、DataSanitizer 与存证流水同步？
```

---

## 2. 标准输出模板 (Standard Inquiry Template)

在回复或规划前列显式输出：

```markdown
### 开工方向多角度校准与基准反问 (Counter-Questioning Probe)

为了确保方案完全契合您的真实预期并丰富方向判断基准，请确认以下关键设计决策：

1. **【范围与交付边界 (Scope & MVP)】**：...
   - 选项 A: ...
   - 选项 B: ...
2. **【架构取舍与偏好 (Trade-offs)】**：...
   - 选项 A: ... (极简自持，代码更少)
   - 选项 B: ... (完整分层，扩展性强)
3. **【异常与降级预期 (Fallbacks)】**：...
   - 选项 A: Fail-Closed 阻断并报错
   - 选项 B: 降级走默认安全策略
4. **【联动影响与治理 (Impact & Governance)】**：...
   - 影响范围分析 (DOWN / UP / FORK)
```

---

## 3. 执行铁律与防旁路规约
- **严禁盲目假设**：存在多条可行技术路线时，严禁单方面自作主张下定论并静默实施；
- **交互式选项提供**：每个反问问题必须附带 2~4 个具体的选项与利弊对比，可直接调用 `ask_question` 工具呈现模态供用户勾选；
- **严禁被自动审批绑架**：即使系统环境存在自动通过的 Hook（Review Policy），在未与用户完成核心分歧对齐前，绝不得将粗制计划直接推向代码突变；
- **快慢分级通道**：当用户明确追加 `直接执行`、`无需反问`、或任务仅为单行 typo / 语法修复时，允许快速跳过。
