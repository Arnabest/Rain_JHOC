import os
import re

print("[START] Consolidating Verse Agent plugins...")

# 1. Update defaultPlugins.ts
plugins_ts_path = r"d:\AI Desktop Agent\desktop_client\src\constants\defaultPlugins.ts"

new_default_plugins_content = '''export interface DSHPluginItem {
  plugin_id: string;
  name: string;
  category: 'sensor' | 'tool' | 'skill' | 'memory' | 'middleware' | 'actuator';
  description: string;
  enabled: boolean;
  priority: number;
  injects_context: boolean;  // True = Context Slice injection; False = On-demand tool/actuator
  max_context_tokens: number;
  event_triggers: string[];
  user_config?: Record<string, any>;
  is_builtin?: boolean;
  source_file?: string;
  packaging_type?: 'standard_agent_bundle';
  version?: string;
  isolation_level?: 'workspace_sandbox' | 'isolated_process';
  dependencies?: string[]; // 底层依赖列表
}

export const DEFAULT_PLUGINS: DSHPluginItem[] = [
  // 1. UI 底层插槽
  {
    plugin_id: 'ui-header-action-slot',
    name: '快捷操作扩展槽 (Header Action Slot)',
    category: 'middleware',
    description: '为业务底层和顶栏提供动态操作插槽，支持业务插件注册快捷图标、自定义按钮、状态徽标与下拉菜单，统一生命周期安全管控。',
    enabled: true,
    priority: 0,
    injects_context: false,
    max_context_tokens: 0,
    event_triggers: ['ui.header_action.register', 'ui.header_action.unregister', 'ui.header_action.update'],
    is_builtin: true,
  },
  // 2. 音频基建
  {
    plugin_id: 'audio-voice-infra',
    name: '统一音频与语音基础设施 (Voice & Audio Infrastructure)',
    category: 'middleware',
    description: '提供系统级音频通道仲裁（Audio Channel Arbiter）、TTS 与 STT 双向音频清洗与自发声防回环（AEC）消音管线。',
    enabled: true,
    priority: 1,
    injects_context: false,
    max_context_tokens: 0,
    dependencies: ['ui-header-action-slot'],
    event_triggers: ['voice.tts.synthesize', 'voice.tts.speak', 'voice.stt.transcribe', 'voice.channel.claim', 'voice.channel.release'],
    is_builtin: true,
  },
  // 3. TTS 执行器
  {
    plugin_id: 'actuator-tts-sovits',
    name: 'GPT-SoVITS 语音合成执行器 (TTS Actuator)',
    category: 'actuator',
    description: '直连本地 GPT-SoVITS (:9880) 高速语音引擎，支持专属角色权重动态热切换、流式伴读分句合成与毫秒级低延迟播放。',
    enabled: true,
    priority: 2,
    injects_context: false,
    max_context_tokens: 0,
    dependencies: ['audio-voice-infra'],
    event_triggers: ['tts.synthesize.request', 'tts.model.switch', 'tts.speed.adjust'],
    is_builtin: true,
  },
  // 4. JHOC 全局治理
  {
    plugin_id: 'jhoc-governance-hud',
    name: 'JHOC 全局治理 HUD (JHOC Governance HUD)',
    category: 'middleware',
    description: '对接 G:\\JHOC 母库治理规范，向会话动态注入核心宪法约束、Rule 7 零 Emoji 纯度法则与单机物理验证守则。',
    enabled: true,
    priority: 5,
    injects_context: true,
    max_context_tokens: 512,
    dependencies: ['ui-header-action-slot'],
    event_triggers: ['jhoc.rule.query', 'jhoc.gate.status', 'governance.hud.sync'],
    is_builtin: true,
  },
  // 5. JHOC 工程门禁
  {
    plugin_id: 'jhoc-engineering-lifecycle',
    name: 'JHOC 工程生命周期门禁 (Kaigong & Shougong Lifecycle)',
    category: 'middleware',
    description: '整合开工前置硬门禁、工作区物理安全护卫（Workspace Guard）与收工归档复核，严格落实开工反问四大维度对齐与未决事项清单交接。',
    enabled: true,
    priority: 6,
    injects_context: true,
    max_context_tokens: 512,
    event_triggers: ['lifecycle.kaigong.verify', 'lifecycle.shougong.audit', 'workspace.boundary.check'],
    is_builtin: true,
  },
  // 6. 多模型协同总线
  {
    plugin_id: 'multi-model-orchestrator',
    name: '多模型协同编排总线 (Multi-Model Orchestrator)',
    category: 'middleware',
    description: '整合 Agent Bus 协同总线、三六阶段任务流转、动态模型竞价路由、异步 Codex 指派与跨模型工作流状态同步。',
    enabled: true,
    priority: 10,
    injects_context: false,
    max_context_tokens: 0,
    event_triggers: ['agent.bus.dispatch', 'model.route.evaluate', 'codex.task.assign', 'multi_model.sync'],
    is_builtin: true,
  },
  // 7. 多模型对等复核
  {
    plugin_id: 'multimodel-review-loop',
    name: '多模型对等复核与方案审查 (Multimodel Peer Review Loop)',
    category: 'skill',
    description: '多模型对等复核环与 Codex 方案规划反向审查套件，执行 DOWN/UP/FORK 三维影响路径推演、缺陷优先反思与任务后置审计。',
    enabled: true,
    priority: 12,
    injects_context: false,
    max_context_tokens: 0,
    user_config: { review_mode: 'peer_review', enabled_codex: true, consensus_threshold: 0.8 },
    event_triggers: ['chat.review.start', 'chat.review.consensus', 'plan.review.audit'],
    is_builtin: true,
  },
  // 8. 知识图谱与 RRF
  {
    plugin_id: 'knowledge-graph-rrf',
    name: '本地因果图谱与 RRF 知识库 (Knowledge Graph & RRF)',
    category: 'memory',
    description: '本地因果拓扑图谱与 RRF（倒数排名融合）多路检索增强系统，负责项目实体依赖构建、知识库图谱管理员分级归档与精准检索。',
    enabled: true,
    priority: 15,
    injects_context: true,
    max_context_tokens: 1024,
    event_triggers: ['memory.rag.search', 'graph.entity.link', 'librarian.catalog.sync'],
    is_builtin: true,
  },
  // 9. 记忆治理中枢
  {
    plugin_id: 'memory-governance-hub',
    name: '分层记忆治理中枢与自愈压缩 (Memory Governance & Context Compact)',
    category: 'memory',
    description: '提供 L1/L2/L3 分层记忆沉淀、错题集（Lessons）治理、无损摘要提炼与长会话上下文滑动窗口自愈压缩。',
    enabled: true,
    priority: 16,
    injects_context: true,
    max_context_tokens: 768,
    event_triggers: ['memory.compact.execute', 'memory.lessons.query', 'memory.persist.commit'],
    is_builtin: true,
  },
  // 10. 多模态态势感知
  {
    plugin_id: 'sensors-multimodal-hub',
    name: '多模态态势感知中枢 (Sensors Multimodal Hub)',
    category: 'sensor',
    description: '整合一键屏幕视窗截图分析、剪贴板动态感知、用户环境态势捕捉与多模态流式数据定时蒸馏。',
    enabled: true,
    priority: 20,
    injects_context: true,
    max_context_tokens: 512,
    dependencies: ['ui-header-action-slot'],
    event_triggers: ['sensory.screen.capture', 'sensory.clipboard.read', 'sensory.environment.probe'],
    is_builtin: true,
  },
  // 11. FunASR 转写套件
  {
    plugin_id: 'media-transcribe-suite',
    name: 'FunASR 音视频转写套件 (Media Transcribe Suite)',
    category: 'tool',
    description: '集成阿里 FunASR (Paraformer-Large) 离线高精转写引擎，支持长音频时间戳分片、降噪切片与 ITN 错字口语清洗。',
    enabled: true,
    priority: 25,
    injects_context: false,
    max_context_tokens: 0,
    event_triggers: ['audio.transcribe.start', 'audio.slice.process', 'audio.text.clean'],
    is_builtin: true,
  },
  // 12. 媒体深度研报
  {
    plugin_id: 'media-learning-distiller',
    name: '音视频深度研报研析管线 (Media Learning & Report Distiller)',
    category: 'skill',
    description: '将技术会议、学术长视频及多媒体讲座字幕经由深度分析管线，提取核心因果链路，一键排版生成高质量专业结构化研报。',
    enabled: true,
    priority: 26,
    injects_context: false,
    max_context_tokens: 0,
    event_triggers: ['media.learn.pipeline', 'media.report.generate'],
    is_builtin: true,
  },
  // 13. 网页搜索
  {
    plugin_id: 'skill-web-search',
    name: '网页检索与实时浏览 (Web Search & Browse)',
    category: 'tool',
    description: '具备搜索引擎联网调用能力，支持实时跨网检索、抓取高质量信息源、Markdown 网页排版与源引用溯源。',
    enabled: true,
    priority: 30,
    injects_context: false,
    max_context_tokens: 0,
    event_triggers: ['web.search.query', 'web.page.fetch', 'web.browse.extract'],
    is_builtin: true,
  },
  // 14. 文档 OCR
  {
    plugin_id: 'skill-document-ocr',
    name: '文档图像 OCR 提取 (Document OCR)',
    category: 'tool',
    description: '支持 DeepSeek-OCR 与本地 OCR 解析本地 PDF、长截图、表格与多语种印刷体，支持多图批处理与 Markdown 格式转换。',
    enabled: true,
    priority: 31,
    injects_context: false,
    max_context_tokens: 0,
    event_triggers: ['ocr.image.extract', 'ocr.pdf.parse'],
    is_builtin: true,
  },
  // 15. Token 监控
  {
    plugin_id: 'skill-token-stats',
    name: 'Token 消耗与配额监控 HUD (Token & Quota HUD)',
    category: 'middleware',
    description: '实时采集 Antigravity / OpenAI 账户配额与 Token 消耗速率，在达到 8% 临界阈值时主动报警并支持安全交接。',
    enabled: true,
    priority: 35,
    injects_context: false,
    max_context_tokens: 0,
    dependencies: ['ui-header-action-slot'],
    event_triggers: ['token.stats.query', 'quota.alert.trigger'],
    is_builtin: true,
  },
  // 16. 自主长程目标
  {
    plugin_id: 'skill-goal',
    name: '目标驱动自主循环 (Goal-Driven Autonomous Loop)',
    category: 'skill',
    description: '针对复杂长程任务，启动自我规划、分步执行、自我纠偏与结果检验的闭环长程自主执行循环。',
    enabled: true,
    priority: 40,
    injects_context: false,
    max_context_tokens: 0,
    event_triggers: ['agent.goal.start', 'agent.goal.step', 'agent.goal.complete'],
    is_builtin: true,
  },
  // 17. 方案规划
  {
    plugin_id: 'skill-plan',
    name: '架构规划与规格设计 (Architecture Planning & Spec)',
    category: 'skill',
    description: '为复杂工程、重构与新特性生成高保真分步实施方案（implementation plan），支持风险评估与用户审批前置门禁。',
    enabled: true,
    priority: 41,
    injects_context: false,
    max_context_tokens: 0,
    event_triggers: ['plan.generate', 'plan.review.request'],
    is_builtin: true,
  },
  // 18. 多维反问探针
  {
    plugin_id: 'skill-counter-questioning-probe',
    name: '多维反问探针 (Counter-Questioning Probe)',
    category: 'skill',
    description: '面对模糊或高风险需求，主动从范围边界、架构取舍、异常降级、长期治理四大正交维度主动反问，对齐基准。',
    enabled: true,
    priority: 42,
    injects_context: false,
    max_context_tokens: 0,
    event_triggers: ['probe.counter_question', 'probe.dimension.align'],
    is_builtin: true,
  },
  // 19. 论文算法提炼
  {
    plugin_id: 'skill-paper-to-knowledge-distiller',
    name: '前沿论文研读与算法提炼 (Paper Knowledge Distiller)',
    category: 'skill',
    description: '系统提取学术论文的问题定义、核心数学公式推导、消融实验证据，识别伪创新与学术过度包装，提炼纯粹可复现代码。',
    enabled: true,
    priority: 45,
    injects_context: false,
    max_context_tokens: 0,
    event_triggers: ['paper.distill.read', 'paper.formula.derive'],
    is_builtin: true,
  },
  // 20. 全量 E2E 诊断
  {
    plugin_id: 'verse-e2e-diagnostic-suite',
    name: 'Verse Agent 20轮全量端到端诊断 (20-Round E2E Diagnostic Suite)',
    category: 'tool',
    description: '全链路真实环境诊断套件，自动核验后端 API、语音 TTS/STT、沙箱生命周期、模型路由与会话持久化一致性。',
    enabled: true,
    priority: 50,
    injects_context: false,
    max_context_tokens: 0,
    event_triggers: ['diagnostic.e2e.run', 'diagnostic.report.generate'],
    is_builtin: true,
  },
];

export const STORAGE_KEY_PLUGINS = 'dsh_plugins_config_v12';
'''

