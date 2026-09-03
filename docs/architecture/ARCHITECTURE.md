# JHOC 独立架构设计

版本：V5
日期：2026-09-01
状态：概念架构基线与实施蓝图

`JHOC` = `Just-in-time Harness Orchestration Core`

JHOC 是一个本地优先、插件化、可观测、可验证、可恢复、可自进化的 Agent Harness 运行时。它把每个任务的上下文、治理策略、能力、资源、执行循环、验收、证据和经验沉淀组织成一个可重建的即时 Harness。

## 1. 架构边界和独立性

JHOC 是唯一运行时入口。AIBOX、VERS 和旧 Agent Bus 不参与 JHOC 运行，不提供运行时 API，不共享状态、数据库、目录或消息协议。

```text
JHOC Runtime
  独立代码、独立协议、独立状态、独立存储、独立权限

AIBOX / VERS / old Agent Bus
  只读历史资产、规则语义、缺陷样本和离线迁移来源
```

不允许：

```text
运行时读取 AIBOX/VERS 文件
运行时读取旧 state.json 或 model-space.jsonl
复用旧 Agent Bus 协议或实现
与旧系统双写
把旧系统作为故障回退运行时
```

历史数据只能经过 `JHOC Ingest` 离线甄别、转换、校验和导入。导入完成后，JHOC 不再访问旧系统。

## 2. 核心架构原则

```text
先边界，再契约
先契约，再内核
先观测，再业务
先治理，再执行
先状态，再智能行为
继承经验，不继承实现
迁移数据，不共享运行时
社区内容默认不可信
候选变更必须评测、审批、灰度和回滚
前台任务永远高于后台自治任务
```

模型负责推理和生成；JHOC 负责将任务变成有边界、有资源、有状态、有证据的执行过程。

## 3. 总体分层

```text
JHOC
├── JHOC Origin       启动与安全初始态
├── JHOC Core         运行时内核
├── JHOC Contracts    原生领域和协议契约
├── JHOC Flow         统一工作管路
├── JHOC Trust        身份、信任和密钥
├── JHOC Config       配置、特性和版本
├── JHOC Relay        Agent Bus V2
├── JHOC Lens         日志、Trace、指标和诊断
├── JHOC Guard        治理运行时
├── JHOC Atlas        知识平面
├── JHOC Graph        知识图谱
├── JHOC Memory       记忆平面
├── JHOC Proof        证据和审计
├── JHOC Registry     能力注册中心
├── JHOC Shelf        能力货架
├── JHOC Quota        资源治理器
├── JHOC Conductor    能力编排器
├── JHOC Context      上下文编排器
├── JHOC Runner       执行运行时
├── JHOC Gate         验收门
├── JHOC Output       受验证结果驱动的输出适配
├── JHOC Commons      模型社区自留地
├── JHOC Idle         后台自治调度器
├── JHOC Forge        自进化工坊
├── JHOC Bench        评测和基线
├── JHOC Restore      备份和恢复
├── JHOC Ingest       一次性离线迁移
└── JHOC Ops          运维和管理
```

输入、传感器、意图预测和风险分析属于 `Origin/Flow` 承载的插件类别，不是额外的可信数据所有者。它们只能提供带来源和置信度的观测或分析结果；任务等级、权限和最终风险判定仍由 JHOC Core/Guard 依据契约确定。

## 4. 端到端主链路

```text
Input / Sensor / Schedule / IDE Event
  -> JHOC Origin
  -> Task Profile
  -> Intent and Risk Analysis
  -> JHOC Context: minimal pre-context (metadata only)
  -> JHOC Guard
  -> JHOC Conductor
       -> Registry/Shelf: discover and filter candidates
       -> Quota: admit and lease resources
  -> JHOC Context: authorized source activation and full package
  -> JHOC Relay
  -> JHOC Runner
       PLAN -> ACT -> OBSERVE -> VERIFY -> REPAIR
  -> JHOC Gate
  -> Accepted WorkResult / EvidencePackage
       -> JHOC Proof (audit and evidence sealing)
       -> JHOC Output (user delivery)
  -> JHOC Memory / Atlas / Graph (downstream)
  -> JHOC Commons / Forge (optional asynchronous downstream)
```

