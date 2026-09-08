# 历程全景索引：跨项目开发路线图与各开发周技术复盘博客 (2026-06-03 ~ 2026-09-05)

> **权威定位**: 记录从最初的代码探索到当前多智能体治理中枢演进的完整历史脉络。
> **核心规范**: 严格执行 Rule 7 零 Emoji 纯净纪律，基于单机真实代码提交、会话记录、日志与测试事实撰写。
> **全景周期**: 跨越 4 个核心大项目、共 15 个开发周、包含 9,770 个血缘节点与 9,790 条依赖关系。

---

## 全景时间轴与项目域划分

```
[2026-06-03] --------------------------------------------------------------------> [2026-09-05]
  |
  +-- 项目 1: QQMusicOverlayNG (桌面音频渲染与系统媒体监控) [Week 01 ~ Week 05]
  |     |-- W01 (06-03 ~ 06-09): 脚手架搭建、归档解包与格式解析
  |     |-- W02 (06-10 ~ 06-16): Windows SMTC 媒体会话捕获与毫秒歌词同步
  |     |-- W03 (06-17 ~ 06-23): OpenGL 硬件加速透明穿透悬浮窗与文字抗锯齿
  |     |-- W04 (06-24 ~ 06-30): COM Apartment 崩溃熔断与 96FPS 高刷丢帧攻坚
  |     +-- W05 (07-01 ~ 07-08): 系统托盘常驻、单例互斥锁与开机自启
  |
  +-- 项目 2: AI Box & Desktop Agent (多模态桌面智能体中枢) [Week 06 ~ Week 11]
  |     |-- W06 (07-09 ~ 07-15): 智能体架构立项、宿主进程通信与遥测总线
  |     |-- W07 (07-16 ~ 07-22): Codex CLI 与 Claude Code 双引擎物理编排
  |     |-- W08 (07-23 ~ 07-29): Memory Administrator 三级记忆与分层索引
  |     |-- W09 (07-30 ~ 08-05): 实时语音交互、LaTeX TTS 乱码防护与 AEC 自激回声消除
  |     |-- W10 (08-06 ~ 08-12): Agentic Skill 货架体系与插件沙箱安全机制
  |     +-- W11 (08-13 ~ 08-16): 长上下文溢出熔断与记忆无损蒸馏压缩
  |
  +-- 项目 3: VERS (语义规则引擎与前端工作流) [Week 12 ~ Week 14]
  |     |-- W12 (08-17 ~ 08-23): 规则驱动架构立项与 1,382 条规则爆炸危机
  |     |-- W13 (08-24 ~ 08-29): 前后端交互分离与搜索框对齐交互故障复盘
  |     +-- W14 (08-30 ~ 08-31): 规则死锁、玄学包装反思与单机最小实证觉醒
  |
  +-- 项目 4: JHOC (联合混合行动中心 - Joint Hybrid Operations Center) [Week 15]
        +-- W15 (09-01 ~ 09-05): JHOC 极简自持微内核、六大铁律、全量血缘图谱与 36 协审
```

---

## 详细博客目录导航

### 项目 1: QQMusicOverlayNG (桌面音频渲染与系统媒体监控)
- **Week 01 (2026-06-03 ~ 2026-06-09)**: [脚手架搭建与音频文件归档解包](docs/worklogs/qqmusic-overlay/week-01-scaffolding-and-archive-pipeline.md)
  - 核心突破: 首个 VS Code 原生会话落地，实现 `.qmflac` 音频容器头校验与高效流式提取。
- **Week 02 (2026-06-10 ~ 2026-06-16)**: [Windows SMTC 媒体会话捕获与歌词毫秒同步](docs/worklogs/qqmusic-overlay/week-02-smtc-media-session-and-lyric-sync.md)
  - 核心突破: 接入 WinRT `GlobalSystemMediaTransportControlsSessionManager`，双向动态时钟校准。
- **Week 03 (2026-06-17 ~ 2026-06-23)**: [OpenGL 硬件加速透明穿透悬浮窗设计](docs/worklogs/qqmusic-overlay/week-03-opengl-transparent-overlay.md)
  - 核心突破: Windows 分层窗口 `WS_EX_LAYERED` 与 OpenGL FBO 逐像素 Alpha 混合融合。
- **Week 04 (2026-06-24 ~ 2026-06-30)**: [COM Apartment 线程模型死锁与 96FPS 高刷卡顿治理](docs/worklogs/qqmusic-overlay/week-04-smtc-crash-and-96fps-stutter.md)
  - 核心突破: STA/MTA 跨线程调度崩溃修复，GLFW 双缓冲与垂直同步自适应步长算法。
