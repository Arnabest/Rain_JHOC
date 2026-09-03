# JHOC 独立重构完整构建计划 V5

版本：V5
日期：2026-09-01
工作区：`G:\JHOC`
状态：概念设计基线，待拆解为实施任务

> JHOC 的所有运行时模块、组件、协议、状态和存储全部重新构建，与 AIBOX、VERS 和旧 Agent Bus 完全脱离。旧系统只作为离线迁移来源、历史依据和经验样本。

## 1. 建设目标

构建本地优先、插件化、可观测、可验证、可恢复、可自进化的 Agent Harness：

```text
输入
  -> 意图和风险分析
  -> 最小预判上下文
  -> 治理决策
  -> 能力与资源调配
  -> 已授权态势感知和完整上下文编排
  -> 模型/工具执行
  -> Agent 协作
  -> 验收和输出
  -> 记忆、证据、知识图谱
  -> 社区交流和受控自进化
```

## 2. 不可变约束

```text
JHOC 是唯一运行时系统
AIBOX/VERS 只提供离线历史资产，不参与运行
旧 Agent Bus 不参与运行，不提供兼容 API
不共享旧数据库、目录、状态文件和消息协议
不复用旧运行时代码
不与旧系统双写
所有模块使用 JHOC 原生契约和工作管路
治理规则类 Skill 永不进入 Capability Shelf
后台任务永远低于前台任务
自进化只能生成候选，不能直接改正式系统
```

## 3. 目标模块

```text
JHOC Origin       启动与安全初始态
JHOC Core         运行时内核
JHOC Contracts    原生领域和协议契约
JHOC Flow         统一工作管路
JHOC Trust        身份、信任和密钥
JHOC Config       配置、特性和版本
JHOC Relay        新 Agent Bus
JHOC Lens         日志、Trace、指标和诊断
JHOC Guard        治理运行时
JHOC Atlas        知识平面
JHOC Graph        知识图谱
JHOC Memory       记忆平面
JHOC Proof        证据和审计
JHOC Registry     能力注册中心
JHOC Shelf        能力货架
JHOC Quota        资源治理器
JHOC Conductor    能力编排器
JHOC Context      上下文编排器
JHOC Runner       执行运行时
JHOC Gate         验收门
JHOC Output       输出适配
JHOC Commons      模型社区自留地
JHOC Idle         后台自治调度器
JHOC Forge        自进化工坊
JHOC Bench        评测和基线
JHOC Restore      备份和恢复
JHOC Ingest       一次性离线迁移工具
JHOC Ops          运维和管理
```

输入、传感器、意图预测和风险分析属于 `Origin/Flow` 承载的插件类别，不是额外的可信数据所有者。它们只能提供带来源和置信度的观测或分析结果；任务等级、权限和最终风险判定仍由 JHOC Core/Guard 依据契约确定。

## 4. 统一工作管路