关键顺序：

```text
意图和风险预判
  -> 最小上下文编排
  -> 策略决策
  -> 能力和资源计划
  -> 完整上下文编排
  -> 执行
```

执行过程中若意图、风险、数据范围或能力需求发生变化，必须重新经过策略和资源检查。

## 5. 统一工作管路

所有模块、组件和插件必须映射到：

```text
RECEIVE
  -> VALIDATE
  -> NORMALIZE
  -> CLASSIFY
  -> AUTHORIZE
  -> PLAN
  -> DISPATCH
  -> EXECUTE
  -> VERIFY
  -> COMMIT
  -> PUBLISH
```

统一异常状态：

```text
REJECTED
WAITING
RETRYING
CANCELLED
FAILED
ROLLED_BACK
QUARANTINED
DEAD_LETTERED
DEGRADED
REQUIRES_RECONCILIATION
```

统一工作对象：

```text
WorkItem
WorkResult
StateTransition
ArtifactRef
EvidenceRef
```

模块可以拥有自己的业务阶段，但不能创建与 JHOC 冲突的私有状态、错误或取消语义。

## 5.1 插件化边界

所有可替换的业务能力均以 JHOC Plugin Protocol 接入，包括模型、RAG、Embedding、Reranker、执行 Skill、工具、感知适配器、输出适配器、社区 Worker 和评测器。插件不能直接访问其他模块的内部存储，必须通过原生契约和授权的服务端口工作。

以下属于可信核心，不作为 Capability Shelf 资产，也不允许模型或普通插件替换、提权或直接修改：

```text
Origin / Core / Contracts / Flow
Trust / Guard / State Store / Proof / Quota
Relay 的投递内核 / Gate 的验收内核
```

可信核心可以使用受控内部扩展点，但扩展点的实现、版本和权限仍由 JHOC 管理。模块之间只依赖契约、受控端口和 Relay，不允许反向调用对方内部实现。

## 6. JHOC Contracts

契约类型：

```text
Task
WorkItem
WorkResult
Command
Event
Query
ContextPackage
PolicyDecision
CapabilityRequest
PluginManifest
MemoryItem
KnowledgeItem
GraphRelation
EvidencePackage
AuditReceipt
UsageRecord
```

`WorkItem` 至少包含：

```text
work_id
work_type
schema_version
source
destination
task_id
parent_work_id
correlation_id
causation_id
priority
deadline
idempotency_key
input_ref
context_ref
policy_ref
state_version
created_at
```

所有大上下文、模型输出、社区内容和证据使用 `ArtifactRef`，避免在消息和日志中重复复制敏感数据。

### 6.1 Plugin Protocol

插件通过版本化原生协议接入，最小接口为：

```text
PluginManifest
Handshake
describe()
health()
initialize()
validate()
invoke()
stream()
cancel()
checkpoint()
drain()
shutdown()
```

`PluginManifest` 必须声明身份、版本、协议版本、插件类型、提供能力、依赖服务、数据访问范围、网络权限、外部副作用、资源需求、许可证、验证状态以及 `shelf_eligible`、`mutable_by_agent`。生命周期为：

```text
DISCOVER -> VERIFIED -> INSTALLED -> LOADED -> NEGOTIATED
-> INITIALIZED -> READY -> RUNNING -> DRAINING -> STOPPED
```

治理、审批、审计和验收插件属于控制面，固定为 `shelf_eligible=false`、`runtime_selectable=false`、`mutable_by_agent=false`。插件只能通过 JHOC 端口访问状态、存储、Relay、Guard 和 Quota，不能通过内部文件或后端接口绕过授权。

## 7. JHOC Relay

`JHOC Relay` 是全新 Agent Bus，不继承旧 Agent Bus 的实现或协议。

```text
Envelope Validator
Event Log
Command Queue
Router
Priority Scheduler
Lease Manager
ACK Manager
Retry Manager
Dead Letter Queue
Delivery State Coordinator
Replay Manager
Backpressure Controller
```

