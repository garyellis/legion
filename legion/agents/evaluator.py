"""Deterministic post-loop evaluation for agent transcripts."""

from __future__ import annotations

from collections.abc import Sequence


def summarize_transcript(
    messages: Sequence[object],
    *,
    tokens_used: int,
    budget_exhausted: bool,
) -> str:
    """Summarize the ReAct transcript into a grounded result string."""

    status = "partial" if budget_exhausted else "complete"
    lines = [f"Result status: {status}", f"Tokens used: {tokens_used}"]

    final_answer = _extract_final_answer(messages)
    if final_answer:
        lines.append("Answer:")
        lines.append(final_answer)
    else:
        lines.append("Answer:")
        lines.append("No final answer produced.")

    findings = _extract_tool_findings(messages)
    if findings:
        lines.append("Findings:")
        lines.extend(findings)

    if budget_exhausted:
        lines.append("Budget exhausted before the loop reached a natural stop.")

    return "\n".join(lines)


def _extract_final_answer(messages: Sequence[object]) -> str:
    # Uses type().__name__ string comparison instead of isinstance() to avoid
    # a hard dependency on langchain_core.messages in this module.
    for message in reversed(messages):
        if type(message).__name__ != "AIMessage":
            continue
        if getattr(message, "tool_calls", None):
            continue
        text = _normalize_content(getattr(message, "content", ""))
        if text:
            return text
    return ""


def _extract_tool_findings(messages: Sequence[object]) -> list[str]:
    # See _extract_final_answer for rationale on type().__name__ pattern.
    findings: list[str] = []
    for message in messages:
        if type(message).__name__ != "ToolMessage":
            continue
        tool_name = getattr(message, "name", None) or "tool"
        snippet = _truncate_line(_normalize_content(getattr(message, "content", "")))
        if snippet:
            findings.append(f"- {tool_name}: {snippet}")
    return findings


def _normalize_content(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            str(item.get("text", "")).strip()
            for item in content
            if isinstance(item, dict) and item.get("text")
        ]
        return "\n".join(part for part in parts if part)
    return str(content).strip()


def _truncate_line(text: str, limit: int = 240) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."
