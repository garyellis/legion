"""Tests for AuditEvent domain model and AuditAction enum."""

from __future__ import annotations

import uuid
from datetime import timezone

import pytest
from pydantic import ValidationError

from legion.domain.audit_event import AuditAction, AuditEvent


class TestAuditAction:
    def test_all_enum_values(self):
        expected = {
            "TOOL_CALL",
            "TOOL_RESULT",
            "LLM_DECISION",
            "APPROVAL_REQUESTED",
            "APPROVAL_GRANTED",
            "APPROVAL_DENIED",
        }
        assert {a.value for a in AuditAction} == expected

    def test_enum_is_str(self):
        for action in AuditAction:
            assert isinstance(action, str)
            assert action == action.value


class TestAuditEvent:
    def _make_event(self, **overrides):
        defaults = {
            "job_id": "job-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "org_id": "org-1",
            "action": AuditAction.TOOL_CALL,
        }
        defaults.update(overrides)
        return AuditEvent(**defaults)

    def test_construction_with_required_fields(self):
        event = self._make_event()
        assert event.job_id == "job-1"
        assert event.agent_id == "agent-1"
        assert event.session_id == "session-1"
        assert event.org_id == "org-1"
        assert event.action == AuditAction.TOOL_CALL

    def test_default_id_is_uuid(self):
        event = self._make_event()
        parsed = uuid.UUID(event.id)
        assert str(parsed) == event.id

    def test_default_id_is_unique(self):
        a = self._make_event()
        b = self._make_event()
        assert a.id != b.id

    def test_default_created_at_is_utc(self):
        event = self._make_event()
        assert event.created_at.tzinfo is not None
        assert event.created_at.tzinfo == timezone.utc

    def test_optional_fields_default_to_none(self):
        event = self._make_event()
        assert event.tool_name is None
        assert event.input is None
        assert event.output is None
        assert event.duration_ms is None

    def test_optional_fields_accept_values(self):
        event = self._make_event(
            tool_name="kubectl",
            input={"namespace": "prod"},
            output={"pods": ["a", "b"]},
            duration_ms=42,
        )
        assert event.tool_name == "kubectl"
        assert event.input == {"namespace": "prod"}
        assert event.output == {"pods": ["a", "b"]}
        assert event.duration_ms == 42

    def test_input_rejects_non_string_keys(self):
        with pytest.raises(ValidationError):
            self._make_event(input={1: "bad"})

    def test_output_rejects_non_string_keys(self):
        with pytest.raises(ValidationError):
            self._make_event(output={2: "bad"})

    def test_input_accepts_nested_dicts(self):
        event = self._make_event(
            input={"outer": {"inner": {"deep": True}}},
        )
        assert event.input["outer"]["inner"]["deep"] is True

    def test_output_accepts_nested_dicts(self):
        event = self._make_event(
            output={"list": [1, 2, {"nested": "ok"}]},
        )
        assert event.output["list"][2]["nested"] == "ok"

    def test_frozen_rejects_field_assignment(self):
        event = self._make_event()
        with pytest.raises(ValidationError):
            event.action = AuditAction.LLM_DECISION

    def test_frozen_rejects_duration_assignment(self):
        event = self._make_event(duration_ms=100)
        with pytest.raises(ValidationError):
            event.duration_ms = 200

    def test_truncation_on_oversized_input(self):
        big_value = "x" * 70_000
        event = self._make_event(input={"payload": big_value})
        assert event.input["_truncated"] is True
        assert event.input["_original_bytes"] > 65_536
        assert "_preview" in event.input

    def test_truncation_on_oversized_output(self):
        big_value = "x" * 70_000
        event = self._make_event(output={"payload": big_value})
        assert event.output["_truncated"] is True
        assert event.output["_original_bytes"] > 65_536
        assert "_preview" in event.output

    def test_negative_duration_rejected(self):
        with pytest.raises(ValidationError):
            AuditEvent(
                job_id="j-1", agent_id="a-1", session_id="s-1", org_id="o-1",
                action=AuditAction.TOOL_CALL,
                duration_ms=-1,
            )

    def test_small_payload_passes_through_unchanged(self):
        small_input = {"key": "value", "number": 42}
        small_output = {"result": [1, 2, 3]}
        event = self._make_event(input=small_input, output=small_output)
        assert event.input == small_input
        assert event.output == small_output
