---
name: kaigong
canonical_id: kaigong
aliases: ["/开工", "开工", "kaigong", "$kaigong"]
description: "JHOC 开工前置硬门禁流：执行工作区路径锁定、规则对齐、Rule 0 蒸馏三问与方向反问、任务目标与断言绑定。"
version: 2.1.0
category: workflow
trigger: ["/开工", "开工", "kaigong", "$kaigong", "/kaigong", "开工门禁", "启动任务"]
when_to_use: ["开始任何编码、调试、重构、配置或架构任务时", "用户输入 /开工 或 开工", "重置任务门禁状态并对齐基准"]
skill_tier: core
---

# /开工 — JHOC 开工前置硬门禁规范

## 1. 触发条件

- **强制执行**：用户输入 `/开工`、`开工`、`$kaigong`；或在进行任何代码修改、架构重构、排错与配置工作之前；
- **免除条件**：纯日常概念解释或闲聊；跳过时在思考中简要说明 `kaigong skipped: pure chat`。

---

## 2. 机械执行五步门禁（不可跳步）

1. **第 1 步：工作区与物理边界锁定**：
   - 确认当前绝对路径为 `g:\JHOC`；
   - 严禁向外部临时目录、Desktop 或隔离归档区（`logs/p19-quarantine/`）写入业务代码；
2. **第 2 步：宪法与纯度红线核对**：
   - 确认遵守 `AGENTS.md` 核心宪法；
   - 坚决执行 Rule 7 零 Emoji 铁律，全程使用纯净 ASCII / Flat 标准文本；
3. **第 3 步：Rule 0 认知前置**：
   - 首段显式执行【蒸馏三问 + 批判性反问】；
   - 若面临新需求或架构方案，强制执行 `counter-questioning-probe`，从四大正交维度（范围边界、架构取舍、异常降级、长期治理）主动反问；
4. **第 4 步：基准与断言绑定**：
   - 运行物理开工门禁脚本：
     ```powershell
     python scripts/jhoc_kaigong.py --title "<任务一句话描述>"
     ```
   - 确认输出包含 `gate: ALLOW`；
   - 明确本次任务的修改目标与预期的可证伪单测命令（如 `python -m unittest ...`）；
5. **第 5 步：启动执行**：
   - 门禁全部就绪后，方可创建或修改实际源文件。
