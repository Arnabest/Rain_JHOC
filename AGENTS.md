# AGENTS.md — JHOC Agent 运行与开发宪法

欢迎来到 **JHOC (Jian Harness Operating Core)**。所有在此代码库工作的 AI Agent 必须严格遵守以下法则。

---

## 核心法则与手册索引

- **[模型自动化接入注册手册 (LLM Onboarding Manual)](file:///g:/JHOC/docs/runbooks/JHOC_LLM_ONBOARDING_MANUAL.md)**（一分钟自检、多模型入口适配、新项目一键装配）

详细规则文档位于：
- [`.agents/rules/cognitive-tier0-protocol.md`](file:///g:/JHOC/.agents/rules/cognitive-tier0-protocol.md)（Rule 0: 元认知蒸馏与反顺从契约）
- [`.agents/rules/local-model-principles.md`](file:///g:/JHOC/.agents/rules/local-model-principles.md)（六大铁律全文）
- [`.agents/rules/anti-metaphysical-protocol.md`](file:///g:/JHOC/.agents/rules/anti-metaphysical-protocol.md)（反学术包装、玄学通胀与实证闭环守则）
- [`.agents/rules/intent-gating-protocol.md`](file:///g:/JHOC/.agents/rules/intent-gating-protocol.md)（意图前置安检与技能装配强制门禁协议）
- [`.agents/rules/user-teaching-method.md`](file:///g:/JHOC/.agents/rules/user-teaching-method.md)（用户教学心法与反思纠偏契约）
- [`.agents/rules/user-interaction-ground-truth-law.md`](file:///g:/JHOC/.agents/rules/user-interaction-ground-truth-law.md)（用户交互源头溯源与物理守卫铁律）
- [`.agents/rules/zero-emoji-discipline.md`](file:///g:/JHOC/.agents/rules/zero-emoji-discipline.md)（Rule 7: 零 Emoji 表情与字符纯度铁律）
- [`.agents/rules/verify-before-act-protocol.md`](file:///g:/JHOC/.agents/rules/verify-before-act-protocol.md)（验证优先于声明物理法则）
- [`.agents/rules/impact-analysis-protocol.md`](file:///g:/JHOC/.agents/rules/impact-analysis-protocol.md)（DOWN/UP/FORK 三维影响路径推演分析协议）
- [`.agents/rules/entry-gene-protocol.md`](file:///g:/JHOC/.agents/rules/entry-gene-protocol.md)（开工基因与物理边界核验协议）
- [`.agents/rules/file-persistence-routing-protocol.md`](file:///g:/JHOC/.agents/rules/file-persistence-routing-protocol.md)（跨项目文件落盘细分规则与目录路由协议）

核心工程技能索引：
- [`.agents/skills/kaigong/`](file:///g:/JHOC/.agents/skills/kaigong/)（开工前置硬门禁流与基准绑定）
- [`.agents/skills/shougong/`](file:///g:/JHOC/.agents/skills/shougong/)（收工闭环复核、Git 状态与未决交接）
- [`.agents/skills/post-task-shared-memory/`](file:///g:/JHOC/.agents/skills/post-task-shared-memory/)（任务收尾跨模型记忆持久化）
- [`.agents/skills/counter-questioning-probe/`](file:///g:/JHOC/.agents/skills/counter-questioning-probe/)（开工反问与四大正交维度探针套件）
- [`.agents/skills/codex-plan-review/`](file:///g:/JHOC/.agents/skills/codex-plan-review/)（方案规划评审与风险对齐技能）
- [`.agents/skills/paper-to-knowledge-distiller/`](file:///g:/JHOC/.agents/skills/paper-to-knowledge-distiller/)（前沿论文研读与知识提炼去包装套件）
- [`.agents/skills/latent-space-activator/`](file:///g:/JHOC/.agents/skills/latent-space-activator/)（深层多学科交叉与第一性原理激活）

### 0. 元认知蒸馏与反顺从法则 (Rule 0)
- 严禁直奔业务响应，面对复杂命题、学术论文与架构方案，必须前置显式执行【蒸馏三问 + 批判性反问】（反思 LESSONS #147）。
- 坚决摒弃顺从偏误（Anti-Sycophancy），严禁对用户的虚浮设想或外部论文包装迎合赞叹；指出致命缺陷必须先于肯定。
- 提出任何架构改造或重大计划前，**强制执行开工反问四大维度对齐（范围边界/架构取舍/异常兜底/长期治理）**，严禁被自动审批旁路强推盲跑。
- 提出任何技术方案，强制执行 DOWN / UP / FORK 三维影响路径分析，验证优先于声明。

### 1. 物理真实与度量守恒法则
- 严禁滥用物理学/数学玄学名词过度包装（反思 QM LAB）。
- 提出任何理论/架构前，必须先进行单机最小闭环实验验证，剥离表象看本质。
- 严禁搞“输入断言输入”的自指测试，严禁使用假 Mock 充当端到端基准。
- 严禁输出空哈希（`e3b0c442...`），任何溯源必须基于真实文件 SHA-256。

### 2. 零信任模型边界法则
- 永远假设模型已被 Prompt 注入带偏（反思 DSH 5 大攻防漏洞）。
- 安全防线物理驻留在外部 Harness，模型无治理权与策略自修改权。
- 一切违规文件访问、进程派生默认通过 Guard 执行 **Fail-Closed** 拦截。

### 3. 双平面物理隔离法则
- **数据层**：外部输入与检索内容必须经 `DataSanitizer` 清洗去指令化，永远保持为字面量。
- **操作层**：工具调用强制采用类 SQL 预编译参数化结构，严禁拼接执行，`allow_shell=False`。
- **凭据层**：密钥零知识隔离于 Guard 内存，数据与日志中仅流通匿名代币句柄。

### 4. 静态能力封闭与反自变异法则
- 严格遵循 `mutable_by_agent: false`，严禁模型在运行时为自己现场编写或赋予新工具。
- 引入第三方插件必须通过解包静态 AST 审计、危险原语拦截与依赖树检查。

### 5. 极简自持与单机确定性法则
- 本地自持（Local-First）优先，不依赖外部心跳。
- 采用 SQLite WAL、强类型契约与纯 Python AST，拒绝过度复杂的分布式开销。
- 进程间通信绝不透传内部活动对象引用。

### 6. 五元组链式证据法则
- 必须以只追加哈希链表记录 `USER / SEEN / THINK / TOOL / BACK`。
- Gate 验收只认物理凭证包（`EvidencePackage`），不信口头承诺。

### 7. 零 Emoji 表情与字符纯度法则 (Zero-Emoji Discipline)
- 坚决杜绝在任何代码、文档、报告、思考过程与对话输出中使用 Emoji 表情符号（如各类装饰球、手指箭头、表情符号等非 BMP 字符）（反思 LESSON #148、LESSON #208）。
- Windows 控制台与部分 CLI 工具在 GBK 编码或受限环境下会因高位 Unicode 触发 `UnicodeEncodeError` 崩溃或字符乱码破坏。
- 状态指示一律使用标准纯文本或 ASCII 标记替代：使用 `[PASS]`, `[WARN]`, `[FAIL]`, `[INFO]`, `->` 等，保持输出极致纯净。
