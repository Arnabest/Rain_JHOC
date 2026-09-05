#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_notebook_insights.py - 自动解析并抽取目标仓库中全部 Jupyter Notebook 与脚本的核心代码与元数据
"""

import os
import sys
import json
import argparse
from collections import defaultdict

def parse_notebook(filepath):
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            nb = json.load(f)
    except Exception as e:
        return {"error": str(e)}

    cells = nb.get("cells", [])
    markdown_headings = []
    key_imports = set()
    class_defs = []
    func_defs = []
    urls = []
    code_lines_count = 0
    markdown_lines_count = 0
    sample_code_snippets = []

    for cell in cells:
        cell_type = cell.get("cell_type", "")
        source = cell.get("source", [])
        if isinstance(source, list):
            text = "".join(source)
        else:
            text = str(source)

        if cell_type == "markdown":
            lines = text.splitlines()
            markdown_lines_count += len(lines)
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("#"):
                    markdown_headings.append(stripped)
                if "http://" in stripped or "https://" in stripped:
                    for part in stripped.split():
                        if part.startswith("http://") or part.startswith("https://"):
                            urls.append(part.strip("()[]<>'\""))
        elif cell_type == "code":
            lines = text.splitlines()
            code_lines_count += len(lines)
            for line in lines:
                sline = line.strip()
                if sline.startswith("import ") or sline.startswith("from "):
                    key_imports.add(sline)
                elif sline.startswith("class ") and ":" in sline:
                    class_defs.append(sline.split(":")[0].strip())
                elif sline.startswith("def ") and "(" in sline:
                    func_defs.append(sline.split("(")[0].replace("def ", "").strip())

            if len(sample_code_snippets) < 3 and any(k in text for k in ["class ", "def ", "loss", "torch", "nn.Module", "ray.", "vllm"]):
                snippet = "\n".join(lines[:15])
                if len(lines) > 15:
                    snippet += "\n# ... (truncated)"
                sample_code_snippets.append(snippet)

    return {
        "headings": markdown_headings,
        "imports": sorted(list(key_imports)),
        "class_defs": class_defs,
        "func_defs": func_defs,
        "urls": list(set(urls)),
        "code_lines": code_lines_count,
        "markdown_lines": markdown_lines_count,
        "sample_snippets": sample_code_snippets
    }

def main():
    parser = argparse.ArgumentParser(description="Extract insights from modern_genai_bilibili repo")
    parser.add_argument("--root", default=r"F:\desktop on f\modern_genai_bilibili-main", help="Target repo root path")
    parser.add_argument("--output", default=r"scratch/repo_code_inventory.json", help="Output JSON path")
    parser.add_argument("--verify", action="store_true", help="Print verification summary only")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.exists(root):
        print(f"[FAIL] Target path not found: {root}")
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    inventory = {}
    stats_by_module = defaultdict(lambda: {"count": 0, "code_lines": 0, "markdown_lines": 0, "classes": 0, "funcs": 0})

    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in [".ipynb", ".py", ".sh", ".ts"]:
                full_path = os.path.join(dirpath, f)
                rel_path = os.path.relpath(full_path, root)
                module_name = rel_path.split(os.sep)[0]

                if ext == ".ipynb":
                    info = parse_notebook(full_path)
                else:
                    # Generic script parsing
                    try:
                        with open(full_path, "r", encoding="utf-8", errors="ignore") as sf:
                            content = sf.read()
                        lines = content.splitlines()
                        info = {
                            "headings": [f"# Script: {f}"],
                            "imports": [l.strip() for l in lines if l.strip().startswith(("import ", "from "))],
                            "class_defs": [l.strip().split(":")[0] for l in lines if l.strip().startswith("class ")],
                            "func_defs": [l.strip().split("(")[0].replace("def ", "") for l in lines if l.strip().startswith("def ")],
                            "urls": [],
                            "code_lines": len(lines),
                            "markdown_lines": 0,
                            "sample_snippets": ["\n".join(lines[:20])]
                        }
                    except Exception as e:
                        info = {"error": str(e)}

                inventory[rel_path] = info

                if "error" not in info:
                    stats = stats_by_module[module_name]
                    stats["count"] += 1
                    stats["code_lines"] += info.get("code_lines", 0)
                    stats["markdown_lines"] += info.get("markdown_lines", 0)
                    stats["classes"] += len(info.get("class_defs", []))
                    stats["funcs"] += len(info.get("func_defs", []))

    with open(args.output, "w", encoding="utf-8") as out_f:
        json.dump(inventory, out_f, ensure_ascii=False, indent=2)

    print(f"[PASS] Successfully scanned {len(inventory)} code/notebook files.")
    print(f"[INFO] Inventory written to: {args.output}")
    print("\n[SUMMARY BY MODULE]:")
    for mod, st in sorted(stats_by_module.items()):
        print(f"  - Module '{mod:15}': {st['count']:3d} files | {st['code_lines']:6d} code lines | {st['markdown_lines']:6d} md lines | {st['classes']:3d} classes | {st['funcs']:4d} funcs")

if __name__ == "__main__":
    main()