所有组件和插件必须映射到：

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
REJECTED / WAITING / RETRYING / CANCELLED / FAILED
ROLLED_BACK / QUARANTINED / DEAD_LETTERED / DEGRADED
REQUIRES_RECONCILIATION
```

统一对象：

```text
WorkItem
WorkResult
StateTransition
ArtifactRef
EvidenceRef
```

## 5. 原生协议和插件规范

### 5.1 协议族

```text
Task、Work、Command、Event、Query、Context、Policy
Capability、Plugin、Memory、Knowledge、Graph、Evidence
Audit、Usage
```

### 5.2 Plugin Protocol

插件必须提供：

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

插件必须声明：

```text
身份、版本、协议版本、插件类型、提供能力、依赖服务
数据访问范围、网络权限、副作用、资源需求、许可证、验证状态
shelf_eligible、mutable_by_agent
```

生命周期：

```text
DISCOVER -> VERIFIED -> INSTALLED -> LOADED -> NEGOTIATED
-> INITIALIZED -> READY -> RUNNING -> DRAINING -> STOPPED
```

治理插件属于控制面，固定为：

```text
shelf_eligible = false
runtime_selectable = false
mutable_by_agent = false
```

## 6. Agent Bus：JHOC Relay

### 核心组件

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

`Delivery State Coordinator` 只维护消息投递状态；任务、知识、记忆、能力和证据的业务状态分别由 JHOC 原生 State Store 及所属模块维护。Artifact Store 是 JHOC 的共享受控存储服务，不属于 Relay 的业务所有权。

### 通道

```text
control.* task.* handoff.* review.* community.* memory.*
knowledge.* evidence.* evolution.* telemetry.* diagnostic.*
```

### 可靠性规则

```text
至少一次投递
幂等执行
租约和过期
有限重试和退避
结果持久化
过期处理
死信
取消
背压
事件重放
```

事件和命令分离；`model-space` 只属于 Commons 的讨论归档，不承担可靠队列职责。

## 7. Governance、Identity 和安全

### JHOC Guard

```text
PolicyRule
PolicyBundle
PolicyDecision
PolicyReceipt
PolicyConflict
ApprovalRequest
```

强制规则：

```text
默认拒绝
失败关闭
最小权限
高风险操作审批
敏感数据本地边界
规则版本和来源可追溯
模型不能改正式规则
```

### JHOC Trust

身份类型：

```text
User / Agent / Model / Plugin / Worker / Service
```

必须支持：

```text
认证、授权、权限委托、密钥轮换、撤销、会话隔离、身份冒用检测
```

不得把 Token、Cookie、API Key 或设备凭据复制到普通数据、Prompt 或日志中。

## 8. Knowledge、Graph、Memory 和 Proof

### Knowledge 入口和生命周期

```text
RECEIVED -> QUARANTINED -> PARSED -> NORMALIZED -> CANDIDATE
-> VERIFIED -> PUBLISHED -> EXPIRED / RETRACTED / ARCHIVED
```

知识类型：

```text
FACT / RULE_REFERENCE / PROJECT_KNOWLEDGE / USER_PREFERENCE
TASK_EXPERIENCE / ERROR_PATTERN / MODEL_CAPABILITY
COMMUNITY_CONCLUSION / OBSERVATION / HYPOTHESIS / PROCEDURE / EVIDENCE
```

### 图谱

节点包括：

```text
User、Project、Task、Agent、Model、Capability、Plugin、Skill、Tool
Document、CodeEntity、Memory、Rule、Evidence、Error、Thread、Decision、Device
```

关系包括：

```text
related_to、derived_from、supports、contradicts、verified_by、used_by
depends_on、caused、solves、belongs_to、applies_to、supersedes
observed_in、produced_by、reviewed_by、requires、blocked_by
```

### 查询

```text
Policy Filter
  -> Scope Filter
  -> Keyword Retrieval
  -> Vector Retrieval
  -> Graph Traversal
  -> Time/Source Filter
  -> Deduplication
  -> Conflict Detection
  -> Ranking
  -> Provenance Package
```

### Memory

```text
UserMemory / ProjectMemory / TaskMemory / ErrorMemory / ExperienceMemory
```

记忆写入必须经过：

```text
分类 -> 来源检查 -> 敏感性检查 -> 去重 -> 冲突检测 -> Write Gate -> 版本提交
```

## 9. Capability 和资源调配

### 能力货架

可进入：

```text
Model / RAG / Embedding / Reranker / Execution Skill / Tool / Agent Bundle
```

能力必须声明：

```text
输入输出 Schema、数据访问、网络权限、副作用、风险等级
资源成本、支持意图、版本、许可证、验证状态
```

### 任务和资源画像

任务等级：

```text
L0 普通对话
L1 知识和信息
L2 生产任务
L3 高风险协作
L4 系统和治理任务
```

任务性质：

```text
conversation / knowledge_qa / document_analysis / code_analysis
code_modification / multimodal_perception / desktop_operation
device_control / external_communication / system_change / governance_change
```

调配闭环：

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

Registry 负责能力发现、元数据和验证状态；Shelf 负责可用能力资产及其版本、健康和可用性视图。Conductor 是货架运行时的唯一选择和编排入口，Registry 和 Shelf 不直接调度任务、不直接授予权限。模型或插件只能提交 `CapabilityRequest`，不能直接读取货架、切换模型、升档或提权；Conductor 必须在 Guard 的 `PolicyDecision` 和 Quota 的 `ResourcePlan/Lease` 约束内返回可解释的选择、拒绝或回退结果。

## 10. Context、Runner 和 Gate

### Context Orchestrator

上下文采用两阶段编排：

```text
Pass A 预判上下文：用户输入、触发元数据、任务范围和非敏感环境摘要
  -> Intent/Risk Analysis
  -> Guard 决定敏感来源是否可激活
Pass B 完整上下文：仅组装已授权的感知、记忆、RAG、图谱、能力和证据来源
```

Pass A 不读取屏幕图像、完整音频、敏感记忆或受限文件内容。Pass B 的 `Policy Filter` 只执行 Guard 已返回的授权结果，不产生新的权限。Context 不能授予权限，Conductor 也不能绕过 Guard 或 Quota。

```text
Source Activation
  -> Normalize
  -> Classify
  -> Policy Filter
  -> Memory/RAG/Graph Retrieve
  -> Rank
  -> Compress
  -> Budget
  -> Compose
  -> Snapshot
