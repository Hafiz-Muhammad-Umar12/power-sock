"""
Unit tests for the mapper module.
Anthropic API is mocked — we test parsing, validation, and error handling.
"""

import json

import pytest

from app.core.mapper import (
    _build_user_content,
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

    def test_raises_on_non_array(self):
        raw = '{"element_type": "button"}'
        with pytest.raises(VisionMappingError, match="Expected JSON array"):
            _parse_candidates(raw)

    def test_raises_on_invalid_json(self):
        raw = 'not json at all'
        with pytest.raises(json.JSONDecodeError):
            _parse_candidates(raw)

    def test_empty_array(self):
        raw = '[]'
        result = _parse_candidates(raw)
        assert result == []


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
        assert result[1].requires_human_approval is False  # default

    def test_empty_list(self):
        result = _validate_candidates([])
        assert result == []

    def test_invalid_candidate_raises(self):
        raw = [
            {"element_type": "button", "semantic_intent": "Click me"},
            {"no_element_type": "bad"},  # Missing required fields
        ]
        # Should raise since ALL candidates fail (only 1 valid, 1 invalid)
        # Actually, only 1 valid and 1 invalid — it should return the valid one
        result = _validate_candidates(raw)
        assert len(result) == 1
        assert result[0].semantic_intent == "Click me"

    def test_all_invalid_raises(self):
        raw = [{"bad": "data"}, {"another": "bad"}]
        with pytest.raises(SchemaValidationError):
            _validate_candidates(raw)

    def test_suggested_tool_schema_defaults_to_empty(self):
        raw = [
            {
                "element_type": "button",
                "semantic_intent": "Click",
                # No suggested_tool_schema
            }
        ]
        result = _validate_candidates(raw)
        assert result[0].suggested_tool_schema == {}


class TestBuildUserContent:
    def test_with_screenshot(self):
        content = _build_user_content(
            screenshot_b64="abc123",
            accessibility_tree={"role": "WebArea", "name": "Test"},
            url="https://example.com",
            title="Test Page",
        )
        assert len(content) == 3  # text + image + a11y tree
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image"
        assert content[1]["source"]["data"] == "abc123"
        assert content[2]["type"] == "text"

    def test_without_screenshot(self):
        content = _build_user_content(
            screenshot_b64=None,
            accessibility_tree={},
            url="https://example.com",
            title="",
        )
        assert len(content) == 2  # text + a11y tree only
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "text"  # a11y tree

    def test_truncates_large_a11y_tree(self):
        large_tree = {"children": [{"data": "x" * 100_000}]}
        content = _build_user_content(
            screenshot_b64=None,
            accessibility_tree=large_tree,
            url="https://example.com",
            title="",
        )
        a11y_text = content[1]["text"]
        assert "truncated" in a11y_text
