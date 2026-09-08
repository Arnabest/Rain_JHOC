# 本地模型系统与 Agent Harness 研发六大铁律 (Local Model Engineering Principles)

> 来源：吸取 DeepSeek Harness (DSH) 5 大攻防漏洞与 QM LAB 实验翻车造假之深刻教训，为 JHOC 及后续所有本地大模型/Agent 研发制定的不可逾越之基准法则。

---

## 1. 物理真实与度量守恒法则 (Reality & Physical Verification Invariant)
- **拒绝学术包装与词汇通胀**：严禁滥用物理学/数学玄学词汇包装常规工程逻辑（如将 Sigmoid 过滤包装为量子退火）。代码与架构坚持使用 Native Contracts 和清晰命名。
- **拒绝自指断言与伪基准**：严禁在单元测试中搞“输入断言自身”的同义反复；严禁使用 Mock 替代真实大模型物理推理却声称具备真实性能。测试必须经受断电恢复、真实模型推理及物理沙箱验证。
- **密码学真迹**：严禁生成空字符串哈希（`e3b0c442...`）冒充溯源账本；所有证据哈希必须对真实物理文件计算。

## 2. 零信任模型边界法则 (Zero-Trust Model Boundary)
- **永远假设模型已被注入带偏**：提示词注入是大模型的内生机理缺陷，无法仅靠 System Prompt 或模型“自觉”消灭。真正的安全边界必须物理驻留在模型上下文之外。
- **所有权与鉴权收归外部 Harness**：模型只是算力单元与候选方案生成者，绝对没有治理规则的决议权与自修改权。
- **Fail-Closed 刚性拦截**：所有的文件读写、网络连接、进程派生必须受外部 Guard（如 `PathGuard`）物理拦截，默认拒绝一切未授权操作。

## 3. 双平面物理隔离法则 (Bi-Planar Physical Isolation)
- **数据层去指令化 (Data Sanitization)**：所有外部不可信数据（网页、文档、上下文）在流入 Prompt 之前，必须经过 `DataSanitizer` 剥离零宽字符并转义注入模式，永远保持纯字面量状态，绝不允许数据自发晋升为执行指令。
- **操作层预编译参数化 (Parameterized Invocation)**：工具调用必须采用类 SQL 预编译结构骨架，强制 `allow_shell=False`，参数作为字面量插槽传入，彻底杜绝 Shell 拼接注入。
- **凭据零知识隔离 (Zero-Knowledge Vault)**：真实密钥仅存在于 Guard 受保护内存中，数据流与日志中仅允许匿名引用（`vault://...`），严禁模型直接接触明文密钥。

## 4. 静态能力封闭与反自变异法则 (Capability Closure & Anti-Mutation)
- **能力预先静态声明**：工具与特权必须在任务执行前静态绑定，严格遵循 `mutable_by_agent: false` 铁律。
- **严禁模型运行时自造工具**：彻底禁止模型在运行时调用 `define_tool` 等原语为自己赋予未受审的新权限。
- **进门三道闸审查**：引入任何第三方插件必须通过免运行的静态 AST 审计、危险原语扫描及依赖数检查，严禁运行未知安装脚本。

## 5. 极简自持与单机确定性法则 (Radical Local-First Simplicity)
- **单机自持高于一切**：优先保证无网络连接状态下的完整运行能力，不依赖任何不可控的外部心跳。
- **崇尚坚固的原生基石**：优先采用 SQLite WAL 模式、强类型数据契约（JSON Schema / Dataclasses）、纯 Python AST 语法分析，拒绝非必要的复杂分布式中间件与过度抽象。
- **不跨进程透传内部活动对象句柄**：组件通信只传递标准序列化数据，防止内存穿透与对象劫持。

## 6. 五元组链式证据法则 (Cryptographic Accountability)
- **全流程上链追溯**：必须以只追加（Append-Only）密码学哈希链表记录 `USER / SEEN / THINK / TOOL / BACK` 完整五元组。
- **Gate 验收只认物理凭证**：任务完成判定不依赖模型的口头陈述，必须校验 `EvidencePackage` 中的哈希指纹、测试退出码和可重复验证的物理交付件。
