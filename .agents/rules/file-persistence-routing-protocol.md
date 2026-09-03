# 跨项目文件落盘细分规则与目录路由协议 (File Persistence Routing Protocol)

> **核心原则**：各归其位，严禁乱存。生产代码进源码包，单测进测试集，临时探针进草稿箱，项目状态留本地，全局共性经验进 JHOC 母体。（反思 Rule 1、Rule 3、Rule 5）  
> **字符纯度**：遵循 Rule 7 零 Emoji 铁律，纯文本/标准 ASCII 标记输出。

---

## 1. 五级文件落盘语义分区 (5-Zone Persistence Matrix)

所有在任意项目工作区中运行的 AI Model / Agent，落盘新建或修改文件时必须严格路由至对应的语义分区：

| 分区类别 | 准许落盘物理路径 | 严格准入内容 | 严厉禁止行为 (Fail-Closed) |
| :--- | :--- | :--- | :--- |
| **Zone 1: 生产源码区** | `<workspace>/src/` 或项目既有业务代码包 | 正式业务逻辑、强类型契约、核心接口 | 严禁存放任何一次性调试脚本、未经封装的临时函数 |
| **Zone 2: 测试套件区** | `<workspace>/tests/` | 单元测试、集成测试、基准套件（`test_*.py`） | 严禁在测试中自指断言（自己测自己输入）；严禁空哈希假测试 |
| **Zone 3: 临时探针与草稿区** | `<artifactDir>/scratch/` 或本地 `scratch/` | 实验探针、中间状态、清洗转换脚本、临时数据 dump | **严禁直接在项目根目录下抛掷零碎测试脚本或调试日志** |
| **Zone 4: 项目专有记忆区** | `<workspace>/memory/` | 本次任务状态（`v3_task_state.json`）、会话纪要（`session-*.md`） | 严禁混入其他项目的专有状态；严禁存放未脱毒的敏感密钥 |
| **Zone 5: JHOC 全局母体区** | `G:\JHOC\docs\lessons/`, `G:\JHOC\.agents\skills/` | 跨项目普适性避坑教训（Lessons）、经 AST 审计的货架技能 | **严禁把单个项目私有的业务代码或特定私有接口归档入 JHOC 母体** |

---

## 2. 根目录零碎文件禁令 (Anti-Root-Littering Invariant)

- **现象警示**：Agent 在排查问题或编写代码时，极易习惯性地在工作区根目录下随手创建 `test.py`, `debug_tmp.py`, `dump.json`, `result.txt` 等垃圾文件；
- **硬红线规定**：
  - 项目根目录只允许存放项目结构级文件（如 `AGENTS.md`, `CLAUDE.md`, `README.md`, `pyproject.toml`, `.gitignore`, 配置目录等）；
  - 任何探索性代码、临时复现脚本或验证脚本，**必须统一放置在 `scratch/` 目录中**；
  - 任务结束时，收工门禁（`jhoc_shougong.py`）将检查工作区根目录文件变动，存在未清理的根目录垃圾文件直接阻断交付。

---

## 3. 跨项目切换时的落盘重定向规则 (Cross-Project Scoping)

当用户指示切换至新工作区（如 `D:\Project-Beta`）时：
1. **锁定工作区根路径**：所有 Zone 1 ~ Zone 4 的相对路径基准立即切换为 `D:\Project-Beta`；
2. **锁定全局母体路径**：Zone 5（全局经验与技能）的物理路径永远保持为 `G:\JHOC\`；
3. **隔离判定**：在 `D:\Project-Beta` 工作时生成的 `v3_task_state.json` 只能写入 `D:\Project-Beta\memory\`，严禁跨盘符覆盖 `G:\JHOC\memory\` 中的宿主状态！

---

## 4. 物理守卫与门禁联动

- **PreToolUse 拦截**：IDE 与 CLI 的文件写入工具（`write_to_file`, `replace_file_content`）受 `jhoc_hook_gate.py` 前置审查：
  - 若检测到在根目录创建临时探针，或尝试跨项目篡改非授权文件，立即返回 `decision: deny`；
- **Fail-Closed 错误提示**：触发落盘违规时，拦截器将明确告知目标规范路径，引导模型自纠错并重新落盘。
