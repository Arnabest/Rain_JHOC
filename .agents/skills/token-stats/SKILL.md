---
name: token-stats
canonical_id: token-stats
aliases: ["token-stats", "token_stats", "/token_stats", "额度查询", "账户配额", "配额检测"]
description: "JHOC 账户配额实时检测与 8% 临界阈值自动交接：通过 Connect-RPC 实时采集 Antigravity 双桶配额，在额度告急时主动触发熔断交接。"
version: 2.1.0
category: governance
trigger: ["token-stats", "token_stats", "/token_stats", "额度查询", "账户配额", "配额检测", "token统计", "配额统计"]
when_to_use: ["需要查询当前窗口绑定账户的 5H/Weekly 实时配额与重置倒计时", "开工前评估当前账号余量是否充足", "任务执行过程中进行阶段性配额巡检", "配额 <= 8% 时指导安全熔断与跨模型/跨账号接力"]
skill_tier: core
---

# Token Stats - JHOC 账户配额实时检测与 8% 临界交接规范

## 1. 触发与治理定位

- **治理定位**: 属于生命周期阶段 6 (CLOSURE) 与全生命周期巡检辅助通道；
- **核心契约**: 通过本地 Language Server Connect-RPC 实时拉取 Antigravity 宿主配额，实现 1-to-1 多窗口、多账户隔离与精确倒计时计算；
- **免除条件**: 仅执行简单文本查询且无网络/RPC 探针需求时跳过。

---

## 2. 核心操作命令

1. **实时配额与 Token 消耗打印**:
   ```powershell
   python scripts/jhoc_token_stats.py
   ```
2. **静默告警检查 (用于自动化脚本门禁)**:
   ```powershell
   python scripts/jhoc_token_stats.py --check-alert --threshold 8.0
   ```
   - 退出码 `0`: 配额充足 (5H 与 Weekly 均 > 8%)；
   - 退出码 `1`: 配额告急 (5H 或 Weekly <= 8%)，必须立刻进入交接流程。

---

## 3. 8% 临界额度熔断交接四步流 (不可跳步)

当检测到当前账户 5小时或每周剩余额度 <= 8% 时，模型必须立刻停止大规模代码重构，严格执行以下交接流程：

1. **第 1 步：代码物理零暂存落盘**:
   - 严禁将未完成的代码仅保留在对话上下文或内存中；
   - 立即调用 `write_to_file` 或 `replace_file_content` 将当前全部改动物理固化至本地磁盘；
2. **第 2 步：实现计划状态固化**:
   - 更新 `implementation_plan.md`，将已完成的条目标记为 `[x]`，并在断点处清晰注明接下来待执行的步骤；
3. **第 3 步：任务状态与跨模型交接包沉淀**:
   - 运行收工或记忆归档命令，生成包含未决事项（Pending Actions）的 `memory/handoff-latest.json` 与 `memory/session-YYYYMMDD-topic.md`；
4. **第 4 步：向用户输出切换账号预警**:
   - 明确输出告警横幅，提示当前账户邮箱、剩余百分比与预计重置时间；
   - 引导用户切换到备用 IDE 窗口/账户，或使用备用模型通过 `/开工` 秒级无缝接力。