通道：

```text
control.*
task.*
handoff.*
review.*
community.*
memory.*
knowledge.*
evidence.*
evolution.*
telemetry.*
diagnostic.*
```

事件与命令分离。Relay 负责传输、投递和消息租约，不负责解释业务语义，也不拥有任务、记忆、知识或能力的业务状态。`Delivery State Coordinator` 只维护消息投递状态；业务状态由 JHOC 原生 State Store 和所属模块维护。

消息生命周期：

```text
CREATED -> VALIDATED -> ACCEPTED -> QUEUED -> LEASED -> RUNNING -> SUCCEEDED
```

可靠性模型：

```text
至少一次投递
+ 幂等执行
+ 租约
+ 去重键
+ 结果持久化
+ 有限重试
+ 取消和过期
+ 死信
+ 可重放
```

`model-space` 属于 JHOC Commons 的讨论归档，不是 Relay 队列。

## 8. JHOC Guard

JHOC Guard 是运行时治理平面。VERS 的有效治理语义经过离线转换后，形成 JHOC 原生策略包。

```text
PolicyRule
PolicyBundle
PolicyDecision
PolicyReceipt
PolicyConflict
ApprovalRequest
```

强制原则：

```text
默认拒绝
失败关闭
最小权限
敏感数据本地边界
高风险操作审批
规则版本和来源可追溯
模型不能改正式规则
外部内容不能升级为规则
```

Guard 负责是否允许；`JHOC Gate` 负责任务结果是否完成。两者不合并。

## 9. JHOC Trust 和安全

身份类型：

```text
User
Agent
Model
Plugin
Worker
Service
```

必须支持：

```text
认证
授权
权限委托
密钥轮换
权限撤销
会话隔离
身份冒用检测
```

安全专项：

```text
Prompt Injection Detection
Memory Poisoning Detection
Tool Result Sanitization
Instruction/Data Separation
Plugin Sandbox
Model/Plugin Supply Chain Verification
License Verification
Capability Revocation
```

Token、Cookie、API Key 和设备凭据不能进入普通知识、上下文、日志或长期记忆。

## 10. JHOC Atlas 和 JHOC Graph

### 10.1 知识管路

```text
RECEIVED
  -> QUARANTINED
  -> PARSED
  -> NORMALIZED
  -> CANDIDATE
  -> VERIFIED
  -> PUBLISHED
  -> EXPIRED / RETRACTED / ARCHIVED
```

知识类型：

```text
FACT
RULE_REFERENCE
PROJECT_KNOWLEDGE
USER_PREFERENCE
TASK_EXPERIENCE
ERROR_PATTERN
MODEL_CAPABILITY
COMMUNITY_CONCLUSION
OBSERVATION
HYPOTHESIS
PROCEDURE
EVIDENCE
```

### 10.2 图谱节点

```text
User
Project
Task
Agent
Model
Capability
Plugin
Skill
Tool
Document
CodeEntity
Memory
Rule
Evidence
Error
CommunityThread
Decision
Resource
Device
```

### 10.3 图谱关系

```text
related_to
derived_from
supports
contradicts
verified_by
used_by
depends_on
caused
solves
belongs_to
applies_to
supersedes
observed_in
produced_by
reviewed_by
requires
blocked_by
```

每条关系必须记录：

```text
relation_id
source_node
target_node
relation_type
confidence
source_ref
valid_time
verification_status
```

Atlas 管理知识内容和生命周期；Graph 管理实体关系投影。Graph 不拥有原始知识内容，避免与 Memory 和 Atlas 争夺数据所有权。

查询必须支持：

```text
关键词
向量
图谱遍历
时间
来源
可信度
项目范围
证据反查
混合检索
```

## 11. JHOC Memory 和 JHOC Proof

记忆类型：

```text
UserMemory
ProjectMemory
TaskMemory
ErrorMemory
ExperienceMemory
```

记忆写入：