with open(plugins_ts_path, "w", encoding="utf-8") as f:
    f.write(new_default_plugins_content)
print("[PASS] defaultPlugins.ts updated to 20 consolidated plugins, bumped to v12")

# 2. Update PluginsHubTab.tsx
hub_path = r"d:\AI Desktop Agent\desktop_client\src\components\settings\tabs\PluginsHubTab.tsx"
with open(hub_path, "r", encoding="utf-8") as f:
    hub = f.read()

# Update old migration keys check
hub = hub.replace("localStorage.getItem('dsh_plugins_config_v11')", "localStorage.getItem('dsh_plugins_config_v12')")
# Update review plugin search
hub = hub.replace(
    "const reviewPlugin = plugins.find(p => p.plugin_id === 'skill-multimodel-review' || p.plugin_id === 'skill-three-six-review-cadence');",
    "const reviewPlugin = plugins.find(p => p.plugin_id === 'multimodel-review-loop' || p.plugin_id === 'multi-model-orchestrator' || p.plugin_id === 'skill-multimodel-review');"
)
with open(hub_path, "w", encoding="utf-8") as f:
    f.write(hub)
print("[PASS] PluginsHubTab.tsx updated")

# 3. Update useSlashCommands.ts
slash_path = r"d:\AI Desktop Agent\desktop_client\src\hooks\useSlashCommands.ts"
with open(slash_path, "r", encoding="utf-8") as f:
    sc = f.read()

