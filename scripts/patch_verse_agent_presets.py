import os
import re

print("[START] Refining Verse Agent Presets and TTS Voice Decoupling Patch...")

# 1. Patch MessageItem.tsx
msg_item_path = r"d:\AI Desktop Agent\desktop_client\src\components\chat\MessageItem.tsx"
with open(msg_item_path, "r", encoding="utf-8") as f:
    mi = f.read()

if "import { useConfigStore } from '../../stores/configStore';" not in mi:
    mi = "import { useConfigStore } from '../../stores/configStore';\n" + mi

# Ensure (p: any) in safe callback
mi = mi.replace("find(p => p.id === currentSession.presetId)", "find((p: any) => p && p.id === currentSession.presetId)")

with open(msg_item_path, "w", encoding="utf-8") as f:
    f.write(mi)
print("[PASS] MessageItem.tsx import and types fixed")

# 2. Patch configStore.ts
config_path = r"d:\AI Desktop Agent\desktop_client\src\stores\configStore.ts"
with open(config_path, "r", encoding="utf-8") as f:
    cfg = f.read()

# Make sure getActivePreset checks activePresetId and implement setActivePresetId + setEditingPresetId
target_marker = "  // Agent Presets\n  getActivePreset: () => {\n    const state = get();\n    return state.agentPresets.find(p => p.id === state.selectedPresetId)"

replacement = """  // Agent Presets
  getActivePreset: () => {
    const state = get();
    return state.agentPresets.find(p => p.id === state.activePresetId)
      || state.agentPresets.find(p => p.id === state.selectedPresetId)
      || state.agentPresets.find(p => p.isDefault)
      || state.agentPresets[0]
      || null;
  },

  setActivePresetId: (id: string) => set((state) => {
    const targetPreset = state.agentPresets.find(p => p.id === id);
    safeSetStorage(STORAGE_KEY_ACTIVE_PRESET, id);
    if (!targetPreset) return { activePresetId: id, selectedPresetId: id };

    let nextModelId = state.selectedModelId;
    if (targetPreset.boundModel) {
      nextModelId = targetPreset.boundModel;
      safeSetStorage(STORAGE_KEY_SELECTED_MODEL, nextModelId);
    }

    let nextThinkingLevel = state.thinkingLevel;
    let nextThinkingMode = state.isThinkingMode;
    if (targetPreset.thinkingLevel) {
      nextThinkingLevel = targetPreset.thinkingLevel;
      nextThinkingMode = nextThinkingLevel !== 'off';
      safeSetStorage(STORAGE_KEY_THINKING_LEVEL, nextThinkingLevel);
      safeSetStorage(STORAGE_KEY_THINKING_MODE, String(nextThinkingMode));
    }

    const matched = state.models.find(m => m.id === nextModelId);

    return {
      activePresetId: id,
      selectedPresetId: id,
      selectedModelId: nextModelId,
      thinkingLevel: nextThinkingLevel,
      isThinkingMode: nextThinkingMode,
      metrics: {
        ...state.metrics,
        activeModel: matched ? matched.name : state.metrics.activeModel,
      }
    };
  }),

  setEditingPresetId: (id: string | null) => set({ editingPresetId: id, selectedPresetId: id }),"""

# Find and replace getActivePreset block
pattern = r"  // Agent Presets\s+getActivePreset: \(\) => \{\s+const state = get\(\);\s+return state\.agentPresets\.find\(p => p\.id === state\.selectedPresetId\)\s+\|\| state\.agentPresets\.find\(p => p\.isDefault\)\s+\|\| state\.agentPresets\[0\]\s+\|\| null;\s+\},"

if re.search(pattern, cfg):
    cfg = re.sub(pattern, replacement, cfg, count=1)
    print("[PASS] Replaced getActivePreset with activePresetId + setActivePresetId + setEditingPresetId")
else:
    print("[WARN] Pattern for getActivePreset did not match regex directly, checking if already replaced")

with open(config_path, "w", encoding="utf-8") as f:
    f.write(cfg)
print("[PASS] configStore.ts updated")