```text
提议
  -> 分类
  -> 来源检查
  -> 敏感性检查
  -> 去重
  -> 冲突检测
  -> Memory Write Gate
  -> 版本提交
```

记忆保存长期可复用内容；Proof 保存任务、策略、能力和验收证据。两者不互相替代。

```text
模型观点 != 用户事实
社区共识 != 治理规则
历史记忆 != 当前状态
执行结果 != 验收证据
```

## 12. JHOC Registry、Shelf、Quota 和 Conductor

### 12.1 能力货架

可进入货架：

```text
Model
RAG
Embedding
Reranker
Execution Skill
Tool
Agent Bundle
```

能力必须声明：

```text
输入输出 Schema
数据访问范围
网络权限
外部副作用
风险等级
资源成本
支持意图
版本
许可证
验证状态
```

治理类 Skill、Policy Resolver、Approval、Audit 和 Gate 永不进入货架。

### 12.2 任务等级

```text
L0 普通对话
L1 知识和信息
L2 生产任务
L3 高风险协作
L4 系统和治理任务
```

任务性质：

```text
conversation
knowledge_qa
document_analysis
code_analysis
code_modification
multimodal_perception
desktop_operation
device_control
external_communication
system_change
governance_change
```

### 12.3 能力调配

```text
TaskProfile
  -> RiskProfile
  -> Guard PolicyDecision
  -> Conductor CapabilityPlan
  -> Registry/Shelf Filter
  -> Quota ResourcePlan and Lease
  -> Execute
  -> Monitor
  -> Upgrade/Degrade/Fallback
  -> Release
  -> Usage/Evidence
```

Registry 负责能力发现、元数据和验证状态；Shelf 负责可用能力资产及其版本/健康/可用性视图。Conductor 是货架运行时的唯一选择和编排入口，负责组合、排序、替换和释放能力，但不能突破 Quota 或 Guard。Registry 和 Shelf 不直接调度任务、不直接授予权限。

Quota 负责强制执行 CPU、GPU、内存、Token、并发、网络、时间、温度、功耗和电池限制，并包含 `Usage Accountant` 记录实际用量。

Conductor 可以为一个任务组合模型、RAG、Embedding、Reranker、Skill 和 Tool。模型或插件只能提交 `CapabilityRequest`，不能直接读取货架、切换模型、升档或提权；Conductor 必须在 Guard 的 `PolicyDecision` 和 Quota 的 `ResourcePlan/Lease` 约束内返回可解释的选择、拒绝或回退结果。

## 13. JHOC Context

JHOC Context 是专门的上下文编排器，不是旧 AIBOX Prompt 注入器。它分为两个明确阶段：

```text
Pass A 预判上下文：用户输入、触发元数据、任务范围和非敏感环境摘要
Pass B 完整上下文：仅在 Guard 授权、Conductor 形成 ResourcePlan 后激活允许的来源
```

Pass A 不读取屏幕图像、完整音频、敏感记忆或受限文件内容。敏感感知源的采集授权由 Guard 决定，Context 只执行已授权的来源激活；Context 的检索、排序和压缩不能扩大数据范围。

```text
Source Activation
  -> Normalize
  -> Classify
  -> Policy Filter (enforce Guard decision; no new authority)
  -> Memory/RAG/Graph Retrieve
  -> Rank
  -> Compress
  -> Budget
  -> Compose
  -> Snapshot
```

上下文来源：

```text
用户输入
硬件状态
桌面和应用
音频/视觉
情绪状态
用户画像
项目记忆
任务记忆
RAG
知识图谱
治理策略
能力描述
社区评审
执行证据
```

上下文类型：

```text
System Context
Policy Context
Task Context
User Context
Environment Context
Knowledge Context
Community Context
Evidence Context
```

Context 不直接选择最终模型、不执行工具、不授予权限、不直接写长期记忆。模型适配器只消费经过 Context 生成的 `ContextPackage`。`ContextPackage` 必须绑定 `policy_ref`、`resource_plan_ref`、来源清单和脱敏结果，保证模型看到的上下文可重建。

## 14. JHOC Runner 和 Gate

