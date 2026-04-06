"""Tests for the agent transcript evaluator."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from legion.agents.evaluator import (
    _extract_final_answer,
    _extract_tool_findings,
    _normalize_content,
    _truncate_line,
    summarize_transcript,
)


def test_summarize_transcript_complete() -> None:
    messages = [
        SystemMessage(content="You are an SRE agent."),
        HumanMessage(content="Check pod health."),
        AIMessage(
            content="",
            tool_calls=[{"name": "kubectl", "args": {}, "id": "1", "type": "tool_call"}],
        ),
        ToolMessage(content="pod/web-1 Running", name="kubectl", tool_call_id="1"),
        AIMessage(content="All pods are healthy."),
    ]

    result = summarize_transcript(messages, tokens_used=150, budget_exhausted=False)

    assert "Result status: complete" in result
    assert "Tokens used: 150" in result
    assert "All pods are healthy." in result
    assert "- kubectl: pod/web-1 Running" in result
    assert "Budget exhausted" not in result


def test_summarize_transcript_budget_exhausted() -> None:
    messages = [
        HumanMessage(content="Investigate outage."),
        AIMessage(content="Partial analysis so far."),
    ]

    result = summarize_transcript(messages, tokens_used=9999, budget_exhausted=True)

    assert "Result status: partial" in result
    assert "Tokens used: 9999" in result
    assert "Partial analysis so far." in result
    assert "Budget exhausted before the loop reached a natural stop." in result


def test_summarize_transcript_no_ai_messages() -> None:
    messages = [
        SystemMessage(content="You are an SRE agent."),
        HumanMessage(content="Hello."),
    ]

    result = summarize_transcript(messages, tokens_used=10, budget_exhausted=False)

    assert "No final answer produced." in result


def test_extract_final_answer_skips_tool_calling_messages() -> None:
    messages = [
        AIMessage(content="First answer."),
        AIMessage(
            content="",
            tool_calls=[{"name": "foo", "args": {}, "id": "1", "type": "tool_call"}],
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "bar", "args": {}, "id": "2", "type": "tool_call"}],
        ),
        AIMessage(content="Final answer."),
        AIMessage(
            content="",
            tool_calls=[{"name": "baz", "args": {}, "id": "3", "type": "tool_call"}],
        ),
    ]

    assert _extract_final_answer(messages) == "Final answer."


def test_extract_final_answer_empty_messages() -> None:
    assert _extract_final_answer([]) == ""


def test_normalize_content_string() -> None:
    assert _normalize_content("  hello world  ") == "hello world"


def test_normalize_content_list_of_dicts() -> None:
    content = [
        {"type": "text", "text": "hello"},
        {"type": "text", "text": "world"},
    ]

    assert _normalize_content(content) == "hello\nworld"


def test_normalize_content_none() -> None:
    assert _normalize_content(None) == ""


def test_normalize_content_other_type() -> None:
    assert _normalize_content(42) == "42"


def test_truncate_line_under_limit() -> None:
    assert _truncate_line("short") == "short"


def test_truncate_line_at_limit() -> None:
    text = "x" * 240
    assert _truncate_line(text) == text


def test_truncate_line_over_limit() -> None:
    text = "x" * 300
    result = _truncate_line(text)

    assert result.endswith("...")
    assert len(result) <= 240


def test_tool_findings_extracts_tool_messages() -> None:
    messages = [
        HumanMessage(content="go"),
        ToolMessage(content="pod/web Running", name="kubectl", tool_call_id="1"),
        AIMessage(content="done"),
        ToolMessage(content="node ready", name="node_status", tool_call_id="2"),
    ]

    findings = _extract_tool_findings(messages)

    assert findings == [
        "- kubectl: pod/web Running",
        "- node_status: node ready",
    ]


def test_tool_findings_truncates_long_output() -> None:
    long_output = "a" * 300
    messages = [
        ToolMessage(content=long_output, name="big_tool", tool_call_id="1"),
    ]

    findings = _extract_tool_findings(messages)

    assert len(findings) == 1
    assert findings[0].endswith("...")
    # The bullet prefix "- big_tool: " plus the truncated content
    assert len(findings[0]) < len(long_output)
