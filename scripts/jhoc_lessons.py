#!/usr/bin/env python3
"""JHOC Canonical Lessons CLI.

Provides mechanical ingestion, atomic lock-protected appending,
and fast querying of canonical JHOC lessons.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.lessons import LessonsAccumulator, LessonsStore  # noqa: E402


def cmd_list(args: argparse.Namespace) -> None:
    store = LessonsStore(ROOT / "docs" / "lessons")
    lessons = store.all_lessons()
    print(f"Total Canonical Lessons in JHOC: {len(lessons)}")
    print("-" * 75)
    for l in lessons:
        print(f"[{l.source_file}] #{l.lesson_id:<5} | {l.title}")


def cmd_search(args: argparse.Namespace) -> None:
    store = LessonsStore(ROOT / "docs" / "lessons")
    results = store.find_by_keyword(args.keyword)
    print(f"Found {len(results)} matching lessons for keyword '{args.keyword}':")
    print("-" * 75)
    for l in results:
        print(f"\n[LESSON #{l.lesson_id}] {l.title} ({l.source_file})")
        print(f"  症状: {l.symptom[:100]}...")
        print(f"  根因: {l.root_cause[:100]}...")
        print(f"  规约: {l.rule[:100]}...")


def cmd_show(args: argparse.Namespace) -> None:
    store = LessonsStore(ROOT / "docs" / "lessons")
    l = store.get_by_id(args.id)
    if not l:
        print(f"Lesson not found: {args.id}", file=sys.stderr)
        sys.exit(1)
    print(f"\n================ LESSON #{l.lesson_id} ================")
    print(f"标题: {l.title}")
    print(f"分类: {l.category} ({l.source_file})")
    print(f"---------------- 症状 ----------------\n{l.symptom}")
    print(f"---------------- 根因 ----------------\n{l.root_cause}")
    print(f"---------------- 规约 ----------------\n{l.rule}")
    print("====================================================\n")


def cmd_add(args: argparse.Namespace) -> None:
    accumulator = LessonsAccumulator(ROOT / "docs" / "lessons")
    entry = accumulator.append_lesson(
        category=args.category,
        title=args.title,
        symptom=args.symptom,
        root_cause=args.root,
        rule=args.rule,
        lesson_id=args.id,
    )
    print(f"[OK] Successfully appended LESSON #{entry.lesson_id} to {entry.source_file}!")
    print(f"  标题: {entry.title}")


def main() -> None:
    parser = argparse.ArgumentParser(description="JHOC Lessons Management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser("list", help="List all canonical lessons")
    p_list.set_defaults(func=cmd_list)

    # search
    p_search = subparsers.add_parser("search", help="Search lessons by keyword")
    p_search.add_argument("keyword", help="Search keyword")
    p_search.set_defaults(func=cmd_search)

    # show
    p_show = subparsers.add_parser("show", help="Show full content of a specific lesson")
    p_show.add_argument("id", help="Lesson ID (e.g. 147, 95)")
    p_show.set_defaults(func=cmd_show)

    # add
    p_add = subparsers.add_parser("add", help="Add a new lesson with atomic lock protection")
    p_add.add_argument("--category", "-c", required=True, choices=["cognitive", "process", "tool", "testing"], help="Category")
    p_add.add_argument("--title", "-t", required=True, help="Lesson title")
    p_add.add_argument("--symptom", "-s", required=True, help="Symptom description")
    p_add.add_argument("--root", "-r", required=True, help="Root cause analysis")
    p_add.add_argument("--rule", "-u", required=True, help="Enforced rule/protocol")
    p_add.add_argument("--id", default=None, help="Explicit lesson ID (optional)")
    p_add.set_defaults(func=cmd_add)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
