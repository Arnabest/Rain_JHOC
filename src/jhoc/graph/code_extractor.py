from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any

from jhoc.contracts.errors import ContractError
from .store import GraphNode, GraphRelation, GraphStore


class CodeGraphExtractor:
    """Extracts static code entities and relationship projections from Python source files."""

    @classmethod
    def extract_from_source(
        cls,
        file_path: str,
        source_code: str,
        module_name: str,
    ) -> tuple[list[GraphNode], list[GraphRelation]]:
        """Parses Python AST and extracts CodeEntity nodes and architectural relations."""
        nodes: list[GraphNode] = []
        relations: list[GraphRelation] = []
        known_node_ids: set[str] = set()

        def add_node(node_id: str, node_type: str = "CodeEntity") -> None:
            if node_id not in known_node_ids:
                nodes.append(GraphNode(node_id, node_type))
                known_node_ids.add(node_id)

        def add_relation(
            src: str,
            tgt: str,
            rel_type: str,
            confidence: float = 1.0,
            quality: str = "VERIFIED",
        ) -> None:
            if src in known_node_ids and tgt in known_node_ids:
                rel_id = f"rel:code:{hashlib.sha256(f'{src}:{rel_type}:{tgt}'.encode()).hexdigest()[:16]}"
                relations.append(
                    GraphRelation(
                        relation_id=rel_id,
                        source_node=src,
                        target_node=tgt,
                        relation_type=rel_type,
                        confidence=confidence,
                        source_ref=file_path,
                        verification_status="VERIFIED",
                        quality=quality,
                    )
                )

        try:
            tree = ast.parse(source_code, filename=file_path)
        except SyntaxError:
            # Concurrency tolerance: If file was partially written, yield briefly and re-read
            import time
            time.sleep(0.02)
            try:
                p = Path(file_path)
                if p.is_file():
                    fresh_code = p.read_text(encoding="utf-8")
                    tree = ast.parse(fresh_code, filename=file_path)
                else:
                    return nodes, relations
            except Exception:
                return nodes, relations

        # 1. Module Level Node
        mod_node_id = f"code:module:{module_name}"
        add_node(mod_node_id)

        # 2. Imports -> depends_on
        imported_names: dict[str, str] = {}
        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    dep_id = f"code:module:{alias.name}"
                    add_node(dep_id)
                    add_relation(mod_node_id, dep_id, "depends_on")
                    imported_names[alias.asname or alias.name] = dep_id
            elif isinstance(stmt, ast.ImportFrom):
                if stmt.module:
                    dep_id = f"code:module:{stmt.module}"
                    add_node(dep_id)
                    add_relation(mod_node_id, dep_id, "depends_on")
                    for alias in stmt.names:
                        imported_names[alias.asname or alias.name] = f"{dep_id}.{alias.name}"

        # 3. Classes and Functions
        class_methods: dict[str, list[str]] = {}
        for stmt in tree.body:
            if isinstance(stmt, ast.ClassDef):
                cls_node_id = f"code:class:{module_name}.{stmt.name}"
                add_node(cls_node_id)
                add_relation(cls_node_id, mod_node_id, "belongs_to")

                # Inheritance -> derived_from
                for base in stmt.bases:
                    if isinstance(base, ast.Name):
                        base_id = imported_names.get(base.id, f"code:class:{module_name}.{base.id}")
                        add_node(base_id)
                        add_relation(cls_node_id, base_id, "derived_from")

                # Methods
                for item in stmt.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_id = f"code:func:{module_name}.{stmt.name}.{item.name}"
                        add_node(method_id)
                        add_relation(method_id, cls_node_id, "belongs_to")
                        class_methods.setdefault(cls_node_id, []).append(method_id)

            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_node_id = f"code:func:{module_name}.{stmt.name}"
                add_node(func_node_id)
                add_relation(func_node_id, mod_node_id, "belongs_to")

        # 4. Test Verification Linkage
        if "test_" in module_name:
            target_module = module_name.replace("tests.", "jhoc.").replace("test_", "")
            target_mod_id = f"code:module:{target_module}"
            add_node(target_mod_id)
            add_relation(mod_node_id, target_mod_id, "verified_by", confidence=0.9)

        return nodes, relations

    @classmethod
    def index_directory(
        cls,
        dir_path: str | Path,
        graph_store: Any,
        *,
        package_prefix: str = "jhoc",
    ) -> int:
        """Recursively parses all Python files in a directory and indexes them into graph_store."""
        root = Path(dir_path).resolve()
        if not root.is_dir():
            raise ContractError(f"directory not found: {root}")

        total_relations_added = 0
        all_nodes: list[GraphNode] = []
        all_relations: list[GraphRelation] = []

        for py_file in root.rglob("*.py"):
            rel_parts = py_file.relative_to(root).with_suffix("").parts
            mod_name = f"{package_prefix}.{'.'.join(rel_parts)}" if package_prefix else ".".join(rel_parts)
            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue

            nodes, rels = cls.extract_from_source(str(py_file), content, mod_name)
            all_nodes.extend(nodes)
            all_relations.extend(rels)

        # Ensure all nodes are added before relations are attached
        for node in all_nodes:
            graph_store.add_node(node)

        for rel in all_relations:
            try:
                graph_store.add_relation(rel)
                total_relations_added += 1
            except Exception:
                # Ignore idempotent relation conflicts or duplicate edges
                pass

        return total_relations_added