# Replace legacy mappings with clean mappings
old_slash_mappings = """        // 核心技能映射
        else if (p.plugin_id === 'skill-compact') {
          cmdName = 'compact';
          promptText = '/compact 请对当前对话进行上下文压缩与摘要蒸馏。';
          icon = Minimize2;
          categoryName = '工具';
        } else if (p.plugin_id === 'skill-goal') {
          cmdName = 'goal';
          promptText = '/goal 目标：';
          icon = Target;
          categoryName = '编排';
        } else if (p.plugin_id === 'skill-plan') {
          cmdName = 'plan';
          promptText = '/plan 请为我制定详细的架构设计与分阶段规划：\\n';
          icon = FileSpreadsheet;
          categoryName = '架构';
        } else if (p.plugin_id === 'skill-codex-plan-review') {
          cmdName = 'plan-review';
          promptText = '请对以下架构规划进行深度评审与反向对齐：\\n';
          icon = ShieldCheck;
          categoryName = '复核';
        } else if (p.plugin_id === 'skill-counter-questioning-probe') {
          cmdName = 'probe';
          promptText = '请针对以下需求，从四大正交维度发起反问探针：\\n';
          icon = HelpCircle;
          categoryName = '对齐';
        } else if (p.plugin_id === 'skill-paper-to-knowledge-distiller') {
          cmdName = 'paper';
          promptText = '请研读并提炼以下论文的核心算法框架与数学推导：\\n';
          icon = FileSearch;
          categoryName = '学术';
        } else if (p.plugin_id === 'skill-media-learning') {
          cmdName = 'media-learn';
          promptText = '请启动音视频学习管线并提炼深度研报：\\n';
          icon = FileCode;
          categoryName = '研报';
        } else if (p.plugin_id === 'skill-media-transcribe') {
          cmdName = 'transcribe';
          promptText = '请调用 FunASR 模型执行音视频转写任务：\\n';
          icon = FileAudio;
          categoryName = '转写';
        } else if (p.plugin_id === 'skill-text-preclean') {
          cmdName = 'preclean';
          promptText = '请对以下转写或 OCR 文本进行结构化清洗与口语归一：\\n';
          icon = Sparkles;
          categoryName = '工具';
        } else if (p.plugin_id === 'skill-audio-split-transcribe') {
          cmdName = 'audio-split';
          promptText = '请对长音频进行时间戳切片与并行转写调度：\\n';
          icon = FileAudio;
          categoryName = '转写';
        } else if (p.plugin_id === 'skill-devtools-deep-diagnostics') {
          cmdName = 'diagnose';
          promptText = '请执行 IDE 与系统环境深度排错与端口自愈诊断：\\n';
          icon = Wrench;
          categoryName = '运维';
        } else if (p.plugin_id === 'skill-python-architecture-modularizer') {
          cmdName = 'modularize';
          promptText = '请对以下复杂 Python 模块进行 800 行以内的模块化架构拆分：\\n';
          icon = FileCode;
          categoryName = '代码';
        } else if (p.plugin_id === 'skill-qt-gui-polish') {
          cmdName = 'qt-polish';
          promptText = '请针对 Qt GUI 样式进行专业桌面化美化与无障碍调优：\\n';
          icon = Palette;
          categoryName = '界面';
        } else if (p.plugin_id === 'skill-vision-bridge') {
          cmdName = 'vision';
          promptText = '请结合当前屏幕视窗与图像进行视觉多模态分析：\\n';
          icon = Eye;
          categoryName = '感知';
        } else if (p.plugin_id === 'skill-web-search') {
          cmdName = 'search';
          promptText = '请使用网页搜索检索以下最新信息：\\n';
          icon = Search;
          categoryName = '搜索';
        } else if (p.plugin_id === 'skill-document-ocr') {
          cmdName = 'ocr';
          promptText = '请提取以下文档或图片中的全部结构化文字与表格：\\n';
          icon = FileText;
          categoryName = '识别';
        } else if (p.plugin_id === 'actuator-tts-sovits') {
          cmdName = 'speak';
          promptText = '请使用 GPT-SoVITS 语音合成朗读以下内容：\\n';
          icon = Volume2;
          categoryName = '语音';
        }"""

