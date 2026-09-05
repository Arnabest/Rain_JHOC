import os
import re

print("[START] Patching auto-speak and TTS broadcast pipeline...")

# 1. Patch SensoryDropdown.tsx
sensory_path = r"d:\AI Desktop Agent\desktop_client\src\components\header\SensoryDropdown.tsx"
if os.path.exists(sensory_path):
    with open(sensory_path, "r", encoding="utf-8") as f:
        s = f.read()

    # Make subtitle and button clear and unambiguous
    old_status_block = """                  <div>
                    <span className="text-xs font-medium text-text-primary">
                      语音合成播报 (TTS)
                    </span>
                    <p className="text-[11px] text-text-muted">
                      {isVoiceBroadcastEnabled ? `GPT-SoVITS 就绪 (${volume}%)` : '已静音'}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => toggleVoiceBroadcast()}
                  className={`px-2 py-1 rounded-lg text-xs font-medium transition-colors ${
                    isVoiceBroadcastEnabled
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'bg-white/[0.06] text-text-muted hover:text-text-primary'
                  }`}
                >
                  {isVoiceBroadcastEnabled ? '开启' : '关闭'}
                </button>"""

    new_status_block = """                  <div>
                    <span className="text-xs font-medium text-text-primary">
                      语音合成播报 (TTS)
                    </span>
                    <p className="text-[11px] text-text-muted">
                      {isVoiceBroadcastEnabled ? `已开启自动朗诵 (${volume}%)` : '已静音 (不自动朗诵)'}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => toggleVoiceBroadcast()}
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                    isVoiceBroadcastEnabled
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/30'
                      : 'bg-white/[0.06] text-text-muted hover:text-text-primary hover:bg-white/[0.1]'
                  }`}
                  title={isVoiceBroadcastEnabled ? '点击关闭自动朗诵' : '点击开启自动朗诵'}
                >
                  {isVoiceBroadcastEnabled ? '已开启' : '点击开启'}
                </button>"""

    # Also handle if already modified or slightly different
    if old_status_block in s:
        s = s.replace(old_status_block, new_status_block)
        print("[PASS] SensoryDropdown.tsx button & status updated")
    else:
        # Regex replacement for flexible matching
        pat = r"\{\s*isVoiceBroadcastEnabled\s*\?\s*`[^`]+`\s*:\s*'已静音'\s*\}"
        s = re.sub(pat, "{isVoiceBroadcastEnabled ? `已开启自动朗诵 (${volume}%)` : '已静音 (不自动朗诵)'}", s)
        pat_btn = r"\{\s*isVoiceBroadcastEnabled\s*\?\s*'开启'\s*:\s*'(?:关闭|静音)'\s*\}"
        s = re.sub(pat_btn, "{isVoiceBroadcastEnabled ? '已开启' : '点击开启'}", s)
        print("[PASS] SensoryDropdown.tsx patched via regex")

    with open(sensory_path, "w", encoding="utf-8") as f:
        f.write(s)

# 2. Patch FloatingComposer.tsx
composer_path = r"d:\AI Desktop Agent\desktop_client\src\components\composer\FloatingComposer.tsx"
if os.path.exists(composer_path):
    with open(composer_path, "r", encoding="utf-8") as f:
        comp = f.read()

    if "import { useTtsStore } from '../../stores/ttsStore';" not in comp:
        comp = "import { useTtsStore } from '../../stores/ttsStore';\n" + comp

    # When mic sends, ensure voice broadcast is active
    old_send_mic = """      if (textToSend) {
        handleSend(textToSend);
      }"""
    new_send_mic = """      if (textToSend) {
        useTtsStore.getState().setVoiceBroadcast(true);
        handleSend(textToSend);
      }"""
    if old_send_mic in comp:
        comp = comp.replace(old_send_mic, new_send_mic)
        print("[PASS] FloatingComposer.tsx mic send linked to setVoiceBroadcast(true)")

    with open(composer_path, "w", encoding="utf-8") as f:
        f.write(comp)

