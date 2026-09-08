# JHOC 多模型协同配置与操作指南 (Multi-Model Collaboration Guide)

**面向多智能体异构协作、无网络本地 IPC 总线与排他租约的工程配置手册**

```text
[文档类型: 工程配置与运行指南]  [字符纯度: 零 EMOJI 纯净规范]
[覆盖客户端: ANTIGRAVITY IDE (GEMINI) | CLAUDE CODE | OPENAI CODEX | DEEPSEEK]
```

---

## 1. 概述与协同架构原理

在基于大语言模型的自主工作流中，单一模型往往存在固有的认知视界盲区、顺从偏误（Sycophancy）与自我验证陷阱（自己写的逻辑自己测试很难发现致命缺陷）。  
**JHOC 协同平面 (Multi-Model Hub)** 旨在探索一种**本地优先 (Local-First)、去中心化且不依赖远程云服务**的多模型并行协作架构：

```text
+-----------------------+     +-----------------------+     +-----------------------+
|  Antigravity IDE      |     |  Claude Code CLI      |     |  OpenAI Codex CLI     |
|  (Gemini Agent)       |     |  (Anthropic Agent)    |     |  (OpenAI Agent)       |
+-----------------------+     +-----------------------+     +-----------------------+
            \                             |                             /
             \                            |                            /
   (run_command / write)            (Bash / edit)             (terminal / write)
               \                          |                           /
                v                         v                          v
    +-----------------------------------------------------------------------+
    |           PreToolUse 门禁适配层 (scripts/jhoc_hook_gate.py)            |
    |          * 工具调用名称归一化  * 排他写租约核验  * 破坏性指令拦截     |
    +-----------------------------------------------------------------------+
                                          |
                                          v
    +-----------------------------------------------------------------------+
    |             SQLite WAL 协同中枢 (src/jhoc/hub/store.py)                |
    |  * Presence 状态追踪  * Bearer Token 互斥锁  * 信封消息总线 (IPC)     |
    +-----------------------------------------------------------------------+
                                          |
                                          v
    +-----------------------------------------------------------------------+
    |        共享物理工作区 (代码树、Schema、单元测试、黑盒哈希存证链)       |
    +-----------------------------------------------------------------------+
```

---

## 2. 各主流模型客户端接入配置

要让不同的模型客户端参与到同一个 JHOC 工作区的协同治理中，只需完成各客户端的轻量化配置：

### 2.1 Antigravity IDE (Gemini Agent) 配置

Antigravity IDE 原生支持项目级 `.agents/` 扩展规范。

- **物理门禁挂载**：工作区根目录已具备 `.agents/hooks.json`，声明了 `PreToolUse` 钩子；
- **身份标识环境变量**：
  可在系统环境或 IDE 终端中设置：

  ```bash
  export JHOC_MODEL_ID="antigravity-ide"
  ```

- **工作机制**：每次 Gemini 准备调用 `run_command` 或 `write_to_file` 时，IDE 自动触发 `jhoc_hook_gate.py` 进行前置安全与租约校验。

### 2.2 Claude Code CLI (`claude.exe`) 配置

Claude Code 是 Anthropic 官方推出的命令行自主编码工具。

- **根目录配置引导**：工作区根目录的 [`CLAUDE.md`](../../CLAUDE.md) 会在 Claude Code 启动时被自动读取；
- **身份标识环境变量**：
  在启动 Claude Code 的终端中设置：

  ```bash
  export JHOC_MODEL_ID="claude-code"
  ```

- **异构工具映射**：
  Claude Code 原生使用 `Bash(command=...)` 与 `str_replace_editor(path=...)`。门禁系统会自动将其规范化映射为内部统一参数，确保破坏性操作拦截与文件写租约检查生效。

### 2.3 OpenAI Codex CLI (`codex`) 配置

针对 OpenAI Codex 及其变体客户端：

- **宪法引导挂载**：Codex 启动时会自动读取根目录的 [`AGENTS.md`](../../AGENTS.md)；
- **身份标识环境变量**：

  ```bash
  export JHOC_MODEL_ID="codex-cli"
  ```

- **异构工具映射**：
  Codex 使用的 `terminal` 与 `write` 命令会自动映射为标准门禁流水线进行同等安检。

### 2.4 DeepSeek / 本地私有模型 Harness 配置

针对通过 Python 脚本或 Socket 派发的本地模型：

- **调度接口**：使用 `scripts/jhoc_dispatch.py` 为模型生成不可变的上下文快照；
- **身份标识**：调用时指定参数 `--caller deepseek-v4`，系统自动为其分配专属会话隔离区。

---

## 3. 排他写互斥与防伪租约机制 (File Mutex Leases)

当多个模型同时运行在同一个工作区时，最常见的事故是模型 A 正在修改某文件，模型 B 同时发起重写导致代码被覆盖丢失。

### 3.1 租约申请与释放流程

JHOC 采用带防伪令牌的租约机制（Bearer Token Mutex）：

