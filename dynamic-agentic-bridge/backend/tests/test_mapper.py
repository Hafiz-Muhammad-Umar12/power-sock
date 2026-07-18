"""
Unit tests for the mapper module.
Tests parsing, validation, and message building (no API calls).
"""

import json

import pytest

from app.core.mapper import (
    _build_ollama_messages,
    _parse_candidates,
    _validate_candidates,
)
from app.core.exceptions import (
    SchemaValidationError,
    VisionMappingError,
)
from app.models.schemas import MCPToolCandidate


class TestParseCandidates:
    def test_valid_json_array(self):
        raw = '[{"element_type": "button", "semantic_intent": "submit form"}]'
        result = _parse_candidates(raw)
        assert len(result) == 1
        assert result[0]["element_type"] == "button"

    def test_strips_markdown_fences(self):
        raw = '```json\n[{"element_type": "button", "semantic_intent": "click"}]\n```'
        result = _parse_candidates(raw)
        assert len(result) == 1

    def test_strips_plain_code_fences(self):
        raw = '```\n[{"element_type": "input", "semantic_intent": "enter text"}]\n```'
        result = _parse_candidates(raw)
        assert len(result) == 1

    def test_single_dict_wrapped_as_candidate(self):
        """Single dict with element_type is treated as one candidate."""
        raw = '{"element_type": "button", "semantic_intent": "Click"}'
        result = _parse_candidates(raw)
        assert len(result) == 1
        assert result[0]["element_type"] == "button"

    def test_dict_with_string_values_treated_as_candidate(self):
        """Any dict with string values is treated as a candidate (moondream compat)."""
        raw = '{"foo": "bar", "baz": "qux"}'
        result = _parse_candidates(raw)
        assert len(result) == 1
        # Should get default element_type and semantic_intent
        assert result[0]["element_type"] == "element"

    def test_raises_on_invalid_json(self):
        raw = 'not json at all'
        with pytest.raises(VisionMappingError, match="Could not parse JSON"):
            _parse_candidates(raw)

    def test_empty_array(self):
        raw = '[]'
        result = _parse_candidates(raw)
        assert result == []

    def test_unwraps_candidates_dict(self):
        """Ollama may wrap response in {"candidates": [...]}."""
        raw = '{"candidates": [{"element_type": "button", "semantic_intent": "Click"}]}'
        result = _parse_candidates(raw)
        assert len(result) == 1
        assert result[0]["element_type"] == "button"


class TestValidateCandidates:
    def test_valid_candidates(self):
        raw = [
            {
                "element_type": "button",
                "semantic_intent": "Submit purchase order",
                "suggested_tool_schema": {"type": "object", "properties": {}},
                "requires_human_approval": True,
            },
            {
                "element_type": "link",
                "semantic_intent": "Navigate to reports",
                "suggested_tool_schema": {},
            },
        ]
        result = _validate_candidates(raw)
        assert len(result) == 2
        assert isinstance(result[0], MCPToolCandidate)
        assert result[0].requires_human_approval is True
        assert result[1].requires_human_approval is False

    def test_empty_list(self):
        result = _validate_candidates([])
        assert result == []

    def test_partial_valid(self):
        raw = [
            {"element_type": "button", "semantic_intent": "Click me"},
            {"no_element_type": "bad"},
        ]
        result = _validate_candidates(raw)
        assert len(result) == 1
        assert result[0].semantic_intent == "Click me"

    def test_all_invalid_raises(self):
        raw = [{"bad": "data"}, {"another": "bad"}]
        with pytest.raises(SchemaValidationError):
            _validate_candidates(raw)

    def test_suggested_tool_schema_defaults_to_empty(self):
        raw = [{"element_type": "button", "semantic_intent": "Click"}]
        result = _validate_candidates(raw)
        assert result[0].suggested_tool_schema == {}


class TestBuildOllamaMessages:
    def test_with_screenshot(self):
        messages = _build_ollama_messages(
            screenshot_b64="abc123",
            accessibility_tree={"role": "WebArea", "name": "Test"},
            url="https://example.com",
            title="Test Page",
        )
        assert len(messages) == 2  # system + user
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["images"] == ["abc123"]
        assert "example.com" in messages[1]["content"]

    def test_without_screenshot(self):
        messages = _build_ollama_messages(
            screenshot_b64=None,
            accessibility_tree={},
            url="https://example.com",
            title="",
        )
        assert len(messages) == 2
        assert "images" not in messages[1]

    def test_truncates_large_a11y_tree(self):
        large_tree = {"children": [{"data": "x" * 100_000}]}
        messages = _build_ollama_messages(
            screenshot_b64=None,
            accessibility_tree=large_tree,
            url="https://example.com",
            title="",
        )
        # Tree should be trimmed well under the text-only cap
        assert len(messages[1]["content"]) < 10_000
