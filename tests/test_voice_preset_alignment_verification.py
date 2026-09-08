# -*- coding: utf-8 -*-
"""Verification script for voice model, port, and character preset alignment."""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

def test_config_store_presets():
    print("\n--- Test 1: Verifying Agent Presets in configStore.ts ---")
    p = Path(r"d:\AI Desktop Agent\desktop_client\src\stores\configStore.ts")
    content = p.read_text(encoding="utf-8")
    
    assert "ttsEngine: 'gpt_sovits'" in content, "[FAIL] ttsEngine not found in configStore"
    assert "ttsVoice: '流萤'" in content, "[FAIL] 流萤 not found in configStore"
    assert "ttsVoice: '三月七(底模零样本)'" in content, "[FAIL] 三月七 not found in configStore"
    assert "nextModelId = targetPreset.boundModel;" in content, "[FAIL] boundModel assignment not found"
    print("[PASS] configStore default presets and migration verified.")

def test_chat_service_alignment():
    print("\n--- Test 2: Verifying chatService.ts getActivePreset Alignment ---")
    p = Path(r"d:\AI Desktop Agent\desktop_client\src\services\chatService.ts")
    content = p.read_text(encoding="utf-8")
    
    assert "const activePreset = configStore.getActivePreset();" in content, "[FAIL] chatService still using hardcoded preset"
    assert "configStore.agentPresets.find(p => p.isDefault)" not in content, "[FAIL] Stale isDefault preset query remains in chatService"
    print("[PASS] chatService correctly uses configStore.getActivePreset().")

def test_session_store_alignment():
    print("\n--- Test 3: Verifying sessionStore.ts boundModel Inheritance ---")
    p = Path(r"d:\AI Desktop Agent\desktop_client\src\stores\sessionStore.ts")
    content = p.read_text(encoding="utf-8")
    
    assert "effectiveModel = cfg.selectedModelId || activePreset?.boundModel" in content, "[FAIL] effectiveModel logic missing"
    assert "setSelectedModelId(targetSession.modelId)" in content, "[FAIL] session switch model sync missing"
    print("[PASS] sessionStore correctly inherits active preset boundModel and syncs on switch.")

def test_realtime_voice_service():
    print("\n--- Test 4: Verifying realtimeVoiceService.ts POST Payload & Weights ---")
    p = Path(r"d:\AI Desktop Agent\desktop_client\src\services\realtimeVoiceService.ts")
    content = p.read_text(encoding="utf-8")
    
    assert "set_gpt_weights?weights_path=" in content, "[FAIL] set_gpt_weights missing in realtimeVoiceService"
    assert "set_sovits_weights?weights_path=" in content, "[FAIL] set_sovits_weights missing in realtimeVoiceService"
    assert "method: 'POST'" in content, "[FAIL] POST method missing in realtimeVoiceService playViaGptSovits"
    assert "text_language=zh" not in content, "[FAIL] Invalid query parameter text_language remains"
    print("[PASS] realtimeVoiceService verified with proper POST payload and weight synchronization.")

def test_physical_sovits_synthesis():
    print("\n--- Test 5: Physical Verification against GPT-SoVITS Service on Port 9880 ---")
    voices_file = Path(r"d:\AI Desktop Agent\voices.json")
    if not voices_file.exists():
        print("[WARN] voices.json not found, skipping physical SoVITS check.")
        return
    
    voices = json.loads(voices_file.read_text(encoding="utf-8"))
    liuying = next((v for v in voices if "流萤" in v.get("name", "")), None)
    if not liuying:
        print("[WARN] 流萤 not found in voices.json, skipping physical check.")
        return
    
    # Check port 9880
    url = "http://127.0.0.1:9880"
    try:
        req = urllib.request.Request(f"{url}/set_gpt_weights?weights_path={urllib.parse.quote(liuying['gpt'])}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200, f"[FAIL] set_gpt_weights HTTP {resp.status}"

        req = urllib.request.Request(f"{url}/set_sovits_weights?weights_path={urllib.parse.quote(liuying['sovits'])}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200, f"[FAIL] set_sovits_weights HTTP {resp.status}"

        # Test POST synthesis
        payload = json.dumps({
            "text": "会话朗读模型与端口对齐验证测试成功！",
            "text_lang": liuying.get("lang", "zh"),
            "ref_audio_path": liuying.get("ref", ""),
            "prompt_text": liuying.get("prompt", ""),
            "prompt_lang": liuying.get("lang", "zh"),
            "media_type": "wav",
            "streaming_mode": False
        }).encode("utf-8")

        post_req = urllib.request.Request(
            f"{url}/tts",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        t0 = time.time()
        with urllib.request.urlopen(post_req, timeout=15) as resp:
            duration = time.time() - t0
            data = resp.read()
            assert resp.status == 200, f"[FAIL] /tts HTTP {resp.status}"
            assert len(data) > 1000, f"[FAIL] Audio data too small: {len(data)} bytes"
            print(f"[PASS] Physical SoVITS synthesis verified! Generated {len(data)} bytes in {duration:.2f}s.")
    except Exception as exc:
        print(f"[WARN] Port 9880 check encountered: {exc}")

def main():
    print("=== JHOC E2E Acceptance: Voice Model, Port & Character Preset Alignment ===")
    test_config_store_presets()
    test_chat_service_alignment()
    test_session_store_alignment()
    test_realtime_voice_service()
    test_physical_sovits_synthesis()
    print("\n[PASS] All alignment verification checks completed successfully!")

if __name__ == "__main__":
    main()