执行状态：

```text
NEW -> PLAN -> ACT -> OBSERVE -> VERIFY -> COMPLETION_PENDING -> COMPLETE
```

修复路径：

```text
VERIFY failed and repairable -> REPAIR -> ACT
scope unclear -> CLARIFY
safety/privacy/budget violation -> BLOCKED
optional dependency unavailable -> DEGRADED
```

外部副作用：

```text
SUCCEEDED
FAILED
PARTIAL
UNKNOWN_SIDE_EFFECT
REQUIRES_RECONCILIATION
```

Runner 管理执行和可修复循环，Gate 管理验收。Runner 只能把任务提交为 `COMPLETION_PENDING`；只有 Gate 在满足预期条件、执行结果、验证结果、副作用状态和证据引用后，才能提交业务状态 `COMPLETE`。Gate 拒绝时任务进入 `FAILED`、`REPAIR`、`BLOCKED` 或 `REQUIRES_RECONCILIATION`，不能由模型自行宣布完成。

## 14.1 JHOC Output

`JHOC Output` 是独立的输出适配层，只消费 Gate 已接受的 `EvidencePackage` 和 `WorkResult`，负责文本、语音、显示或其他用户通道的格式化、流式发送和设备呈现。输出插件不能绕过 Gate 发布未验收结果；Memory、Atlas、Graph、Commons 和 Forge 的写入属于独立的下游沉淀或异步工作，不得阻塞已验收结果的返回。

任务业务状态与输出投递状态必须分离：

```text
Task: COMPLETION_PENDING -> COMPLETE (owned by Gate)
Delivery: PENDING -> SENDING -> DELIVERED / FAILED / RETRYING (owned by Output)
```

Output 失败只重试幂等投递，不重新执行任务或外部副作用。只有用户明确要求重新运行时，才创建新的 `task_id`。

## 15. JHOC Commons 和 JHOC Idle

### 15.1 Commons

JHOC Commons 继承 AIBOX 模型社区自留地的功能目标：

```text
模型讨论
发帖和回帖
Agent 交接
同行评审
共识整理
模型能力反馈
经验交流
```

社区内容默认是：

```text
unverified collaborative evidence
```

不能自动成为：

```text
治理规则
用户事实
长期记忆
能力授权
货架资产
```

### 15.2 Idle

触发：

```text
任务完成
用户闲聊
系统空闲
定时维护
```

后台任务必须具备：

```text
低优先级
Token 配额
最大时长
最大并发
TTL
抢占
取消
检查点
恢复
```

前台任务到达时，Idle 必须停止或暂停后台社区任务，释放模型、GPU、Token 和工具资源。

社区和自进化任务必须经过：

```text
Eligible Evidence
  -> Guard/Privacy Redaction
  -> Idle Job
  -> Relay
  -> Quota Admission
  -> Commons/Forge Worker
```

它们不得从模型输出直接同步发帖、直接写入正式知识或直接发布进化候选。

## 16. JHOC Forge

自进化来源：

```text
任务轨迹
用户纠正
模型质量
工具失败
RAG 质量
能力选择
Token 和延迟
CPU/GPU/内存
社区评审
任务验收
```

自进化流水线：

```text
Experience Collector
  -> Pattern Miner
  -> Atlas/Graph Association
  -> Candidate Generator
  -> Replay Evaluator
  -> Regression Checker
  -> Policy/Security Check
  -> Approval
  -> Canary
  -> Monitor
  -> Promote/Rollback
```

候选状态：

```text
OBSERVED
CANDIDATE
EVALUATING
APPROVAL_REQUIRED
CANARY
PROMOTED
REJECTED
ROLLED_BACK
EXPIRED
```

可低风险调整模型排序、RAG 排序、上下文压缩、非关键重试和后台顺序。治理规则、权限、网络边界、货架准入、Agent Bus 核心协议和 Completion Gate 不得自动生效。

## 17. JHOC Lens

统一日志和反馈管路：