```

上下文必须带有来源、可信度、敏感级别、有效期、允许消费者和溯源信息。

### Execution Runtime

```text
NEW -> PLAN -> ACT -> OBSERVE -> VERIFY -> COMPLETION_PENDING -> COMPLETE
```

修复分支：

```text
REPAIR -> ACT
CLARIFY
BLOCKED
DEGRADED
```

外部副作用必须区分：

```text
SUCCEEDED / FAILED / PARTIAL / UNKNOWN_SIDE_EFFECT
REQUIRES_RECONCILIATION
```

### Completion Gate

完成必须有：

```text
预期条件
执行结果
验证结果
副作用状态
证据引用
策略版本
能力版本
```

Runner 只能提交 `COMPLETION_PENDING`；Gate 验收通过后才能进入 `COMPLETE`。Gate 拒绝时必须进入修复、阻断或副作用对账路径，不能由模型自行宣布完成。

### JHOC Output

Output 只接收 Gate 已接受的 `EvidencePackage` 和 `WorkResult`，负责文本、语音、显示或其他用户通道的格式化和发送。输出适配器不能绕过 Gate 发布未验收结果；Memory、Atlas、Graph、Commons 和 Forge 属于独立的下游沉淀或异步工作。

任务状态 `COMPLETE` 由 Gate 拥有；Output 独立维护 `PENDING / SENDING / DELIVERED / FAILED / RETRYING`。输出失败只能幂等重试投递，不能重新执行任务或外部副作用。

## 11. Commons、Idle 和 Forge

### JHOC Commons

继承 AIBOX 模型社区自留地的语义：

```text
讨论、发帖、回帖、任务交接、同行评审、共识整理、模型反馈
```

社区观点不自动成为：

```text
规则、事实、长期记忆、能力授权、货架资产
```

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

### JHOC Idle

触发：

```text
任务完成
用户闲聊
系统空闲
定时维护
```

后台必须具备：

```text
低优先级、Token 配额、最大时长、最大并发、TTL、抢占、取消、检查点、恢复
```

### JHOC Forge

```text
经验采集
  -> 模式发现
  -> 知识/图谱关联
  -> 候选生成
  -> 历史回放
  -> 回归检查
  -> 策略和安全检查
  -> 审批
  -> 灰度
  -> 监控
  -> 晋级或回滚
```

可低风险调整模型排序、RAG 排序、上下文压缩和非关键重试；治理规则、权限、核心协议和验收门槛不得自动生效。

## 12. 可观测性和反馈

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
  -> Recovery / Operator / Agent Bus
```

日志、Trace、Metric、Event、Audit、Evidence 分离；逻辑统一收集，物理保留模块隔离。

必须通过 `task_id` 重建任务链，通过 `work_id` 定位组件调用，通过 `policy_ref` 解释治理决策。

## 13. 可靠性、硬件和恢复

必须处理：

```text
时间和因果
并发和版本
幂等和副作用
模型/插件崩溃
队列堆积
网络不可用
CPU/GPU/内存不足
温度、功耗和电池限制
音频、摄像头和外设占用
```

运行模式：

```text
ONLINE / LIMITED_NETWORK / OFFLINE / DEGRADED / EMERGENCY_SAFE_MODE
```

恢复顺序：

```text
身份和密钥
  -> 策略包
  -> 存储
  -> 能力注册和货架
  -> 记忆和图谱
  -> 证据和审计
  -> 后台任务
```

## 14. 详细阶段计划

| 阶段 | 任务 | 交付物 | 通过门槛 |
|---|---|---|---|
| P0 | 目标、SLO、威胁模型和旧系统冻结 | ADR、SLO、只读快照 | 旧系统停止运行时变更 |
| P1 | 领域、信任、权限和数据边界 | Domain Map、Trust Boundary | 无职责和权限重叠 |
| P2 | 原生对象和 Schema | JHOC Contracts | 契约可校验、可版本化 |
| P3 | 统一工作管路和状态机 | JHOC Flow | 所有组件有统一状态语义 |
| P4 | 插件协议和一致性测试 | Plugin Protocol、Conformance Tests | 插件可验证、加载、调用、卸载 |
| P5 | 身份、密钥、配置和空系统启动 | Trust、Config、Origin | 无模型、无记忆时仍安全启动 |
| P6 | Kernel、存储和可观测性 | Core、Storage、Lens | 断开旧系统可独立运行 |
| P7 | Agent Bus V2 | Relay | 重复、乱序、崩溃、背压可恢复 |
| P8 | 治理运行时 | Guard、Policy Bundle | 默认拒绝、失败关闭、可审计 |
| P9 | Memory、Knowledge、Graph、Proof | Atlas、Graph、Memory、Proof | 来源、版本、敏感级别完整 |
| P10 | Capability Registry、Shelf、Quota | Registry、Shelf、Quota | 能力验证和资源限制有效 |
| P11 | Capability Orchestrator | Conductor、Adaptive Controller | 选择、拒绝、回退可解释 |
| P12 | Context Orchestrator | Context、Snapshot、Delta | 上下文可追溯、可裁剪、可脱敏 |
| P13 | Execution、Verification 和 Output | Runner、Gate、Output | 任务状态和副作用可恢复；仅验收结果可输出 |
| P14 | Community Plane | Commons、Handoff、Review | 社区消息不能越权 |
| P15 | Background Runtime | Idle、抢占和恢复 | 后台不影响前台 |
| P16 | Evolution 和 Evaluation | Forge、Bench、Canary | 候选有回放、审批和回滚 |
| P17 | 安全、灾备和运维 | Restore、Ops、Runbook | 故障可恢复，操作可追踪 |
| P18 | 端到端和故障验证 | E2E、压力、隐私、权限矩阵 | 无 P0/P1 缺陷 |
| P19 | 离线资产迁移 | Ingest、Migration Manifest | 不修改旧数据，不产生旧依赖 |
| P20 | 独立运行验收 | Independence Report | 断开 AIBOX/VERS/旧 Bus 仍可工作 |
| P21 | 正式切换和封存 | Cutover、Archive Manifest | JHOC 成为唯一运行时入口 |