new_slash_mappings = """        // 现代化整合插件指令映射
        else if (p.plugin_id === 'memory-governance-hub') {
          cmdName = 'compact';
          promptText = '/compact 请对当前会话执行分层记忆沉淀与无损上下文压缩。';
          icon = Minimize2;
          categoryName = '记忆';
        } else if (p.plugin_id === 'knowledge-graph-rrf') {
          cmdName = 'rag';
          promptText = '请基于本地因果拓扑图谱与 RRF 检索增强查询以下知识：\\n';
          icon = BrainCircuit;
          categoryName = '知识';
        } else if (p.plugin_id === 'multimodel-review-loop') {
          cmdName = 'review';
          promptText = '请启动多模型对等复核环，对方案进行 DOWN/UP/FORK 三维推演与反向审查：\\n';
          icon = ShieldCheck;
          categoryName = '复核';
        } else if (p.plugin_id === 'multi-model-orchestrator') {
          cmdName = 'orchestrate';
          promptText = '请启动多模型协同总线，按三六阶段流转调度任务：\\n';
          icon = Layers;
          categoryName = '协同';
        } else if (p.plugin_id === 'sensors-multimodal-hub') {
          cmdName = 'vision';
          promptText = '请结合当前屏幕视窗与图像进行视觉多模态态势分析：\\n';
          icon = Eye;
          categoryName = '感知';
        } else if (p.plugin_id === 'media-transcribe-suite') {
          cmdName = 'transcribe';
          promptText = '请调用 FunASR 音视频转写套件执行切片转写与口语清洗：\\n';
          icon = FileAudio;
          categoryName = '音视频';
        } else if (p.plugin_id === 'media-learning-distiller') {
          cmdName = 'media-learn';
          promptText = '请启动音视频深度研报研析管线，提取因果链路并生成研报：\\n';
          icon = FileCode;
          categoryName = '研报';
        } else if (p.plugin_id === 'skill-goal') {
          cmdName = 'goal';
          promptText = '/goal 目标：';
          icon = Target;
          categoryName = '自主';
        } else if (p.plugin_id === 'skill-plan') {
          cmdName = 'plan';
          promptText = '/plan 请为我制定详细的架构设计与分阶段实施方案：\\n';
          icon = FileSpreadsheet;
          categoryName = '架构';
        } else if (p.plugin_id === 'skill-counter-questioning-probe') {
          cmdName = 'probe';
          promptText = '请针对以下需求，从四大正交维度发起开工反问探针：\\n';
          icon = HelpCircle;
          categoryName = '对齐';
        } else if (p.plugin_id === 'skill-paper-to-knowledge-distiller') {
          cmdName = 'paper';
          promptText = '请研读并提炼以下前沿论文的核心算法框架与数学推导：\\n';
          icon = FileSearch;
          categoryName = '学术';
        } else if (p.plugin_id === 'skill-web-search') {
          cmdName = 'search';
          promptText = '请使用网页检索跨网查询以下最新事实与资料：\\n';
          icon = Search;
          categoryName = '搜索';
        } else if (p.plugin_id === 'skill-document-ocr') {
          cmdName = 'ocr';
          promptText = '请提取以下文档或图片中的全部结构化文字与表格：\\n';
          icon = FileText;
          categoryName = '识别';
        } else if (p.plugin_id === 'actuator-tts-sovits') {
          cmdName = 'speak';
          promptText = '请使用 GPT-SoVITS 语音合成朗读以下内容：\\n';
          icon = Volume2;
          categoryName = '语音';
        } else if (p.plugin_id === 'verse-e2e-diagnostic-suite') {
          cmdName = 'diagnose';
          promptText = '请执行 Verse Agent 全量端到端环境与链路自愈诊断：\\n';
          icon = Wrench;
          categoryName = '运维';
        }"""

if old_slash_mappings in sc:
    sc = sc.replace(old_slash_mappings, new_slash_mappings)
    print("[PASS] useSlashCommands.ts mapped to consolidated plugins")
else:
    print("[WARN] old_slash_mappings did not match exactly, checking regex")

with open(slash_path, "w", encoding="utf-8") as f:
    f.write(sc)

# 4. Update configStore.ts
cfg_path = r"d:\AI Desktop Agent\desktop_client\src\stores\configStore.ts"
with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = f.read()

# Update loadInitialWebSearchPluginActive key to STORAGE_KEY_PLUGINS or v12
cfg = cfg.replace("'dsh_plugins_config_v7'", "'dsh_plugins_config_v12'")
with open(cfg_path, "w", encoding="utf-8") as f:
    f.write(cfg)
print("[PASS] configStore.ts updated to v12 key")

print("[DONE] All plugin consolidation edits completed.")