```text
[模型 A] ---> 申请租约: acquire_file_lease("src/main.py", model="claude-code")
                  |
                  v
[Hub]   ---> 生成随机构造的 lease_id (例如: "lease-a8f9c1b2...")
                  |
                  v
[模型 A] ---> 获得写锁，在有效期内 (TTL=120s) 安全执行修改
                  |
                  v
[模型 B] ---> 尝试修改 "src/main.py"
                  |
                  v
[门禁]  ---> 拦截! 抛出 "File Mutex Conflict: Locked by claude-code"
                  |
                  v
[模型 A] ---> 修改完成，调用 release_file_lease("src/main.py", "lease-a8f9c1b2...")
                  |
                  v
[Hub]   ---> 校验 Token 一致，释放文件锁；其他模型可申领
```

### 3.2 僵尸租约与死锁防范

- **默认超时时间 (TTL)**：120 秒；
- **心跳续约**：正在执行长时间重构的模型可通过传递当前 `lease_id` 调用续约；
- **自动回收**：若持有锁的模型进程异常终止、崩溃或超时未续约，Hub 状态机会自动判定租约失效并予以释放，防止工作区永久锁死。

---

## 4. 跨模型信封通信总线 (Inter-Model Messaging)

多模型协作不仅需要互斥，还需要交换意图、评审意见与协同派发。

### 4.1 信封结构 (`MessageEnvelope`)

所有跨模型消息均封装为标准的数据结构：

```json
{
  "message_id": "msg-20260904-001",
  "sender_id": "antigravity-ide",
  "recipient_id": "claude-code",
  "channel_type": "TARGETED",
  "payload": {
    "action": "REVIEW_REQUEST",
    "target_files": ["src/jhoc/guard/vault.py"],
    "summary": "请对该凭据隔离模块的并发线程安全性进行红蓝对抗审查"
  },
  "status": "DELIVERED",
  "timestamp": "2026-09-04T03:00:00Z"
}
```

### 4.2 四种路由信道模式

1. **`TARGETED` (点对点直发)**：
   主模型明确指派特定模型协助完成特定模块审查；
2. **`BROADCAST` (全域广播)**：
   发生全局事件（如核心底层架构变更、全局写冻结）时向所有在线模型同步；
3. **`ROUND_ROBIN` (负载轮询)**：
   将大批量的单测编写或文档翻译任务轮流派发给空闲模型；
4. **`CONSENSUS` (多票共识)**：
   重大架构方案或发布前，收集来自 2 个以上不同模型的独立赞成票方可放行。

---

## 5. 多模型对抗协审实战流水线 (Adversarial Co-Review)

JHOC 内置了多模型对抗协审分发脚本 [`scripts/jhoc_run_co_review.py`](../../scripts/jhoc_run_co_review.py)，其标准实战流如下：

```powershell
# 执行多模型对抗协审分发
python scripts/jhoc_run_co_review.py
```

### 协审流水线执行阶段

1. **上下文提取**：从当前工作区中提取最新的 Git Diff 与架构设计说明；
2. **异构模型拉起**：自动调用本地可用的各厂商 CLI（如 `claude.exe` 或 `codex`）；
3. **红队质询注入**：向受试模型注入批判性质询 Prompt，要求其作为红队安全专家寻找代码中的并发漏洞、绕过风险与边缘失效；
4. **响应结构化归档**：将各模型的真实回答落盘至 `logs/co-review/`，并向 `p19-hub.sqlite` 登记交互事件；
5. **人类复核收敛**：主模型结合外部模型的审阅意见进行针对性加固，直至多方达成共识。

---

## 6. 协同审计大屏与多模型归因监控

在多模型协作期间，随时可以执行状态大屏命令：

```powershell
python scripts/jhoc_log_stats.py
```

### 监控重点指标

- **Model Attribution (模型调用归因)**：清晰呈现每个模型各自调用了多少次工具、多少次放行、多少次被门禁拦截；
- **Active Leases (活跃写锁)**：查看当前哪些文件被哪个模型加锁持有，避免盲目等待；
- **Human Approval Inbox (人工工单状态)**：查看各模型提交的高危操作审批工单流转情况。

---

## 7. 常见协同故障排查速查 (FAQ)

| 表现现象 | 根本原因 (Root Cause) | 解决方式 |
| :--- | :--- | :--- |
| **`File Mutex Conflict` 报错** | 目标文件正被其他模型修改，租约尚未释放 | 等待持有模型完成（最长 120s TTL），或联系持有模型调用 `release_file_lease` 提前让渡 |
| **外部模型执行高危命令被阻断** | 触发了门禁的高危命令拦截矩阵 | 引导该模型走工单流，操作员使用 `python scripts/jhoc_approve.py approve <工单ID>` 单次放行 |
| **不同模型对同一规范理解冲突** | 各模型提示词存在细微偏差 | 统一以根目录 [`AGENTS.md`](../../AGENTS.md) 纯 ASCII 宪法为最高裁决基准 |
| **模型调用工具未被门禁拦截** | 未正确配置 `.agents/hooks.json` 或工具别名未映射 | 确认模型是否支持 PreToolUse 钩子，并在 `jhoc_hook_gate.py` 中确认工具名映射 |
