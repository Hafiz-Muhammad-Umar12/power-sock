"""
Unit tests for the MCP generator module.
Database is mocked — we test tool definition generation and name creation.
"""

import pytest

from app.core.mcp_generator import (
    _make_tool_name,
    generate_mcp_tool_definition,
)
from app.core.exceptions import ToolSchemaError
from app.models.schemas import MCPToolCandidate


class TestMakeToolName:
    def test_basic_name(self):
        name = _make_tool_name("Submit purchase order", "button")
        assert name == "button__submit_purchase_order"

    def test_lowercases(self):
        name = _make_tool_name("CLICK HERE", "LINK")
        assert name == "link__click_here"

    def test_removes_special_chars(self):
        name = _make_tool_name("Filter by date (range)", "select")
        assert name == "select__filter_by_date_range"

    def test_max_length(self):
        long_intent = "x" * 100
        name = _make_tool_name(long_intent, "button")
        assert len(name) <= 64

    def test_strips_trailing_underscores(self):
        name = _make_tool_name("Submit!!!", "button")
        assert not name.endswith("_")

    def test_empty_prefix(self):
        name = _make_tool_name("navigate somewhere", "")
        assert name == "navigate_somewhere"


class TestGenerateMcpToolDefinition:
    def test_basic_tool(self):
        candidate = MCPToolCandidate(
            element_type="button",
            semantic_intent="Submit purchase order",
            suggested_tool_schema={
                "type": "object",
                "properties": {
                    "quantity": {"type": "integer", "description": "Order quantity"},
                },
                "required": ["quantity"],
            },
            requires_human_approval=True,
        )
        tool = generate_mcp_tool_definition(candidate)

        assert tool["name"] == "button__submit_purchase_order"
        assert "[button]" in tool["description"]
        assert "⚠️ Requires human approval" in tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        assert "quantity" in tool["inputSchema"]["properties"]
        assert tool["annotations"]["requires_human_approval"] is True
        assert tool["annotations"]["element_type"] == "button"

    def test_readonly_tool(self):
        candidate = MCPToolCandidate(
            element_type="link",
            semantic_intent="Navigate to reports page",
            suggested_tool_schema={},
            requires_human_approval=False,
        )
        tool = generate_mcp_tool_definition(candidate)
        assert "⚠️" not in tool["description"]
        assert tool["annotations"]["requires_human_approval"] is False

    def test_empty_schema_gets_default(self):
        candidate = MCPToolCandidate(
            element_type="button",
            semantic_intent="Click refresh",
            suggested_tool_schema={},
        )
        tool = generate_mcp_tool_definition(candidate)
        assert tool["inputSchema"]["type"] == "object"

    def test_missing_semantic_intent_raises(self):
        candidate = MCPToolCandidate(
            element_type="button",
            semantic_intent="",
            suggested_tool_schema={},
        )
        with pytest.raises(ToolSchemaError, match="semantic_intent is required"):
            generate_mcp_tool_definition(candidate)

    def test_tool_with_bounding_box(self):
        candidate = MCPToolCandidate(
            element_type="button",
            semantic_intent="Save changes",
            bounding_box={"x": 10, "y": 20, "width": 100, "height": 40},
        )
        tool = generate_mcp_tool_definition(candidate)
        assert tool["annotations"]["bounding_box"] == {
            "x": 10, "y": 20, "width": 100, "height": 40
        }

    def test_complex_schema_preserved(self):
        schema = {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "format": "date"},
                "end_date": {"type": "string", "format": "date"},
                "category": {"type": "string", "enum": ["all", "electronics", "clothing"]},
            },
            "required": ["start_date", "end_date"],
        }
        candidate = MCPToolCandidate(
            element_type="select",
            semantic_intent="Filter orders by date range and category",
            suggested_tool_schema=schema,
        )
        tool = generate_mcp_tool_definition(candidate)
        assert tool["inputSchema"] == schema
