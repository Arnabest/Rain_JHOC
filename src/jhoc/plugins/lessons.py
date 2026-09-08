from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.lessons.accumulator import LessonsAccumulator
from jhoc.lessons.store import LessonsStore
from jhoc.plugins.protocol import HealthStatus, PluginLifecycle, PluginProtocol


class LessonsPlugin(PluginProtocol):
    """Native JHOC Plugin implementing the standard PluginProtocol for Canonical Lessons."""

    def __init__(self, lessons_dir: Path | str | None = None) -> None:
        self._root = Path(lessons_dir) if lessons_dir else Path(__file__).resolve().parents[3] / "docs" / "lessons"
        self.store = LessonsStore(self._root)
        self.accumulator = LessonsAccumulator(self._root)
        self._drained = False
        self._shutdown = False
        self._config: dict[str, Any] = {}

    def describe(self) -> Mapping[str, Any]:
        return {
            "plugin_id": "jhoc.lessons",
            "protocol_version": "1.0",
            "capabilities": ["list", "search", "get", "add", "query"],
            "lifecycle": PluginLifecycle.READY.value if not self._shutdown else PluginLifecycle.STOPPED.value,
        }

    def health(self) -> Mapping[str, Any]:
        if self._shutdown:
            return {"status": HealthStatus.UNAVAILABLE.value}
        return {
            "status": HealthStatus.READY.value,
            "lessons_count": len(self.store.all_lessons()),
            "root_path": str(self._root),
        }

    def initialize(self, config: Mapping[str, Any]) -> None:
        self._config = dict(config)
        custom_root = config.get("lessons_dir")
        if custom_root:
            self._root = Path(custom_root)
            self.store = LessonsStore(self._root)
            self.accumulator = LessonsAccumulator(self._root)
        self.store.load()

    def validate(self, request: Mapping[str, Any]) -> None:
        if not isinstance(request, Mapping):
            raise ContractError("Request must be a mapping", ErrorCode.INVALID_CONTRACT)
        action = request.get("action")
        if action not in {"list", "search", "get", "add", "query"}:
            raise ContractError(f"Unsupported action: {action}", ErrorCode.PLUGIN_VALIDATION_FAILED)

        if action == "query" and not str(request.get("query", "")).strip():
            raise ContractError("query action requires non-empty 'query'", ErrorCode.PLUGIN_VALIDATION_FAILED)
        elif action == "search" and not request.get("keyword"):
            raise ContractError("search action requires 'keyword'", ErrorCode.PLUGIN_VALIDATION_FAILED)
        elif action == "get" and not request.get("id"):
            raise ContractError("get action requires 'id'", ErrorCode.PLUGIN_VALIDATION_FAILED)
        elif action == "add":
            for field in ("category", "title", "symptom", "root", "rule"):
                if not str(request.get(field, "")).strip():
                    raise ContractError(f"add action requires '{field}'", ErrorCode.PLUGIN_VALIDATION_FAILED)

    def invoke(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.validate(request)
        action = request["action"]

        if action == "query":
            query_text = str(request["query"])
            limit = int(request.get("limit", 2))
            results = [asdict(l) for l in self.store.query(query_text, limit=limit)]
            return {"status": "OK", "count": len(results), "lessons": results}

        elif action == "list":
            lessons = [asdict(l) for l in self.store.all_lessons()]
            return {"status": "OK", "count": len(lessons), "lessons": lessons}

        elif action == "search":
            results = [asdict(l) for l in self.store.find_by_keyword(str(request["keyword"]))]
            return {"status": "OK", "count": len(results), "lessons": results}

        elif action == "get":
            l = self.store.get_by_id(str(request["id"]))
            if not l:
                return {"status": "NOT_FOUND", "lesson_id": request["id"]}
            return {"status": "OK", "lesson": asdict(l)}

        elif action == "add":
            entry = self.accumulator.append_lesson(
                category=str(request["category"]),
                title=str(request["title"]),
                symptom=str(request["symptom"]),
                root_cause=str(request["root"]),
                rule=str(request["rule"]),
                lesson_id=request.get("id"),
            )
            # 刷新缓存
            self.store = LessonsStore(self._root)
            self.store.load()
            return {"status": "CREATED", "lesson": asdict(entry)}

        return {"status": "UNHANDLED"}

    def stream(self, request: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
        result = self.invoke(request)
        yield result
        yield {"done": True}

    def cancel(self, work_id: str) -> None:
        pass

    def checkpoint(self) -> Mapping[str, Any]:
        return {"lessons_count": len(self.store.all_lessons()), "root": str(self._root)}

    def drain(self) -> None:
        self._drained = True

    def shutdown(self) -> None:
        self._shutdown = True
