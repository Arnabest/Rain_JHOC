# JHOC 技能货架权威总目录 (Skill Shelf Ledger)

> **Authority**: Governed under [`ADR-0009-registry-shelf-quota.md`](file:///g:/JHOC/docs/adr/ADR-0009-registry-shelf-quota.md) 与 [`src/jhoc/shelf/`](file:///g:/JHOC/src/jhoc/shelf/)
> **准入技能总数**: 8 项 | **状态**: 全部 VERIFIED & SHELF_ELIGIBLE

---

| 技能 Canonical ID | 版本 | 分类 | 触发特征 / Aliases | 准入状态 | 对应文件 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `codex-plan-review` | `1.1.0` | `collaboration` | `codex-plan-review`, `plan-review`, `规划复核` | `VERIFIED` | [codex-plan-review](.agents/skills/codex-plan-review/SKILL.md) |
| `counter-questioning-probe` | `1.1.0` | `methodology` | `counter-questioning-probe`, `task-inquiry`, `direction-probe` | `VERIFIED` | [counter-questioning-probe](.agents/skills/counter-questioning-probe/SKILL.md) |
| `kaigong` | `2.1.0` | `workflow` | `/开工`, `开工`, `kaigong` | `VERIFIED` | [kaigong](.agents/skills/kaigong/SKILL.md) |
| `latent-space-activator` | `1.1.0` | `methodology` | `$latent`, `/paradigm`, `潜空间` | `VERIFIED` | [latent-space-activator](.agents/skills/latent-space-activator/SKILL.md) |
| `paper-to-knowledge-distiller` | `1.1.0` | `methodology` | `paper-to-knowledge-distiller`, `paper-distiller`, `论文研读` | `VERIFIED` | [paper-to-knowledge-distiller](.agents/skills/paper-to-knowledge-distiller/SKILL.md) |
| `post-task-shared-memory` | `2.1.0` | `memory` | `post-task-shared-memory`, `共享记忆归档`, `任务收尾归档` | `VERIFIED` | [post-task-shared-memory](.agents/skills/post-task-shared-memory/SKILL.md) |
| `shougong` | `2.1.0` | `workflow` | `/收工`, `收工`, `shougong` | `VERIFIED` | [shougong](.agents/skills/shougong/SKILL.md) |
| `token-stats` | `2.1.0` | `governance` | `token-stats`, `token_stats`, `额度查询` | `VERIFIED` | [token-stats](.agents/skills/token-stats/SKILL.md) |

---

## 货架上架硬契约与门禁
1. **禁止裸露文件存在**：`.agents/skills/` 目录下任何未在此货架登记的技能，在自动化合规测试中均判定为 `E_UNADMITTED_SKILL` 阻断！
2. **单一事实源**：每个技能必须具备合法的 YAML Frontmatter 与只读不可变标志 (`mutable_by_agent: false`)。
3. **意图调度联动**：所有上架技能必须与 `src/jhoc/intent/classifier.py` 建立特征绑定，支持程序化自动装配。

---

## 技能生命周期拓扑偏序契约 (Skill Lifecycle Partial Order DAG)

为根除多技能并发调用与错序执行时产生的基线覆盖、虚假记忆污染与并发写崩溃，货架技能严格遵循以下 6 阶段因果时序，严禁逆序跳步：

```text
[阶段 1: INCEPTION 需求澄清期]
  - 核心技能: counter-questioning-probe, paper-to-knowledge-distiller
  - 约束: 仅分析需求与前置反问，审定生成式规范边界，严禁写代码，严禁开工。

[阶段 2: ELABORATION 方案冻结期]
  - 核心技能: codex-plan-review
  - 约束: 执行 DOWN/UP/FORK 影响分析与 Plan Checkpoint 方案门禁，产出 implementation plan，等待审批。

[阶段 3: ARM 开工锁定期]
  - 核心技能: kaigong
  - 约束: 方案批准后执行；记录 Git Baseline Commit SHA，状态跃迁至 ARMED；
          若任务已处于 ARMED 状态，执行重入保护，保留初始基线防篡改。

[阶段 4: EXECUTION 执行实施期]
  - 核心技能: latent-space-activator, 代码编写与重构工具
  - 约束: 仅在 ARMED 状态下允许文件写操作；受 hook_gate 门禁全程守护。

[阶段 5: VERIFICATION 验收写冻结期]
  - 核心技能: shougong (步骤 1 - 5)
  - 约束: 前置断言必须为 ARMED；激活全局写冻结锁 (write_freeze.lock)，
          执行全量单测、契约验证与零 Emoji 审查；测试期间阻断一切写入工具。

[阶段 6: CLOSURE 收尾归档期]
  - 核心技能: post-task-shared-memory, shougong (步骤 6), token-stats
  - 约束: 仅在单测 100% 满绿后触发；生成 handoff-latest.json，沉淀 session.md，
          状态跃迁至 CLOSED 并解除写冻结，输出归档证据与 Token 统计，并在配额 <= 8% 时输出熔断告警。
```