```text
组件/插件
  -> Log SDK
  -> Local Buffer
  -> Collector
  -> Validate/Normalize/Redact
  -> Trace Correlation
  -> Per-Module Routing
  -> Storage
  -> Health Analysis
  -> Diagnostic Feedback
  -> Recovery / Operator / Relay
```

日志、Trace、Metric、Event、Audit 和 Evidence 分离；逻辑统一收集，物理保留模块隔离。

每条日志必须能够关联：

```text
task_id
work_id
message_id
trace_id
component_id
module_id
plugin_id
policy_ref
capability_id
```

JHOC Lens 负责采集、关联和诊断；JHOC Proof 负责不可抵赖的审计和验收证据。

## 18. 存储、恢复和运行模式

JHOC 自有存储：

```text
Event Store
State Store
Artifact Store
Knowledge Store
Graph Store
Memory Store
Evidence Store
Audit Store
```

存储的物理后端可以统一部署，但逻辑所有权必须隔离：

| 存储 | 所有者 | 允许其他模块做什么 |
|---|---|---|
| Event Store | Relay | 通过事件查询和重放，不直接改事件 |
| State Store | Core 与各业务模块 | 通过版本化状态端口读写自己的状态 |
| Artifact Store | Core Storage | 通过 `ArtifactRef` 读写被授权对象 |
| Knowledge Store | Atlas | Graph 只能建立投影关系 |
| Graph Store | Graph | 只保存由 Atlas、Memory、Proof 等来源派生的关系投影 |
| Memory Store | Memory | Atlas、Graph 只能按契约引用，不直接改记忆 |
| Evidence/Audit Store | Proof | Lens 只能提交观测引用，不能改审计证据 |

任何模块不得通过共享文件、数据库表或后端管理接口绕过所属者修改其他模块的数据。

恢复顺序：

```text
身份和密钥
  -> 策略包
  -> 核心存储
  -> 能力注册和货架
  -> 记忆和图谱
  -> 证据和审计
  -> 后台任务
```

运行模式：

```text
ONLINE
LIMITED_NETWORK
OFFLINE
DEGRADED
EMERGENCY_SAFE_MODE
```

安全初始态和紧急模式都禁止高风险操作、外发和自进化发布。

## 19. 迁移和归档

`JHOC Ingest` 是一次性的离线工具，不属于运行时。

```text
旧系统只读快照
  -> 文件清单和 Hash
  -> 类型识别
  -> 内容/依赖/权威/敏感度分析
  -> 处置判定
  -> 目标对象映射
  -> 隔离区转换
  -> 完整性验证
  -> 结构验证
  -> 语义验证
  -> JHOC 正式导入
  -> 旧系统只读归档
```

处置状态：

```text
MIGRATE
TRANSFORM
REFERENCE_ONLY
ARCHIVE
QUARANTINE
REJECT
DUPLICATE
EXPIRED
```

迁移不得复制：

```text
旧运行时代码
旧权限和凭据
旧状态单例
旧消息协议
未验证模型和 Skill
无法确认来源的知识
```

## 20. 统一验收门槛

```text
G0 旧系统隔离
G1 原生契约
G2 插件协议
G3 Kernel/Storage
G4 Relay 可靠性
G5 Guard/Quota
G6 单模块
G7 端到端
G8 Commons/Idle
G9 安全/隐私/故障
G10 数据迁移
G11 独立运行
G12 正式切换
```

每个模块和插件必须验证：

```text
输入输出契约
状态迁移
权限边界
资源上限
超时
取消
重复调用
崩溃恢复
版本兼容
日志和 Trace
审计和 Evidence
升级、卸载和回滚
```

正式启用前必须满足：

```text
所有模块和插件为新实现
无旧运行时、数据库、目录和状态依赖
任务可暂停、恢复、取消和回滚
完成声明都有验证证据
只有 Gate 接受的结果才能进入 Output；输出投递失败不得重新执行任务副作用
后台任务不影响前台
社区内容不能越权
自进化候选可回放、审批、灰度和回滚
日志可重建完整任务链
备份恢复演练通过
无 P0/P1 缺陷
```

