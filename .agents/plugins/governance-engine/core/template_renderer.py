"""Fixed template renderer for negative lessons and anti-impulse warnings.

Guarantees:
1. Pure structured field rendering (ID, symptom, rule, positive_action).
2. Never injects model-generated raw prose directly (prevents self-prompt injection).
3. Strictly adheres to Rule 7 (Zero-Emoji Discipline) and concise length (< 150 chars).
"""

from __future__ import annotations

from typing import Mapping


class LessonTemplateRenderer:
    """Safely renders verified negative lessons into bounded advisory prompts."""

    @classmethod
    def render_lesson_warning(cls, lesson: Mapping[str, str], *, positive_tool: str = "") -> str:
        lid = str(lesson.get("lesson_id", "GENERAL")).strip()
        rule = str(lesson.get("rule", "")).strip()
        symptom = str(lesson.get("symptom", "")).strip()

        # Sanitize any accidental emojis or carriage returns
        clean_rule = rule.replace("\n", " ").replace("\r", " ").strip()
        clean_symptom = symptom.replace("\n", " ").replace("\r", " ").strip()

        # Limit to 100 characters per field to prevent context inflation
        if len(clean_rule) > 100:
            clean_rule = clean_rule[:97] + "..."
        if len(clean_symptom) > 80:
            clean_symptom = clean_symptom[:77] + "..."

        action_hint = f" -> Positive Action: run '{positive_tool}'" if positive_tool else ""
        return f"[LESSON #{lid} WARNING] Anti-Pattern: {clean_symptom} | Invariant: {clean_rule}{action_hint}"

    @classmethod
    def render_ephemeral_package(
        cls,
        *,
        intent_name: str,
        scaffolding_path: str,
        target_tool: str = "",
        lesson_warning: str = "",
        gate_constraint: str = "",
    ) -> tuple[str, ...]:
        lines: list[str] = []
        # Line 1: Detected Intent & Scaffolding
        scaffold_str = f" | Shelf: {scaffolding_path}" if scaffolding_path else ""
        lines.append(f"[JHOC GOVERNANCE] Detected Intent: {intent_name}{scaffold_str}")

        # Line 2: Executable Target Tool
        if target_tool:
            lines.append(f"[JHOC TARGET TOOL] Executable CLI: {target_tool}")

        # Line 3: Structured Negative Lesson
        if lesson_warning:
            lines.append(lesson_warning)

        # Line 4: Current Gating Constraint
        if gate_constraint:
            lines.append(f"[GATE INVARIANT] {gate_constraint}")

        return tuple(lines)
