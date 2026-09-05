# -*- coding: utf-8 -*-
"""Patch script to align conversation readback models and ports with character presets."""
import os
import re
import sys
from pathlib import Path

CLIENT_SRC = Path(r"d:\AI Desktop Agent\desktop_client\src")
CLIENT_SERVER = Path(r"d:\AI Desktop Agent\desktop_client\server")

def patch_file(filepath: Path, old_block: str, new_block: str, desc: str):
    if not filepath.exists():
        print(f"[FAIL] File not found: {filepath}")
        return False
    
    content = filepath.read_text(encoding="utf-8")
    if old_block not in content:
        if new_block in content:
            print(f"[INFO] {desc} already applied in {filepath.name}")
            return True
        print(f"[FAIL] Target block not found in {filepath.name} for: {desc}")
        return False
    
    content = content.replace(old_block, new_block, 1)
    filepath.write_text(content, encoding="utf-8")
    print(f"[PASS] {desc} applied to {filepath.name}")
    return True

def run():
    print("=== Aligning Model and Port with Character Presets ===")
    success = True

    # 1. Patch configStore.ts
    config_store_path = CLIENT_SRC / "stores" / "configStore.ts"
    
    # 1.1 Add ttsEngine and ttsVoice to DEFAULT_AGENT_PRESETS
    old_presets_block = """    configFilePath: 'memory/user_settings.json',
    createdAt: '2026-08-22',
  },
  {
    id: 'desktop-agent-default',
    name: 'AI 桌面执行官 (Desktop Agent)',
    isCustom: false,
    isDefault: true,
    description: '端侧桌面全能智能体，调度系统监控与自动化代码指令',
    icon: 'autonomous',
    boundModel: 'deepseek-reasoner',
    temperature: 0.6,
    thinkingBudget: 16384,
    systemPrompt: `# Desktop AI Agent 核心调度协议
你是一个高效率、严谨的 Windows 桌面智能体。
- **零 Emoji 纯净纪律**: 严禁在代码、日志、UI 与输出中输出高位 Emoji 符号，一律采用 [OK]、[已完成]、[警告] 等纯文本规范标记。
- **严谨代码输出**: 输出的代码必须具备高可维护性与类型安全，并附带清晰的逻辑说明。
- **验证先于声明**: 任何任务结论必须基于确切的推导或事实。`,
    mountedSkills: [],
    configFilePath: 'memory/user_settings.json',
    createdAt: '2026-08-18',
  },
  {
    id: 'rrf-knowledge-expert',
    name: '本地知识图谱与错题本专家 (RRF Knowledge)',
    isCustom: false,
    isDefault: false,
    description: '基于知识图谱与错题本分级索引，高精度检索项目历史与操作台账',
    icon: 'reviewer',
    boundModel: 'deepseek-reasoner',
    temperature: 0.3,
    thinkingBudget: 12000,
    systemPrompt: `# 知识系统与错题本检索规范
- 基于本地知识系统进行全量检索与相关性排序。
- 在给出架构重构与排错建议前，优先查阅历史踩坑记录与错误模式库。
- 采用混合多维关联策略进行高精度知识蒸馏。`,
    mountedSkills: [],
    configFilePath: 'D:/AI Box/knowledge/index.json',
    createdAt: '2026-08-18',
  },
  {
    id: 'microkernel-architect',
    name: '全栈代码与微内核架构师 (Microkernel Architect)',
    isCustom: false,
    isDefault: false,
    description: '专注于客户端架构重构、模块解耦、TypeScript 前端与 Rust Tauri 桥接',
    icon: 'architect',
    boundModel: 'claude-3-7-sonnet',
    temperature: 0.4,
    thinkingBudget: 16384,
    systemPrompt: `# 软件架构与微内核规范
- 遵循薄主体与插件化解耦原则。
- 保证严格类型安全 (TypeScript strict / Python 类型提示)，杜绝未捕获异常导致主进程崩溃。`,
    mountedSkills: [],
    configFilePath: 'desktop_client/src-tauri/tauri.conf.json',
    createdAt: '2026-08-18',
  },
  {
    id: 'fast-chat-mode',
    name: '轻量极速日常助手 (Fast Assistant)',
    isCustom: false,
    isDefault: false,
    description: '低延迟流式对话，极速响应日常代码查阅、文档速览与日常问答',
    icon: 'chat',
    boundModel: 'deepseek-chat',
    temperature: 0.7,
    thinkingBudget: 2048,
    systemPrompt: `# 极速桌面助手规范
- 针对用户提问直接输出高价值结论与代码片段，不做多余漫长前缀。
- 输出内容保持精炼清晰，遵循 Flat 纯文本格式规范与代码高亮。`,
    mountedSkills: [],
    configFilePath: 'memory/user_settings.json',
    createdAt: '2026-08-18',
  },
];"""

    new_presets_block = """    configFilePath: 'memory/user_settings.json',
    createdAt: '2026-08-22',
    ttsEngine: 'gpt_sovits',
    ttsVoice: '流萤',
  },
  {
    id: 'desktop-agent-default',
    name: 'AI 桌面执行官 (Desktop Agent)',
    isCustom: false,
    isDefault: true,
    description: '端侧桌面全能智能体，调度系统监控与自动化代码指令',
    icon: 'autonomous',
    boundModel: 'deepseek-reasoner',
    temperature: 0.6,
    thinkingBudget: 16384,
    systemPrompt: `# Desktop AI Agent 核心调度协议
你是一个高效率、严谨的 Windows 桌面智能体。
- **零 Emoji 纯净纪律**: 严禁在代码、日志、UI 与输出中输出高位 Emoji 符号，一律采用 [OK]、[已完成]、[警告] 等纯文本规范标记。
- **严谨代码输出**: 输出的代码必须具备高可维护性与类型安全，并附带清晰的逻辑说明。
- **验证先于声明**: 任何任务结论必须基于确切的推导或事实。`,
    mountedSkills: [],
    configFilePath: 'memory/user_settings.json',
    createdAt: '2026-08-18',
    ttsEngine: 'gpt_sovits',
    ttsVoice: '流萤',
  },
  {
    id: 'rrf-knowledge-expert',
    name: '本地知识图谱与错题本专家 (RRF Knowledge)',
    isCustom: false,
    isDefault: false,
    description: '基于知识图谱与错题本分级索引，高精度检索项目历史与操作台账',
    icon: 'reviewer',
    boundModel: 'deepseek-reasoner',
    temperature: 0.3,
    thinkingBudget: 12000,
    systemPrompt: `# 知识系统与错题本检索规范
- 基于本地知识系统进行全量检索与相关性排序。
- 在给出架构重构与排错建议前，优先查阅历史踩坑记录与错误模式库。
- 采用混合多维关联策略进行高精度知识蒸馏。`,
    mountedSkills: [],
    configFilePath: 'D:/AI Box/knowledge/index.json',
    createdAt: '2026-08-18',
    ttsEngine: 'gpt_sovits',
    ttsVoice: '流萤',
  },
  {
    id: 'microkernel-architect',
    name: '全栈代码与微内核架构师 (Microkernel Architect)',
    isCustom: false,
    isDefault: false,
    description: '专注于客户端架构重构、模块解耦、TypeScript 前端与 Rust Tauri 桥接',
    icon: 'architect',
    boundModel: 'claude-3-7-sonnet',
    temperature: 0.4,
    thinkingBudget: 16384,
    systemPrompt: `# 软件架构与微内核规范
- 遵循薄主体与插件化解耦原则。
- 保证严格类型安全 (TypeScript strict / Python 类型提示)，杜绝未捕获异常导致主进程崩溃。`,
    mountedSkills: [],
    configFilePath: 'desktop_client/src-tauri/tauri.conf.json',
    createdAt: '2026-08-18',
    ttsEngine: 'gpt_sovits',
    ttsVoice: '三月七(底模零样本)',
  },
  {
    id: 'fast-chat-mode',
    name: '轻量极速日常助手 (Fast Assistant)',
    isCustom: false,
    isDefault: false,
    description: '低延迟流式对话，极速响应日常代码查阅、文档速览与日常问答',
    icon: 'chat',
    boundModel: 'deepseek-chat',
    temperature: 0.7,
    thinkingBudget: 2048,
    systemPrompt: `# 极速桌面助手规范
- 针对用户提问直接输出高价值结论与代码片段，不做多余漫长前缀。
- 输出内容保持精炼清晰，遵循 Flat 纯文本格式规范与代码高亮。`,
    mountedSkills: [],
    configFilePath: 'memory/user_settings.json',
    createdAt: '2026-08-18',
    ttsEngine: 'gpt_sovits',
    ttsVoice: '三月七(底模零样本)',
  },
];"""

    success &= patch_file(config_store_path, old_presets_block, new_presets_block, "Add default ttsEngine & ttsVoice")

    # 1.2 Update loadInitialAgentPresets to fill in missing ttsEngine and ttsVoice
    old_load_presets = """    if (raw) {
      const parsed = JSON.parse(raw) as AgentPreset[];
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed;
      }
    }"""
    new_load_presets = """    if (raw) {
      const parsed = JSON.parse(raw) as AgentPreset[];
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed.map(p => {
          const matchedDefault = DEFAULT_AGENT_PRESETS.find(d => d.id === p.id);
          return {
            ...p,
            ttsEngine: p.ttsEngine || matchedDefault?.ttsEngine || 'gpt_sovits',
            ttsVoice: p.ttsVoice || matchedDefault?.ttsVoice || '流萤',
          };
        });
      }
    }"""
    success &= patch_file(config_store_path, old_load_presets, new_load_presets, "Fill missing ttsEngine & ttsVoice in loaded presets")

    # 1.3 Update setSelectedPresetId to ensure model bound to preset is activated
    old_set_preset = """    let nextModelId = state.selectedModelId;
    if (targetPreset.boundModel && state.models.some(m => m.id === targetPreset.boundModel)) {
      nextModelId = targetPreset.boundModel;
      safeSetStorage(STORAGE_KEY_SELECTED_MODEL, nextModelId);
    }"""
    new_set_preset = """    let nextModelId = state.selectedModelId;
    if (targetPreset.boundModel) {
      nextModelId = targetPreset.boundModel;
      safeSetStorage(STORAGE_KEY_SELECTED_MODEL, nextModelId);
    }"""
    success &= patch_file(config_store_path, old_set_preset, new_set_preset, "Allow setSelectedPresetId to activate preset boundModel")

    # 2. Patch sessionStore.ts
    session_store_path = CLIENT_SRC / "stores" / "sessionStore.ts"

    # 2.1 Update createSession to respect active preset boundModel
    old_create_session = """  createSession: (title = '新对话', modelId = 'deepseek-reasoner', workspaceId?: string) => {
    const state = get();
    const wsId = workspaceId || state.currentWorkspaceId;
    const newId = `session-${Date.now()}`;
    const newSession: Session = {
      id: newId,
      workspaceId: wsId,
      title,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      modelId,
      messages: [],
    };"""

    new_create_session = """  createSession: (title = '新对话', modelId?: string, workspaceId?: string) => {
    const state = get();
    const wsId = workspaceId || state.currentWorkspaceId;
    const newId = `session-${Date.now()}`;
    // 若未显式传入指定模型，优先继承当前活跃预设绑定的模型或已选模型
    let effectiveModel = modelId;
    if (!effectiveModel || effectiveModel === 'deepseek-reasoner') {
      try {
        const cfg = useConfigStore.getState();
        const activePreset = cfg.getActivePreset();
        effectiveModel = cfg.selectedModelId || activePreset?.boundModel || 'deepseek-reasoner';
      } catch {
        effectiveModel = 'deepseek-reasoner';
      }
    }
    const newSession: Session = {
      id: newId,
      workspaceId: wsId,
      title,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      modelId: effectiveModel,
      messages: [],
    };"""
    success &= patch_file(session_store_path, old_create_session, new_create_session, "Inherit boundModel in createSession")

    # 2.2 Sync model on switchSession
    old_switch_session = """  switchSession: (id: string) => {
    try {
      localStorage.setItem(STORAGE_KEY_CUR_SESSION, id);
    } catch {}
    set((state) => ({
      currentSessionId: id,
      sessionLruTimestamps: {
        ...state.sessionLruTimestamps,
        [id]: Date.now(),
      },
    }));
  },"""

    new_switch_session = """  switchSession: (id: string) => {
    try {
      localStorage.setItem(STORAGE_KEY_CUR_SESSION, id);
    } catch {}
    const state = get();
    const targetSession = state.sessions.find(s => s.id === id);
    if (targetSession && targetSession.modelId) {
      try {
        useConfigStore.getState().setSelectedModel(targetSession.modelId);
      } catch {}
    }
    set((prevState) => ({
      currentSessionId: id,
      sessionLruTimestamps: {
        ...prevState.sessionLruTimestamps,
        [id]: Date.now(),
      },
    }));
  },"""
    success &= patch_file(session_store_path, old_switch_session, new_switch_session, "Sync model on switchSession")

    # 3. Patch chatService.ts line 271
    chat_service_path = CLIENT_SRC / "services" / "chatService.ts"
    old_chat_preset = """    // 获取当前激活的 Agent 预设与系统提示词
    const activePreset = configStore.agentPresets.find(p => p.isDefault) || configStore.agentPresets[0];
    let baseSystemPrompt = activePreset?.systemPrompt || '你是一个专业、严谨且富有洞察力的 AI 桌面智能助手。请用清晰优雅的格式回答。';"""

    new_chat_preset = """    // 获取当前激活的 Agent 预设与系统提示词 (严格对齐 getActivePreset)
    const activePreset = configStore.getActivePreset();
    let baseSystemPrompt = activePreset?.systemPrompt || '你是一个专业、严谨且富有洞察力的 AI 桌面智能助手。请用清晰优雅的格式回答。';"""
    success &= patch_file(chat_service_path, old_chat_preset, new_chat_preset, "Fix chatService activePreset retrieval")

    # 4. Patch voiceService.ts: expose cached catalog & support dynamic sovitsUrl
    voice_service_path = CLIENT_SRC / "services" / "voiceService.ts"
    
    old_test_synth = """  public async testSynthesize(
    payload: { voiceId: string; engine?: string; text: string; [key: string]: any },
    options?: RequestOptions
  ) {
    return apiClient.post<VoiceTestSynthesizeResult>('/api/voice/test-synthesize', payload, options);
  }"""

    new_test_synth = """  public getCachedCatalog(): VoiceCatalog | null {
    return this.cachedCatalog;
  }

  public async testSynthesize(
    payload: { voiceId: string; engine?: string; text: string; sovitsUrl?: string; [key: string]: any },
    options?: RequestOptions
  ) {
    return apiClient.post<VoiceTestSynthesizeResult>('/api/voice/test-synthesize', payload, options);
  }"""
    success &= patch_file(voice_service_path, old_test_synth, new_test_synth, "Expose getCachedCatalog and sovitsUrl in voiceService")

    # 5. Patch server/routes/runtimeRoutes.ts: handle dynamic port and fast direct SoVITS synthesis
    runtime_routes_path = CLIENT_SERVER / "routes" / "runtimeRoutes.ts"
    old_handle_synth = """export async function handleVoiceTestSynthesize(req: IncomingMessage, res: ServerResponse) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Content-Type', 'application/json');

  if (req.method === 'OPTIONS') {
    res.statusCode = 204;
    res.end();
    return;
  }

  let body = '';
  req.on('data', (chunk) => { body += chunk; });
  req.on('end', async () => {
    try {
      const payload = JSON.parse(body || '{}');
      const { voiceId, text, engine } = payload;
      const targetId = voiceId || 'zh-CN-XiaoxiaoNeural';
      const synthText = text || '您好！这是自定义语音合成测试效果，祝您工作愉快！';

      const scriptArgs: string[] = ['--test', targetId, '--text', synthText, '--no-play'];
      if (engine) {
        scriptArgs.push('--engine', engine);
      }

      const result = await runPythonScript('scripts/quick_voice_setup.py', {
        args: scriptArgs,
        timeoutMs: 35000,
      });

      // 检查是否有落地生成的试听音频文件
      const rootDir = path.resolve(__dirname, '../../../');
      const trialWavPath = path.join(rootDir, 'data', 'temp_audio', 'last_trial_voice.wav');
      let audioBase64: string | null = null;
      let audioFormat = 'audio/wav';

      if (fs.existsSync(trialWavPath)) {
        try {
          const fileBuf = fs.readFileSync(trialWavPath);
          if (fileBuf && fileBuf.length > 100) {
            audioBase64 = fileBuf.toString('base64');
          }
        } catch {}
      }

      res.statusCode = 200;
      res.end(JSON.stringify({
        ok: result.ok,
        output: result.stdout || result.stderr || (result.ok ? '语音合成成功' : '语音合成失败'),
        audioBase64,
        audioFormat,
      }));
    } catch (err: any) {
      res.statusCode = 500;
      res.end(JSON.stringify({ ok: false, error: err.message }));
    }
  });
}"""

    new_handle_synth = """export async function handleVoiceTestSynthesize(req: IncomingMessage, res: ServerResponse) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Content-Type', 'application/json');

  if (req.method === 'OPTIONS') {
    res.statusCode = 204;
    res.end();
    return;
  }

  let body = '';
  req.on('data', (chunk) => { body += chunk; });
  req.on('end', async () => {
    try {
      const payload = JSON.parse(body || '{}');
      const { voiceId, text, engine, sovitsUrl } = payload;
      const targetEngine = engine || (voiceId && (voiceId.startsWith('zh-') || voiceId.startsWith('ja-') || voiceId.startsWith('en-')) ? 'edge_tts' : 'gpt_sovits');
      const targetId = voiceId || (targetEngine === 'edge_tts' ? 'zh-CN-XiaoxiaoNeural' : '流萤');
      const synthText = text || '您好！这是自定义语音合成测试效果，祝您工作愉快！';
      const rootDir = path.resolve(__dirname, '../../../');
      const targetSovitsUrl = (sovitsUrl || 'http://127.0.0.1:9880').replace(/\\/+$/, '');
      const trialWavPath = path.join(rootDir, 'data', 'temp_audio', 'last_trial_voice.wav');
      let audioBase64: string | null = null;
      let audioFormat = 'audio/wav';

      // 1. 若为 GPT-SoVITS 且目标服务在线，优先通过高速直连代理执行权重加载与 POST 合成 (毫秒级响应，消除多进程开销)
      if (targetEngine === 'gpt_sovits') {
        const voicesPath = path.join(rootDir, 'voices.json');
        let matchedVoice: any = null;
        if (fs.existsSync(voicesPath)) {
          try {
            const voicesData = JSON.parse(fs.readFileSync(voicesPath, 'utf8'));
            if (Array.isArray(voicesData)) {
              matchedVoice = voicesData.find((v: any) => v.name === targetId || v.name?.includes(targetId) || targetId.includes(v.name));
            }
          } catch {}
        }

        if (matchedVoice) {
          try {
            // 切换模型权重
            if (matchedVoice.gpt) {
              await fetch(`${targetSovitsUrl}/set_gpt_weights?weights_path=${encodeURIComponent(matchedVoice.gpt)}`, { signal: AbortSignal.timeout(6000) }).catch(() => {});
            }
            if (matchedVoice.sovits) {
              await fetch(`${targetSovitsUrl}/set_sovits_weights?weights_path=${encodeURIComponent(matchedVoice.sovits)}`, { signal: AbortSignal.timeout(6000) }).catch(() => {});
            }

            // POST 合成请求
            const synthPayload = {
              text: synthText,
              text_lang: matchedVoice.lang || 'zh',
              ref_audio_path: matchedVoice.ref || '',
              prompt_text: matchedVoice.prompt || '',
              prompt_lang: matchedVoice.lang || 'zh',
              media_type: 'wav',
              streaming_mode: false,
            };

            const directRes = await fetch(`${targetSovitsUrl}/tts`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(synthPayload),
              signal: AbortSignal.timeout(18000),
            });

            if (directRes.ok) {
              const arrayBuf = await directRes.arrayBuffer();
              const buf = Buffer.from(arrayBuf);
              if (buf && buf.length > 200) {
                audioBase64 = buf.toString('base64');
                fs.mkdirSync(path.dirname(trialWavPath), { recursive: true });
                fs.writeFileSync(trialWavPath, buf);

                res.statusCode = 200;
                res.end(JSON.stringify({
                  ok: true,
                  output: `GPT-SoVITS 角色「${matchedVoice.name}」已通过端口 ${targetSovitsUrl} 高速合成成功`,
                  audioBase64,
                  audioFormat,
                }));
                return;
              }
            }
          } catch (directErr) {
            console.warn('[RuntimeRoutes] Direct SoVITS synth failed, falling back to script runner:', directErr);
          }
        }
      }

      // 2. 备用或 Edge-TTS: 回退至 Python quick_voice_setup.py 执行
      const scriptArgs: string[] = ['--test', targetId, '--text', synthText, '--no-play'];
      if (engine) {
        scriptArgs.push('--engine', engine);
      }

      const result = await runPythonScript('scripts/quick_voice_setup.py', {
        args: scriptArgs,
        timeoutMs: 35000,
      });

      if (fs.existsSync(trialWavPath)) {
        try {
          const fileBuf = fs.readFileSync(trialWavPath);
          if (fileBuf && fileBuf.length > 100) {
            audioBase64 = fileBuf.toString('base64');
          }
        } catch {}
      }

      res.statusCode = 200;
      res.end(JSON.stringify({
        ok: result.ok,
        output: result.stdout || result.stderr || (result.ok ? '语音合成成功' : '语音合成失败'),
        audioBase64,
        audioFormat,
      }));
    } catch (err: any) {
      res.statusCode = 500;
      res.end(JSON.stringify({ ok: false, error: err.message }));
    }
  });
}"""
    success &= patch_file(runtime_routes_path, old_handle_synth, new_handle_synth, "Add dynamic SoVITS proxy and correct defaults in runtimeRoutes.ts")

    # 6. Patch realtimeVoiceService.ts: fix fallback, pass sovitsUrl, and use proper POST payload
    realtime_voice_path = CLIENT_SRC / "services" / "realtimeVoiceService.ts"
    
    old_realtime_queue = """    try {
      const targetEngine = activePreset?.ttsEngine || 'gpt_sovits';
      const targetVoice = activePreset?.ttsVoice || (targetEngine === 'edge_tts' ? 'zh-CN-XiaoxiaoNeural' : '流萤');

      // 优先通过统一后端语音合成通道按预设专属音色播放
      let played = false;
      try {
        const res = await voiceService.testSynthesize({
          voiceId: targetVoice,
          engine: targetEngine,
          text: sentence,
        }, { timeoutMs: 12000 });"""

    new_realtime_queue = """    try {
      const targetEngine = activePreset?.ttsEngine || 'gpt_sovits';
      const targetVoice = activePreset?.ttsVoice || (targetEngine === 'edge_tts' ? 'zh-CN-XiaoxiaoNeural' : '流萤');
      const sovitsUrl = 'http://127.0.0.1:9880';

      // 优先通过统一后端语音合成通道按预设专属音色播放
      let played = false;
      try {
        const res = await voiceService.testSynthesize({
          voiceId: targetVoice,
          engine: targetEngine,
          text: sentence,
          sovitsUrl,
        }, { timeoutMs: 15000 });"""

    success &= patch_file(realtime_voice_path, old_realtime_queue, new_realtime_queue, "Pass sovitsUrl and increase timeout in processTtsQueue")

    old_play_fallback = """      // 若后端专属合成不可用，尝试直连本地 9880 端口或原生 Web Speech
      if (!played && targetEngine === 'gpt_sovits') {
        played = await this.playViaGptSovits(sentence);
      }
      if (!played) {
        await this.playViaWebSpeech(sentence);
      }
    } catch (e) {
      console.warn('[RealtimeVoiceService] 朗读失败:', e);
    } finally {
      this.isProcessingTtsQueue = false;
      if (this.ttsQueue.length === 0) {
        this.state.isSpeaking = false;
        this.notify();
      } else {
        this.processTtsQueue();
      }
    }
  }

  /**
   * 通过本地 GPT-SoVITS 端口朗读
   */
  private async playViaGptSovits(text: string): Promise<boolean> {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 1200);

      const res = await fetch(`http://127.0.0.1:9880/tts?text=${encodeURIComponent(text)}&text_language=zh`, {
        signal: controller.signal,
      });
      clearTimeout(timeout);

      if (!res.ok) return false;
      const blob = await res.blob();
      const audioUrl = URL.createObjectURL(blob);
      const audio = new Audio(audioUrl);
      this.currentAudio = audio;

      // 申请通道并注册抢占打断回调
      audioChannelArbiter.claimChannel('stream_tts', audio, () => {
        this.stopSpeaking();
      });

      return new Promise((resolve) => {
        audio.onended = () => {
          this.currentAudio = null;
          audioChannelArbiter.releaseChannel('stream_tts', audio);
          URL.revokeObjectURL(audioUrl);
          resolve(true);
        };
        audio.onerror = () => {
          this.currentAudio = null;
          audioChannelArbiter.releaseChannel('stream_tts', audio);
          URL.revokeObjectURL(audioUrl);
          resolve(false);
        };
        audio.play().catch(() => {
          this.currentAudio = null;
          audioChannelArbiter.releaseChannel('stream_tts', audio);
          URL.revokeObjectURL(audioUrl);
          resolve(false);
        });
      });
    } catch {
      return false;
    }
  }"""

    new_play_fallback = """      // 若后端专属合成不可用，尝试直连本地 GPT-SoVITS 端口或原生 Web Speech
      if (!played && targetEngine === 'gpt_sovits') {
        played = await this.playViaGptSovits(sentence, targetVoice, sovitsUrl);
      }
      if (!played) {
        console.warn(`[RealtimeVoiceService] 专属音色「${targetVoice}」(${targetEngine}) 合成未能完成，降级至原生语音播放`);
        await this.playViaWebSpeech(sentence);
      }
    } catch (e) {
      console.warn('[RealtimeVoiceService] 朗读失败:', e);
    } finally {
      this.isProcessingTtsQueue = false;
      if (this.ttsQueue.length === 0) {
        this.state.isSpeaking = false;
        this.notify();
      } else {
        this.processTtsQueue();
      }
    }
  }

  /**
   * 通过本地 GPT-SoVITS 端口与专属角色音色直接合成播放 (备用高速通道)
   */
  private async playViaGptSovits(text: string, voiceName?: string, sovitsUrl?: string): Promise<boolean> {
    try {
      const baseUrl = (sovitsUrl || 'http://127.0.0.1:9880').replace(/\\/+$/, '');
      const catalog = voiceService.getCachedCatalog();
      const matchedVoice = catalog?.gptSovits?.find((v: any) => v.name === voiceName || v.name?.includes(voiceName || '') || (voiceName && voiceName.includes(v.name)));

      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 16000);

      // 确保模型权重切换至预设角色
      if (matchedVoice) {
        if (matchedVoice.gpt) {
          await fetch(`${baseUrl}/set_gpt_weights?weights_path=${encodeURIComponent(matchedVoice.gpt)}`, { signal: controller.signal }).catch(() => {});
        }
        if (matchedVoice.sovits) {
          await fetch(`${baseUrl}/set_sovits_weights?weights_path=${encodeURIComponent(matchedVoice.sovits)}`, { signal: controller.signal }).catch(() => {});
        }
      }

      const payload = {
        text,
        text_lang: matchedVoice?.lang || 'zh',
        ref_audio_path: matchedVoice?.ref || '',
        prompt_text: matchedVoice?.prompt || '',
        prompt_lang: matchedVoice?.lang || 'zh',
        media_type: 'wav',
        streaming_mode: false,
      };

      const res = await fetch(`${baseUrl}/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      clearTimeout(timeout);

      if (!res.ok) return false;
      const blob = await res.blob();
      if (!blob || blob.size < 200) return false;

      const audioUrl = URL.createObjectURL(blob);
      const audio = new Audio(audioUrl);
      this.currentAudio = audio;

      // 申请通道并注册抢占打断回调
      audioChannelArbiter.claimChannel('stream_tts', audio, () => {
        this.stopSpeaking();
      });

      return new Promise((resolve) => {
        audio.onended = () => {
          this.currentAudio = null;
          audioChannelArbiter.releaseChannel('stream_tts', audio);
          URL.revokeObjectURL(audioUrl);
          resolve(true);
        };
        audio.onerror = () => {
          this.currentAudio = null;
          audioChannelArbiter.releaseChannel('stream_tts', audio);
          URL.revokeObjectURL(audioUrl);
          resolve(false);
        };
        audio.play().catch(() => {
          this.currentAudio = null;
          audioChannelArbiter.releaseChannel('stream_tts', audio);
          URL.revokeObjectURL(audioUrl);
          resolve(false);
        });
      });
    } catch {
      return false;
    }
  }"""
    success &= patch_file(realtime_voice_path, old_play_fallback, new_play_fallback, "Update playViaGptSovits with POST and voice weights")

    if success:
        print("\n[PASS] All patches successfully applied!")
        return 0
    else:
        print("\n[WARN] Some patches could not be applied or were already present.")
        return 1

if __name__ == "__main__":
    sys.exit(run())