## 21. 设计一致性审查

| 检查项 | 结论 | 解决方式 |
|---|---|---|
| VERS 与 JHOC Guard | 无运行时冲突 | VERS 只经离线转换，Guard 只读 JHOC Policy Bundle |
| JHOC Memory 与 Atlas | 无数据所有权冲突 | Memory 管记忆，Atlas 管知识，按类型进入不同平面 |
| Atlas 与 Graph | 无所有权冲突 | Atlas 管内容和生命周期，Graph 管关系投影 |
| Relay 与 Commons | 无职责冲突 | Relay 管可靠传输，Commons 管讨论语义 |
| Relay 与 State Store | 无所有权冲突 | Relay 管消息租约，State Store 管业务状态 |
| Lens 与 Proof | 无职责冲突 | Lens 管观测诊断，Proof 管审计和验收证据 |
| Guard 与 Gate | 无管线冲突 | Guard 判断能否做，Gate 判断是否完成 |
| Gate、Proof 与 Output | 无管线冲突 | Gate 接受结果，Proof 固化证据，Output 只负责已接受结果的投递 |
| Conductor 与 Quota | 无控制冲突 | Conductor 选择能力，Quota 强制资源上限 |
| Context 与 Conductor | 无循环冲突 | 先最小上下文预判，后能力选择，再完整上下文编排 |
| Context 与 Guard | 无授权冲突 | Guard 决定来源权限，Context 只执行授权过滤和组装 |
| Runner 与 Relay | 无执行冲突 | Runner 执行业务步骤，Relay 负责投递和协调 |
| Output 与 Runner | 无副作用重跑冲突 | Output 只重试投递，Runner 不因输出失败重执行 |
| Commons 与 Forge | 无自动生效冲突 | Commons 提供证据，Forge 生成候选并评测 |
| Idle 与 Runner | 无前台冲突 | Idle 只创建低优先级任务，前台可抢占 |
| Migration 与独立性 | 无运行时冲突 | Ingest 只离线导入，运行时不保留旧适配器 |
| 插件化与可信内核 | 无边界冲突 | 业务能力插件化，身份、状态一致性、治理和审计保留在可信核心 |

审查结果：当前架构不存在阻断性职责矛盾。需要在实现阶段严格遵守以上边界，尤其不能将社区消息当成控制命令，不能让上下文编排器授予权限，也不能让自进化模块直接修改 Guard、Relay、Shelf 或 Gate。

## 22. 实施顺序

```text
P0 目标、SLO、威胁模型和旧系统冻结
P1 领域、信任、权限和数据边界
P2 原生对象、Schema 和错误码
P3 统一工作管路和状态机
P4 插件协议和一致性测试
P5 身份、密钥、配置和空系统启动
P6 Kernel、Storage 和 Lens
P7 Relay
P8 Guard
P9 Memory、Atlas、Graph、Proof
P10 Registry、Shelf、Quota
P11 Conductor 和 Adaptive Controller
P12 Context
P13 Runner、Gate 和 Output
P14 Commons
P15 Idle
P16 Forge 和 Bench
P17 Restore、Ops 和安全增强
P18 端到端、压力、隐私、权限和故障验证
P19 Ingest 离线迁移
P20 独立运行验收
P21 正式切换和旧系统封存
```

必须先冻结契约、工作管路、日志、身份和安全边界，才能进入大规模模块开发。

## 23. 文档优先级和冻结关系

```text
ARCHITECTURE.md
  定义架构边界、模块职责、数据所有权、管线方向和不可违反的设计原则

JHOC_BUILD_PLAN_V5.md
  定义构建阶段、阶段依赖、交付物、验收门槛和迁移/切换顺序

后续 Contract / Protocol / ADR 文档
  定义可执行 Schema、接口字段、错误码、时序、版本兼容和实现决策
```

发生冲突时，后续文档只能细化上层边界，不能改变本架构定义的所有权、授权方向、旧系统隔离和 Gate/Guard 分工；若确需改变，必须新增 ADR、更新本文件和构建计划，并重新执行全链路审查。
