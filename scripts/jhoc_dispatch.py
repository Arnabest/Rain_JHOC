"""Dispatch one workflow task to native JHOC providers and await responses."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
import time
from uuid import uuid4


def rpc(host: str, port: int, request: dict[str, object]) -> dict:
    with socket.create_connection((host, port), timeout=5) as connection:
        connection.sendall((json.dumps(request, ensure_ascii=True) + "\n").encode("utf-8"))
        line = connection.makefile("rb").readline()
    if not line:
        raise ConnectionError("JHOC endpoint returned no response")
    value = json.loads(line.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JHOC endpoint response must be an object")
    return value


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def build_dispatched_context(prompt: str, consumer_id: str, workspace_root: str | Path | None = None) -> dict[str, object]:
    try:
        from datetime import timedelta
        from jhoc.context.orchestrator import ContextOrchestrator, ContextSource
        orchestrator = ContextOrchestrator()
        pass_a = orchestrator.pass_a(prompt, {"caller": "jhoc_dispatch"}, policy_ref="jhoc-governance-v1.0")

        # 遵循职责分离与服务自治：召回层向知识索引插件发起标准化检索申请
        from jhoc.plugins.lessons import LessonsPlugin
        lessons_plugin = LessonsPlugin()
        query_res = lessons_plugin.invoke({"action": "query", "query": prompt, "limit": 2})
        raw_lessons = query_res.get("lessons", [])

        selected_lessons = [
            {
                "lesson_id": l["lesson_id"],
                "title": l["title"],
                "symptom": l["symptom"],
                "rule": l["rule"],
                "source": l["source_file"],
            }
            for l in raw_lessons
        ]

        from jhoc.context.sanitizer import DataSanitizer

        allowed_consumers = frozenset({consumer_id, "codex-cli", "deepseek-harness", "agy-cli"})
        target_ws = str(Path(workspace_root).resolve()) if workspace_root else str(ROOT.resolve())
        from jhoc.shelf import SkillShelfLoader
        shelf_loader = SkillShelfLoader(ROOT / ".agents" / "skills")
        shelf_brief = shelf_loader.export_shelf_manifest_brief()

        gov_source = ContextSource(
            source_id="jhoc:governance:active",
            data={
                "environment": "JHOC V5 Native",
                "rules": [
                    "RULE_ONLINE_QUERY_SAFE",
                    "RULE_MUTATION_APPROVAL_REQUIRED",
                    "RULE_READ_ONLY_SAFE",
                    "RULE_DENY_POLICY_MUTATION",
                    "RULE_DENY_RAW_SECRETS",
                ],
                "workspace": target_ws,
                "available_shelf_skills": shelf_brief,
                "mode": "FAIL_CLOSED",
            },
            sensitivity="INTERNAL",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            allowed_consumers=allowed_consumers,
            provenance=("docs/governance/jhoc-governance-policy-bundle-v1.json",),
        )

        # 遵循 Rule 3 双平面物理隔离：必须经 DataSanitizer 清洗去指令化，永远保持字面量
        sanitized_lessons = DataSanitizer.sanitize_source({"active_lessons": selected_lessons})
        lesson_source = ContextSource(
            source_id="jhoc:lessons:active",
            data=sanitized_lessons.content,
            sensitivity="INTERNAL",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            allowed_consumers=allowed_consumers,
            provenance=("docs/lessons/", f"digest:{sanitized_lessons.digest}"),
            confidence=sanitized_lessons.purity_score,
        )

        # 遵循 L1 优先常驻 + L2 意图按需检索：召回热会话与架构精炼记忆
        from jhoc.memory_store.retriever import MemoryRetriever
        mem_retriever = MemoryRetriever()
        active_memory = mem_retriever.retrieve_active_memory_bundle(prompt)

        sanitized_memory = DataSanitizer.sanitize_source({"active_memory": active_memory})
        memory_source = ContextSource(
            source_id="jhoc:memory:active",
            data=sanitized_memory.content,
            sensitivity="INTERNAL",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            allowed_consumers=allowed_consumers,
            provenance=("logs/p19-memory.sqlite", f"digest:{sanitized_memory.digest}"),
            confidence=sanitized_memory.purity_score,
        )

        # 遵循意图前置安检与脚手架强制装配：若命中货架技能，物理挂载至 context package
        from jhoc.intent.classifier import IntentClassifier
        classifier = IntentClassifier()
        intent_decision = classifier.classify(prompt)

        skill_source = None
        skill_payload = None
        if intent_decision.enforced_scaffolding:
            scaffold_path = ROOT / intent_decision.enforced_scaffolding
            if scaffold_path.is_file():
                scaffold_content = scaffold_path.read_text(encoding="utf-8", errors="ignore")
                sanitized_skill = DataSanitizer.sanitize_source({
                    "intent": intent_decision.intent.value,
                    "scaffolding_path": intent_decision.enforced_scaffolding,
                    "content": scaffold_content,
                })
                skill_source = ContextSource(
                    source_id="jhoc:skill:active",
                    data=sanitized_skill.content,
                    sensitivity="INTERNAL",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    allowed_consumers=allowed_consumers,
                    provenance=(intent_decision.enforced_scaffolding, f"digest:{sanitized_skill.digest}"),
                    confidence=intent_decision.confidence,
                )
                skill_payload = {
                    "intent": intent_decision.intent.value,
                    "scaffolding_path": intent_decision.enforced_scaffolding,
                    "confidence": intent_decision.confidence,
                }

        sources = [gov_source, lesson_source, memory_source]
        authorized = {"jhoc:governance:active", "jhoc:lessons:active", "jhoc:memory:active"}
        if skill_source:
            sources.append(skill_source)
            authorized.add("jhoc:skill:active")

        package = orchestrator.pass_b(
            pass_a,
            tuple(sources),
            authorized_source_ids=frozenset(authorized),
            consumer_id=consumer_id,
            resource_plan_ref="plan:default:v1",
            redact_keys=frozenset({"api_key", "token", "secret", "password"}),
        )
        return {
            "snapshot_id": package.snapshot_id,
            "policy_ref": pass_a.policy_ref,
            "rules": list(gov_source.data.get("rules", [])),
            "lessons": selected_lessons,
            "memory": active_memory,
            "skill": skill_payload,
            "shelf": shelf_brief,
            "workspace": gov_source.data.get("workspace"),
            "sensitivity": gov_source.sensitivity,
        }
    except Exception:
        return {"policy_ref": "jhoc-governance-v1.0", "snapshot_id": "fallback:unorchestrated"}


def dispatch(host: str, port: int, providers: tuple[str, ...], session_id: str, prompt: str, timeout: float) -> dict:
    health = rpc(host, port, {"op": "health"})
    if not health.get("ok") or not health.get("running"):
        raise RuntimeError(f"JHOC supervisor is not ready: {health}")
    requests = []
    for provider_id in providers:
        context_data = build_dispatched_context(prompt, provider_id)
        result = rpc(host, port, {
            "op": "submit",
            "provider_id": provider_id,
            "payload": {
                "session_id": session_id,
                "prompt": prompt,
                "context": context_data,
                "dispatch_id": str(uuid4()),
            },
        })
        if not result.get("ok"):
            raise RuntimeError(f"provider dispatch rejected: {provider_id}")
        requests.append({"provider_id": provider_id, "correlation_id": result["correlation_id"]})
    deadline = time.monotonic() + max(0.1, timeout)
    while time.monotonic() < deadline:
        complete = True
        for request in requests:
            response = rpc(host, port, {"op": "response", "correlation_id": request["correlation_id"]})
            if response.get("ok") and response.get("response"):
                request["response"] = response["response"]
            else:
                complete = False
        if complete:
            break
        time.sleep(0.1)
    for request in requests:
        response = request.get("response")
        request["status"] = response.get("status", "timeout") if isinstance(response, dict) else "timeout"
        request["final"] = bool(isinstance(response, dict) and response.get("payload", {}).get("final"))
        request["session_match"] = bool(isinstance(response, dict) and response.get("session_id") == session_id)
    accepted = [item for item in requests if item["status"] == "accepted" and item["final"] and item["session_match"]]
    return {
        "schema_version": "jhoc-dispatch/v1",
        "session_id": session_id,
        "prompt": prompt,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": {"host": host, "port": port},
        "requests": requests,
        "accepted_final_provider_count": len({item["provider_id"] for item in accepted}),
        "collaboration_gate": len({item["provider_id"] for item in accepted}) >= 2,
        "probe_only": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--provider", action="append", dest="providers", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args(argv)
    session_id = args.session_id or f"jhoc-{uuid4()}"
    result = dispatch(args.host, args.port, tuple(dict.fromkeys(args.providers)), session_id, args.prompt, args.timeout)
    if args.artifact:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["collaboration_gate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