- **Week 05 (2026-07-01 ~ 2026-07-08)**: [系统托盘常驻、单例互斥与进程自愈](docs/worklogs/qqmusic-overlay/week-05-tray-persistence-and-automation.md)
  - 核心突破: `CreateMutexW` 防多开，`pystray` 托盘右键菜单与异常静默热重启。

---

### 项目 2: AI Box & Desktop Agent (多模态桌面智能体中枢)
- **Week 06 (2026-07-09 ~ 2026-07-15)**: [桌面智能体立项与宿主进程遥测总线](docs/worklogs/aibox-desktop-agent/week-06-desktop-agent-architecture.md)
  - 核心突破: 基于 JSON Lines 的本地遥测总线 `activity_*.jsonl`，双向非阻塞命名管道。
- **Week 07 (2026-07-16 ~ 2026-07-22)**: [OpenAI Codex CLI 与 Claude Code 双引擎物理编排](docs/worklogs/aibox-desktop-agent/week-07-codex-cli-integration-and-dual-engine.md)
  - 核心突破: 子进程隔离调用本地 CLI，解除外部网络强依赖，实现多模型对抗复核。
- **Week 08 (2026-07-23 ~ 2026-07-29)**: [Memory Administrator 三级记忆治理体系](docs/worklogs/aibox-desktop-agent/week-08-memory-governance-and-tri-tier-cache.md)
  - 核心突破: L1 进程缓存、L2 任务短期记忆与 L3 持久经验库无损归并。
- **Week 09 (2026-07-30 ~ 2026-08-05)**: [多模态语音交互、LaTeX 乱码防护与 AEC 回声消除](docs/worklogs/aibox-desktop-agent/week-09-stt-tts-pipeline-and-aec-echo-cancellation.md)
  - 核心突破: 语音发音文本沙箱清洗，Agent 自发声特征哈希识别与双工物理打断。
- **Week 10 (2026-08-06 ~ 2026-08-12)**: [Agentic Skill 货架标准与安全沙箱](docs/worklogs/aibox-desktop-agent/week-10-agentic-skill-shelf-and-tool-registry.md)
  - 核心突破: 声明式技能清单 `SHELF.md`，AST 静态审计与高危原语硬拦截。
- **Week 11 (2026-08-13 ~ 2026-08-16)**: [长上下文溢出物理熔断与结构化会话无损蒸馏](docs/worklogs/aibox-desktop-agent/week-11-context-overflow-and-memory-compaction.md)
  - 核心突破: 80% Token 阈值提前预警，任务流转上下文自动折叠与五元组链表存盘。

---

### 项目 3: VERS (语义规则引擎与前端工作流)
- **Week 12 (2026-08-17 ~ 2026-08-23)**: [规则驱动架构初探与 1,382 条规则爆炸困境](docs/worklogs/verse/week-12-rule-engine-and-1382-rules-explosion.md)
  - 核心突破: 揭示规则过度细分导致的语义冲突与上下文爆炸，建立规则优先级分级树。
- **Week 13 (2026-08-24 ~ 2026-08-29)**: [前后端交互解耦与搜索框焦点错位故障排查](docs/worklogs/verse/week-13-verse-frontend-backend-and-search-box-bug.md)
  - 核心突破: CSS 绝对定位穿透与 DOM 焦点竞争根因攻克，真实还原用户端交互修复。
- **Week 14 (2026-08-30 ~ 08-31)**: [规则死锁破局：去学术包装与实证闭环觉醒](docs/worklogs/verse/week-14-governance-deadlock-and-anti-metaphysical-awakening.md)
  - 核心突破: 痛定思痛摒弃玄学包装，提出验证优先于声明，确立单机最小闭环基准。

---

### 项目 4: JHOC (联合混合行动中心 - Joint Hybrid Operations Center)
- **Week 15 (2026-09-01 ~ 2026-09-05)**: [JHOC 极简自持微内核、六大铁律与 9,770 节点全量血缘图谱](docs/worklogs/jhoc/week-15-jhoc-bootstrap-six-invariants-and-lineage-graph.md)
  - 核心突破: 59 次 Git 提交筑基，P19 SQLite WAL 黑匣子，36 多模型协审，全量关系图谱 Graph-RAG。

---

## 质量与规范声明
1. **真实性原则**: 所有代码 Diff、配置段落与单测结果均来自物理磁盘存在的真实文件；
2. **纯净性原则**: 遵循 Rule 7，全景索引与所有周报博客 100% 杜绝 Emoji 表情符号，纯 ASCII 与通用文本排版；
3. **结构化原则**: 每篇周报严格遵循 7 段式架构（背景、诱因、机理、曲折、终局与 Diff、启示、度量）。
