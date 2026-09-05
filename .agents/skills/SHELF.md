# JHOC 技能货架权威总目录 (Skill Shelf Ledger)

> **Authority**: Governed under [`ADR-0009-registry-shelf-quota.md`](file:///g:/JHOC/docs/adr/ADR-0009-registry-shelf-quota.md) 与 [`src/jhoc/shelf/`](file:///g:/JHOC/src/jhoc/shelf/)
> **技能总数**: 12 项 (核心工程治理: 8 项 | 领域业务扩展: 4 项) | **状态**: 全部 VERIFIED & SHELF_ELIGIBLE

---

## 一、 核心工程与治理技能货架 (Core Governance & Engineering Shelf)
> **物理空间**: `.agents/skills/` | **定位**: 框架微内核生命周期内置常驻能力，严禁动态剥离，随微内核发行。

| 技能 Canonical ID | 层级 | 版本 | 分类 | 触发特征 / Aliases | 准入状态 | 对应文件 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `codex-plan-review` | `core` | `1.1.0` | `collaboration` | `codex-plan-review`, `plan-review`, `规划复核` | `VERIFIED` | [codex-plan-review](codex-plan-review/SKILL.md) |
| `counter-questioning-probe` | `core` | `1.1.0` | `methodology` | `counter-questioning-probe`, `task-inquiry`, `direction-probe` | `VERIFIED` | [counter-questioning-probe](counter-questioning-probe/SKILL.md) |
| `kaigong` | `core` | `2.1.0` | `workflow` | `/开工`, `开工`, `kaigong` | `VERIFIED` | [kaigong](kaigong/SKILL.md) |
| `latent-space-activator` | `core` | `1.1.0` | `methodology` | `$latent`, `/paradigm`, `潜空间` | `VERIFIED` | [latent-space-activator](latent-space-activator/SKILL.md) |
| `paper-to-knowledge-distiller` | `core` | `1.1.0` | `methodology` | `paper-to-knowledge-distiller`, `paper-distiller`, `论文研读` | `VERIFIED` | [paper-to-knowledge-distiller](paper-to-knowledge-distiller/SKILL.md) |
| `post-task-shared-memory` | `core` | `2.1.0` | `memory` | `post-task-shared-memory`, `共享记忆归档`, `任务收尾归档` | `VERIFIED` | [post-task-shared-memory](post-task-shared-memory/SKILL.md) |
| `shougong` | `core` | `2.1.0` | `workflow` | `/收工`, `收工`, `shougong` | `VERIFIED` | [shougong](shougong/SKILL.md) |
| `token-stats` | `core` | `2.1.0` | `governance` | `token-stats`, `token_stats`, `/token_stats` | `VERIFIED` | [token-stats](token-stats/SKILL.md) |

---

## 二、 领域与业务扩展插件货架 (Domain & Business Plugin Shelf)
> **物理空间**: `.agents/plugins/domain-content/skills/` | **定位**: 业务领域专用扩展包，按需热插拔，不随微内核发行。

| 技能 Canonical ID | 层级 | 版本 | 分类 | 触发特征 / Aliases | 准入状态 | 对应文件 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `beautiful-article` | `domain` | `1.0.0` | `presentation` | `beautiful-article`, `网页长文`, `生成文章` | `VERIFIED` | [beautiful-article](../plugins/domain-content/skills/beautiful-article/SKILL.md) |
| `content-generative-harness` | `domain` | `1.0.0` | `methodology` | `content-generative-harness`, `内容生成式规范`, `生成式Harness` | `VERIFIED` | [content-generative-harness](../plugins/domain-content/skills/content-generative-harness/SKILL.md) |
| `web-video-presentation` | `domain` | `1.1.0` | `multimodal` | `web-video-presentation`, `web-video`, `制作视频` | `VERIFIED` | [web-video-presentation](../plugins/domain-content/skills/web-video-presentation/SKILL.md) |
| `worklog-distiller` | `domain` | `1.0.0` | `presentation` | `worklog-distiller`, `工作日志`, `日志总结` | `VERIFIED` | [worklog-distiller](../plugins/domain-content/skills/worklog-distiller/SKILL.md) |

---

## 货架上架硬契约与门禁
1. **禁止裸露文件存在**：`.agents/skills/` 目录下任何未在核心货架登记的技能，在自动化合规测试中均判定为 `E_UNADMITTED_SKILL` 阻断！
2. **单一事实源**：每个技能必须具备合法的 YAML Frontmatter、强类型 `skill_tier` 与只读不可变标志 (`mutable_by_agent: false`)。
3. **意图调度联动**：所有上架技能必须与 `src/jhoc/intent/classifier.py` 建立特征绑定，支持程序化自动装配。