## 15. 离线迁移规范

### 15.1 迁移流程

```text
旧系统只读快照
  -> 文件清单和 Hash
  -> 类型识别
  -> 内容、依赖、权威、敏感度分析
  -> 处置判定
  -> 目标对象映射
  -> 隔离区转换
  -> 完整性验证
  -> 结构验证
  -> 语义验证
  -> JHOC 正式导入
  -> 旧系统只读归档
```

### 15.2 处置状态

```text
MIGRATE / TRANSFORM / REFERENCE_ONLY / ARCHIVE
QUARANTINE / REJECT / DUPLICATE / EXPIRED
```

### 15.3 迁移对象

```text
AIBOX Memory -> JHOC Memory
AIBOX Knowledge -> JHOC Atlas/Graph
AIBOX model-space -> JHOC Commons Archive
AIBOX tasks -> JHOC Task History
AIBOX op-log -> JHOC Proof/Audit Archive
VERS Rules -> JHOC PolicyRule/PolicyBundle
旧代码和脚本 -> REFERENCE_ONLY
凭据和权限 -> 不复制，重新建立
```

## 16. 总体验收

JHOC 正式启用前必须满足：

```text
所有模块和插件为新实现
所有接口使用 JHOC 原生协议
无旧系统运行时、数据库、目录和状态依赖
Relay 支持幂等、租约、取消、重试、死信和重放
Guard 默认拒绝且失败关闭
Quota 能强制限制资源和硬件状态
Conductor 的选择、拒绝和回退可解释
Context 可追溯、可脱敏、可重建
Atlas/Graph/Memory 生命周期和关系质量完整
Runner 状态和副作用可恢复
Gate 以证据判断完成
只有 Gate 接受的结果才能进入 Output；输出投递失败不得重新执行任务副作用
Commons 内容不能越权
Idle 任务不能影响前台
Forge 候选不能绕过评测、审批、灰度和回滚
Lens 能重建完整任务链路
Restore 恢复演练通过
迁移来源、Hash、版本和语义验证完整
无 P0/P1 缺陷
```

## 17. 第一批实施任务

```text
1. 冻结本计划和架构决策
2. 建立 JHOC Contracts、Schema 和错误码
3. 定义 WorkItem、WorkResult、MessageEnvelope、PluginManifest
4. 定义状态机、重试、取消、幂等和副作用语义
5. 定义 Log、Trace、Audit、Evidence 对象
6. 定义身份、权限、秘密和 ResourcePlan
7. 设计 Core、Relay、Guard 的最小接口
8. 建立插件一致性和故障注入测试框架
9. 建立空系统安全启动测试
10. 建立离线迁移 Manifest，不接入旧系统运行时
11. 确定 P0 的延迟、资源、可靠性和质量基线
```

## 18. 最终建设原则

```text
先边界，再契约
先契约，再内核
先观测，再业务
先治理，再执行
先状态，再智能行为
先验证新系统，再迁移历史数据
先独立验收，再封存旧体系
```

## 19. 文档优先级和变更规则

```text
ARCHITECTURE.md
  架构边界、模块职责、数据所有权、管线方向和不可违反的设计原则

JHOC_BUILD_PLAN_V5.md
  构建阶段、阶段依赖、交付物、验收门槛和迁移/切换顺序

后续 Contract / Protocol / ADR 文档
  可执行 Schema、接口字段、错误码、时序、版本兼容和实现决策
```

后续协议或实现文档只能细化上层架构，不能改变 JHOC 独立运行、Guard/Quota 强制边界、Relay/State Store 所有权、Gate 验收责任或旧系统离线迁移规则。改变这些边界必须新增 ADR、同步更新架构与计划，并重新执行全链路审查。
