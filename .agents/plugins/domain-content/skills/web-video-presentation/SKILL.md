---
name: web-video-presentation
canonical_id: web-video-presentation
aliases: ["web-video", "制作视频", "文章转视频", "网页视频演示", "知识讲解视频", "web-video-presentation"]
description: "基于 Harness 驾驭工程的知识讲解视频全自动制作套件 — 将技术长文/深度文章经由四阶段两检查点，编译为高度可控、音画对齐、支持全自动播放与录屏的现代化 Web 动态演示系统。内建 23 套工业级设计主题与 narrations.ts 唯一事实源步数硬契约。"
version: 1.1.0
category: multimodal
trigger: ["web-video-presentation", "web-video", "制作视频", "文章转视频", "网页视频演示", "知识讲解视频"]
when_to_use: ["需要将 Markdown/技术长文全流程转为精美动效讲解视频", "制作高可控性、无黑盒抽卡、结构透明的网页演示课件", "需要音画天然对齐且支持逐帧微调的自动化内容生产", "将口播稿转化为支持全自动/键盘控制的 16:9 网页演示项目"]
mutable_by_agent: false
skill_tier: domain
---

# Web Video Presentation 技能 (Harness 知识讲解视频生成引擎)

> **Authority**: Governed under **JHOC Agent 宪法体系** ([`g:\JHOC\AGENTS.md`](file:///g:/JHOC/AGENTS.md)) 与 [`ADR-0009-registry-shelf-quota.md`](file:///g:/JHOC/docs/adr/ADR-0009-registry-shelf-quota.md)
> **Physical Location**: `g:\JHOC\.agents\skills\web-video-presentation\`
> **Design Pattern**: 确定性前端状态机驱动，拒绝黑盒抽卡，坚持两阶段人工检查点与步数恒等式。

---

## 1. 核心设计原则与 Harness 铁律

1. **确定性重于黑盒生成**：
   - 严禁调用不可控的黑盒视频生成大模型。
   - 全片通过 Vite + React + TypeScript + CSS 状态机实现，保证字体、调色板、停顿毫秒、图表架构具备绝对可控性与热修改能力。
2. **唯一事实源步数契约 (`narrations.ts` Invariant)**：
   - 每个章节的 `narrations.ts` 是口播文本与步数的唯一事实源。
   - **硬性数学恒等式**：章节 `.tsx` 代码中 `if (step === N)` 出现的最大值 $N$ 必须满足：
     $$\max(N) + 1 \equiv \text{narrations.length}$$
   - 绝对杜绝大纲、章节代码、路由表与音频文件之间的步数脱节与音画漂移。
3. **大纲只锁信息池，不锁动画**：
   - `outline.md` 只负责规划**章节切分、口播节拍 (Beat) 与信息密度**，严禁在大纲阶段规划具体 CSS 动效（如从左滑入、弹跳等）。
   - 动效必须在章节开发阶段，对照 [references/CHAPTER-CRAFT.md](references/CHAPTER-CRAFT.md) 的“反 AI 感手艺法则”现场设计，赋予页面空间呼吸感与动态张力。
4. **两阶段人工检查点 (Human Checkpoints)**：
   - 严禁全流程全自动盲跑交付。
   - **[检查点 1 (Plan)]**：阶段一完成产出大纲后，必须停下来交由人工确认文案风味、23 套主题选型与开发模式。
   - **[检查点 2 (Audio)]**：阶段二完成第 1 章后必须强制单独由人工在浏览器点检验收，确立全片视觉基准；全片合成后确认配音需求。
5. **反馈修复的最小切片原则**：
   - 严禁在收到排版或节奏调整反馈时盲目推倒重做整章。
   - 严格将问题归因至 [节奏 / 视觉 / 内容 / 代码] 四层之一，只对最小代码切片执行定向修补。

---

## 2. 状态机执行时序图 (四阶段与两检查点)

```text
[原始输入 article.md]
        |
   [阶段一: Phase 1] 内容规划与大纲拆解
        |-- 1.1 识别输入与技术要点
        `-- 1.2 一次产出 script.md (口播稿) + outline.md (开发计划)
        |
   [检查点 1: Checkpoint Plan] 人工阻断对齐 5 件事:
        |-- 1. 稿子 (去AI味/口语短句)
        |-- 2. outline (节拍步数合理性)
        |-- 3. 主题 (从内置 23 套 themes/ 中选择或定制)
        |-- 4. 素材准备 (纯代码矢量绘制 / 外部图片占位)
        `-- 5. 开发模式 (串行控费模式 / 并行高速模式)
        |
   [阶段二: Phase 2] 网页脚手架与逐章开发
        |-- 2.1 基于 templates/ 与选定主题构建脚手架
        |-- 2.2 第 1 章先行开发 -> 人工浏览器点检验收 [硬节点: 确立视觉基准]
        `-- 2.3 后续章节开发 (按选定模式) -> Review 交叉自检
        |
   [检查点 2: Checkpoint Audio] 全片连贯性走查，决策是否自动合成配音
        |
   [阶段三: Phase 3] 音频工程批量合成 (可选)
        |-- 提取 narrations.ts -> audio-segments.json
        `-- 调用 MiniMax CLI / OpenAI / edge-tts 批量幂等生成
        |
   [阶段四: Phase 4] 全屏播放与录屏交付
        `-- 提供手动模式 (/)、音频辅助模式 (/?audio=1)、全自动成片模式 (/?auto=1)
```

---

## 3. 标准项目工作区目录结构

```text
my-video-project/
├── article.md                     # 原文输入 (开发阶段补充技术密度的事实源，不删)
├── script.md                      # 平台化口播稿 (决定讲解节拍与短句节奏)
├── outline.md                     # 开发大纲 (章节切分 + 每步内容 + 信息池，不写具体动效)
├── lessons_learned.md             # 动态防坑自愈日志 (记录人工微调原因与解法)
└── presentation/                  # 基于 templates/ 生成的 Vite + React + TS 演示工程
    ├── src/
    │   ├── styles/
    │   │   ├── tokens.css         # 从 themes/<name>/tokens.css 复制的调色板与排版变量
    │   │   └── global.css
    │   └── chapters/
    │       ├── 01-intro/
    │       │   ├── Intro.tsx      # 视觉实现
    │       │   ├── Intro.css      # 独立类名命名空间 (.ch01-xxx)
    │       │   └── narrations.ts  # 唯一事实源: 步数与口播映射
    │       └── ...
    ├── scripts/
    │   ├── extract-narrations.ts   # 扫描所有 narrations.ts -> audio-segments.json
    │   ├── synthesize-audio.sh     # Bash 音频合成器 (MiniMax / OpenAI 等)
    │   └── tts-providers/          # TTS 提供商适配层
    └── public/
        └── audio/<chapter>/<N>.mp3 # 合成的分段音频文件
```

---

## 4. 资产库资源索引

本技能内置了完备的工业级工程参考、设计主题与脚手架模板，位于技能子目录下：

### 4.1 核心参考规约 ([references/](references/))
- [SCRIPT-STYLE.md](references/SCRIPT-STYLE.md)：口播稿三层自检（形式、风骨、念出来口语化）。
- [OUTLINE-FORMAT.md](references/OUTLINE-FORMAT.md)：细粒度大纲规范、信息池与步骤划分指南。
- [CHAPTER-CRAFT.md](references/CHAPTER-CRAFT.md)：章节视觉工艺、反 AI 廉价感手艺法则与排版动效。
- [THEMES.md](references/THEMES.md)：23 套主题风格导览与视觉气质搭配表。
- [AUDIO.md](references/AUDIO.md)：音频合成规范、停顿气口控制与标点符号映射。
- [RECORDING.md](references/RECORDING.md)：Screen Studio / OBS 录屏设置与视频交付标准。

### 4.2 内置 23 套工业级设计主题 ([themes/](themes/))
开发时可根据内容题材直接从以下主题引入 `tokens.css`：

| 主题分类 | 主题目录名称 | 视觉气质与推荐场景 |
| :--- | :--- | :--- |
| **现代科技/暗色** | `midnight-press` | 科技暗蓝底，专业硬核，架构讲解最佳默认选型 |
| | `electric-studio` | 霓虹紫/电光蓝高对比度，适合前沿 AI/Web3 演示 |
| | `neon-cyber` | 赛博暗夜霓虹，高视觉冲击力 |
| | `terminal-green` | 极客终端黑绿，底层内核/CLI/Linux 专题首选 |
| **经典学术/出版** | `swiss-ikb` | 瑞士国际主义排版，克莱因蓝 + 极端理性格栅 |
| | `blueprint` | 经典工程蓝图白线，系统设计与硬件架构标配 |
| | `paper-press` | 纸墨质感白底，经典刊物阅读体验 |
| | `monochrome-print`| 纯粹黑白灰胶印，去燥极简 |
| | `newsroom` | 新闻报章纪实风，事件复盘与产业调研最佳 |
| **人文/质感** | `kraft-paper` | 牛皮纸复古质感，手工温润感 |
| | `vintage-editorial`| 复古排版与衬线字体，历史与文化演进主题 |
| | `forest-ink` | 深林墨绿护眼配色，生态与长期演化主题 |
| | `dune` | 沙漠大地暖色调，宏大叙事与思考类长文 |
| **先锋设计/明快** | `bauhaus-bold` | 包豪斯原色几何块面，强烈视觉构成 |
| | `bold-signal` | 高饱和警示橙黄，爆点揭秘与痛点洞察 |
| | `split-canvas` | 双色分屏对比，A/B 方案对撞与概念辨析 |

---

## 5. Token 控费与实战避坑指南 (Lessons Learned)

1. **Token 控费降级路径**：
   - **个人/经济模式 (推荐)**：选择**串行开发模式**。在 `tokens.css` 与 `global.css` 中提前提取通用的 `.kicker`, `.title`, `.card-box`, `.metric-badge` 样式。避免各章全量重复写入 300 行 CSS，可将 Token 消耗从 100 万压缩至 **30 万以内**。
   - **团队高速模式**：仅在具备充足配额与强基座模型（如 Claude Opus / Sonnet）时启用 Agent Teams 多章节并行。
2. **动态踩坑日志挂载 (`lessons_learned.md`)**：
   - 阶段二人工微调时遇到的任何具体排版错误（如文字遮挡拓扑图、移动端断点溢出、字号过小），必须立即沉淀到根目录的 `lessons_learned.md`。
   - 开发后续章节前，强制先读取该日志进行前置防御。
3. **Windows 平台执行建议**：
   - 音频合成与脚本调度可优先使用 Node/Python 跨平台命令；若使用 `.sh` 脚本，建议在 Git Bash、WSL2 或使用 Python 脚本执行。