# 3. Patch chatStreamExecutor.ts
stream_exec_path = r"d:\AI Desktop Agent\desktop_client\src\services\chatStreamExecutor.ts"
if os.path.exists(stream_exec_path):
    with open(stream_exec_path, "r", encoding="utf-8") as f:
        se = f.read()

    # Claude content_block_delta feedStreamingText
    claude_old = """              outputChars += text.length;
              sessionStore.appendStreamContent(sessionId, assistantMessageId, text, false);
            }
            return false;
          }"""
    claude_new = """              outputChars += text.length;
              sessionStore.appendStreamContent(sessionId, assistantMessageId, text, false);
              realtimeVoiceService.feedStreamingText(text, false);
            }
            return false;
          }"""
    if claude_old in se:
        se = se.replace(claude_old, claude_new)
        print("[PASS] chatStreamExecutor.ts Claude stream linked to feedStreamingText")

    # Think tag boundary parts[1] / sub[1] feedStreamingText
    think_end_old = """                if (parts[1]) {
                  outputChars += parts[1].length;
                  sessionStore.appendStreamContent(sessionId, assistantMessageId, parts[1], false);
                }"""
    think_end_new = """                if (parts[1]) {
                  outputChars += parts[1].length;
                  sessionStore.appendStreamContent(sessionId, assistantMessageId, parts[1], false);
                  realtimeVoiceService.feedStreamingText(parts[1], false);
                }"""
    if think_end_old in se:
        se = se.replace(think_end_old, think_end_new)
        print("[PASS] chatStreamExecutor.ts think boundary linked to feedStreamingText")

    # Inner think end sub[1]
    inner_sub_old = """                  if (sub[1]) {
                    outputChars += sub[1].length;
                    sessionStore.appendStreamContent(sessionId, assistantMessageId, sub[1], false);
                  }"""
    inner_sub_new = """                  if (sub[1]) {
                    outputChars += sub[1].length;
                    sessionStore.appendStreamContent(sessionId, assistantMessageId, sub[1], false);
                    realtimeVoiceService.feedStreamingText(sub[1], false);
                  }"""
    if inner_sub_old in se:
        se = se.replace(inner_sub_old, inner_sub_new)
        print("[PASS] chatStreamExecutor.ts inner think sub linked to feedStreamingText")

    # Prefix before think
    prefix_think_old = """              if (parts[0]) {
                outputChars += parts[0].length;
                sessionStore.appendStreamContent(sessionId, assistantMessageId, parts[0], false);
              }"""
    prefix_think_new = """              if (parts[0]) {
                outputChars += parts[0].length;
                sessionStore.appendStreamContent(sessionId, assistantMessageId, parts[0], false);
                realtimeVoiceService.feedStreamingText(parts[0], false);
              }"""
    if prefix_think_old in se:
        se = se.replace(prefix_think_old, prefix_think_new)
        print("[PASS] chatStreamExecutor.ts prefix think linked to feedStreamingText")

    with open(stream_exec_path, "w", encoding="utf-8") as f:
        f.write(se)

# 4. Patch realtimeVoiceService.ts
voice_service_path = r"d:\AI Desktop Agent\desktop_client\src\services\realtimeVoiceService.ts"
if os.path.exists(voice_service_path):
    with open(voice_service_path, "r", encoding="utf-8") as f:
        rvs = f.read()

    if "import { useSessionStore } from '../stores/sessionStore';" not in rvs:
        rvs = "import { useSessionStore } from '../stores/sessionStore';\n" + rvs

    # Use current session's preset if available, and apply volume
    old_active_preset = """    const ttsStore = useTtsStore.getState();
    const configStore = useConfigStore.getState();
    const activePreset = configStore.getActivePreset();"""

    new_active_preset = """    const ttsStore = useTtsStore.getState();
    const configStore = useConfigStore.getState();
    const currentSession = useSessionStore.getState().getCurrentSession();
    const sessionPreset = currentSession?.presetId
      ? configStore.agentPresets.find((p: any) => p && p.id === currentSession.presetId)
      : null;
    const activePreset = sessionPreset || configStore.getActivePreset();"""

    if old_active_preset in rvs:
        rvs = rvs.replace(old_active_preset, new_active_preset)
        print("[PASS] realtimeVoiceService.ts session preset priority patched")

    # Set volume on audio
    old_audio_create = """          const mime = res.data.audioFormat || 'audio/wav';
          const audio = new Audio(`data:${mime};base64,${res.data.audioBase64}`);
          this.currentAudio = audio;"""

    new_audio_create = """          const mime = res.data.audioFormat || 'audio/wav';
          const audio = new Audio(`data:${mime};base64,${res.data.audioBase64}`);
          audio.volume = Math.max(0, Math.min(1, (ttsStore.volume ?? 85) / 100));
          this.currentAudio = audio;
          console.log(`[RealtimeVoiceService] 朗读单句 [${targetVoice}] (音量 ${Math.round(audio.volume * 100)}%):`, sentence);"""

    if old_audio_create in rvs:
        rvs = rvs.replace(old_audio_create, new_audio_create)
        print("[PASS] realtimeVoiceService.ts audio volume & logging applied")

    # Also apply volume in playViaGptSovits
    old_sovits_audio = """      const audioUrl = URL.createObjectURL(blob);
      const audio = new Audio(audioUrl);
      this.currentAudio = audio;"""

    new_sovits_audio = """      const audioUrl = URL.createObjectURL(blob);
      const audio = new Audio(audioUrl);
      audio.volume = Math.max(0, Math.min(1, (useTtsStore.getState().volume ?? 85) / 100));
      this.currentAudio = audio;
      console.log(`[RealtimeVoiceService] 直连 SoVITS 朗读单句 [${voiceName}] (音量 ${Math.round(audio.volume * 100)}%):`, text);"""

    if old_sovits_audio in rvs:
        rvs = rvs.replace(old_sovits_audio, new_sovits_audio)
        print("[PASS] realtimeVoiceService.ts direct SoVITS audio volume applied")

    # Also apply volume in playViaWebSpeech
    old_web_speech = """      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'zh-CN';
      utterance.rate = 1.05;
      utterance.pitch = 1.0;"""

    new_web_speech = """      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'zh-CN';
      utterance.rate = 1.05;
      utterance.pitch = 1.0;
      utterance.volume = Math.max(0, Math.min(1, (useTtsStore.getState().volume ?? 85) / 100));
      console.log(`[RealtimeVoiceService] Web Speech 降级朗读单句 (音量 ${Math.round(utterance.volume * 100)}%):`, text);"""

    if old_web_speech in rvs:
        rvs = rvs.replace(old_web_speech, new_web_speech)
        print("[PASS] realtimeVoiceService.ts Web Speech volume applied")

    with open(voice_service_path, "w", encoding="utf-8") as f:
        f.write(rvs)

print("[DONE] All auto-speak & broadcast pipeline patches applied.")
