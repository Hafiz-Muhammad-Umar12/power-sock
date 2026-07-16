"""
Tests for mapper.py — mocked Anthropic API client.
Tests map_elements with various API responses and error conditions.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.mapper import map_elements
from app.core.exceptions import (
    ClaudeAPIError,
    ClaudeRateLimitError,
    SchemaValidationError,
    VisionMappingError,
)
from app.models.schemas import MCPToolCandidate


def _mock_response(text: str) -> MagicMock:
    """Create a mock Anthropic API response with the given text."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _mock_rate_limit_response() -> MagicMock:
    """Create a mock rate limit error response."""
    resp = MagicMock()
    resp.headers = {"retry-after": "5"}
    err = MagicMock()
    err.response = resp
    err.status_code = 429
    return err


class TestMapElements:
    @pytest.mark.asyncio
    async def test_success_single_candidate(self):
        """map_elements returns validated candidates from Claude."""
        candidates = [
            {
                "element_type": "button",
                "semantic_intent": "Submit form",
                "suggested_tool_schema": {"type": "object", "properties": {}},
                "requires_human_approval": True,
            }
        ]
        api_response = _mock_response(json.dumps(candidates))

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=api_response)

        with patch("app.core.mapper.anthropic.AsyncAnthropic", return_value=mock_client):
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.anthropic_api_key = "sk-ant-test"
                result = await map_elements(
                    screenshot_b64="fake_base64",
                    accessibility_tree={"role": "WebArea"},
                    url="https://example.com",
                    title="Test",
                )

        assert len(result) == 1
        assert isinstance(result[0], MCPToolCandidate)
        assert result[0].element_type == "button"
        assert result[0].semantic_intent == "Submit form"
        assert result[0].requires_human_approval is True

    @pytest.mark.asyncio
    async def test_success_multiple_candidates(self):
        """map_elements handles multiple candidates."""
        candidates = [
            {"element_type": "button", "semantic_intent": "Click A", "suggested_tool_schema": {}},
            {"element_type": "link", "semantic_intent": "Go to B", "suggested_tool_schema": {}},
            {"element_type": "input", "semantic_intent": "Enter text", "suggested_tool_schema": {}, "requires_human_approval": True},
        ]
        api_response = _mock_response(json.dumps(candidates))

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=api_response)

        with patch("app.core.mapper.anthropic.AsyncAnthropic", return_value=mock_client):
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.anthropic_api_key = "sk-ant-test"
                result = await map_elements(
                    screenshot_b64="fake",
                    accessibility_tree={},
                    url="https://example.com",
                    title="Test",
                )

        assert len(result) == 3
        assert all(isinstance(c, MCPToolCandidate) for c in result)

    @pytest.mark.asyncio
    async def test_strips_markdown_fences(self):
        """map_elements strips ```json fences from Claude response."""
        candidates = [{"element_type": "button", "semantic_intent": "Click", "suggested_tool_schema": {}}]
        fenced = f"```json\n{json.dumps(candidates)}\n```"
        api_response = _mock_response(fenced)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=api_response)

        with patch("app.core.mapper.anthropic.AsyncAnthropic", return_value=mock_client):
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.anthropic_api_key = "sk-ant-test"
                result = await map_elements(
                    screenshot_b64=None,
                    accessibility_tree={},
                    url="https://example.com",
                    title="Test",
                )

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        """map_elements raises VisionMappingError on empty response."""
        block = MagicMock()
        block.type = "text"
        block.text = ""
        response = MagicMock()
        response.content = [block]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("app.core.mapper.anthropic.AsyncAnthropic", return_value=mock_client):
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.anthropic_api_key = "sk-ant-test"
                with pytest.raises(VisionMappingError, match="empty response"):
                    await map_elements(
                        screenshot_b64=None,
                        accessibility_tree={},
                        url="https://example.com",
                        title="Test",
                    )

    @pytest.mark.asyncio
    async def test_invalid_json_retries_then_fails(self):
        """map_elements retries once on invalid JSON, then raises."""
        invalid_response = _mock_response("not valid json at all")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=invalid_response)

        with patch("app.core.mapper.anthropic.AsyncAnthropic", return_value=mock_client):
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.anthropic_api_key = "sk-ant-test"
                with pytest.raises(Exception):  # JSONDecodeError or VisionMappingError
                    await map_elements(
                        screenshot_b64=None,
                        accessibility_tree={},
                        url="https://example.com",
                        title="Test",
                    )

        # Should have been called twice (initial + retry)
        assert mock_client.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_no_api_key_raises(self):
        """map_elements raises ClaudeAPIError when no API key configured."""
        with patch("app.core.mapper.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            with pytest.raises(ClaudeAPIError, match="not configured"):
                await map_elements(
                    screenshot_b64=None,
                    accessibility_tree={},
                    url="https://example.com",
                    title="Test",
                )

    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        """map_elements raises ClaudeRateLimitError on 429."""
        import anthropic
        err = anthropic.RateLimitError(
            message="Rate limited",
            response=MagicMock(status_code=429, headers={"retry-after": "5"}),
            body=None,
        )
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=err)

        with patch("app.core.mapper.anthropic.AsyncAnthropic", return_value=mock_client):
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.anthropic_api_key = "sk-ant-test"
                with pytest.raises(ClaudeRateLimitError):
                    await map_elements(
                        screenshot_b64=None,
                        accessibility_tree={},
                        url="https://example.com",
                        title="Test",
                    )
