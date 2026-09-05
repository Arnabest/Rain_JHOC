slash_path = r'd:\AI Desktop Agent\desktop_client\src\hooks\useSlashCommands.ts'
with open(slash_path, 'r', encoding='utf-8') as f:
    code = f.read()

start_marker = "        // 核心技能映射"
end_marker = "        } else if (p.category === 'sensor') {"

start_idx = code.find(start_marker)
end_idx = code.find(end_marker)

if start_idx != -1 and end_idx != -1:
    new_block = """        // 现代化整合插件指令映射
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
          icon = Volume2;
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
          promptText = '请联网搜索并分析：';
          icon = SearchIcon;
          categoryName = '搜索';
        } else if (p.plugin_id === 'skill-document-ocr') {
          cmdName = 'ocr';
          promptText = '请执行 OCR 识别与文本提取：';
          icon = ScanText;
          categoryName = '识别';
        } else if (p.plugin_id === 'actuator-tts-sovits') {
          cmdName = 'tts';
          promptText = '请使用 GPT-SoVITS 语音合成朗读以下内容：';
          icon = Volume2;
          categoryName = '语音';
        } else if (p.plugin_id === 'verse-e2e-diagnostic-suite') {
          cmdName = 'diagnose';
          promptText = '请执行 Verse Agent 全量端到端环境与链路自愈诊断：\\n';
          icon = Wrench;
          categoryName = '运维';
        }
"""
    code = code[:start_idx] + new_block + code[end_idx:]
    with open(slash_path, 'w', encoding='utf-8') as f:
        f.write(code)
    print('[PASS] useSlashCommands.ts successfully updated with new block!')
else:
    print('[FAIL] Markers not found:', start_idx, end_idx)
