"""
Tests for mapper.py — mocked Ollama HTTP API.
Tests map_elements with various API responses and error conditions.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.mapper import map_elements, _call_ollama
from app.core.exceptions import (
    ClaudeAPIError,
    ClaudeRateLimitError,
    SchemaValidationError,
    VisionMappingError,
)
from app.models.schemas import MCPToolCandidate


def _mock_ollama_response(content: str, status_code: int = 200) -> httpx.Response:
    """Create a mock httpx.Response for Ollama chat API."""
    body = json.dumps({
        "model": "moondream",
        "message": {"role": "assistant", "content": content},
        "done": True,
    })
    return httpx.Response(
        status_code=status_code,
        content=body.encode(),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )


def _mock_ollama_candidates(candidates: list[dict]) -> httpx.Response:
    """Create a mock response with a candidates JSON array."""
    return _mock_ollama_response(json.dumps(candidates))


class TestCallOllama:
    @pytest.mark.asyncio
    async def test_success(self):
        """_call_ollama returns response text on success."""
        candidates = [{"element_type": "button", "semantic_intent": "Click"}]
        resp = _mock_ollama_candidates(candidates)

        with patch("app.core.mapper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await _call_ollama(
                messages=[{"role": "user", "content": "test"}],
                model="moondream",
            )

        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["element_type"] == "button"

    @pytest.mark.asyncio
    async def test_model_not_found(self):
        """_call_ollama raises ClaudeAPIError on 404."""
        resp = httpx.Response(
            status_code=404,
            content=b"model not found",
            request=httpx.Request("POST", "http://localhost:11434/api/chat"),
        )

        with patch("app.core.mapper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ClaudeAPIError, match="not found"):
                await _call_ollama(
                    messages=[{"role": "user", "content": "test"}],
                    model="nonexistent",
                )

    @pytest.mark.asyncio
    async def test_server_error(self):
        """_call_ollama raises ClaudeAPIError on non-200 status."""
        resp = httpx.Response(
            status_code=500,
            content=b"internal error",
            request=httpx.Request("POST", "http://localhost:11434/api/chat"),
        )

        with patch("app.core.mapper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ClaudeAPIError, match="500"):
                await _call_ollama(
                    messages=[{"role": "user", "content": "test"}],
                    model="moondream",
                )

    @pytest.mark.asyncio
    async def test_timeout(self):
        """map_elements catches timeout from _call_ollama."""
        with patch("app.core.mapper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.ollama_base_url = "http://localhost:11434"
                mock_settings.ollama_model = "moondream"
                with pytest.raises(ClaudeAPIError, match="timed out"):
                    await map_elements(
                        screenshot_b64=None,
                        accessibility_tree={},
                        url="https://example.com",
                        title="Test",
                    )

    @pytest.mark.asyncio
    async def test_empty_response(self):
        """_call_ollama raises VisionMappingError on empty content."""
        resp = _mock_ollama_response("")

        with patch("app.core.mapper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(VisionMappingError, match="empty response"):
                await _call_ollama(
                    messages=[{"role": "user", "content": "test"}],
                    model="moondream",
                )


class TestMapElements:
    @pytest.mark.asyncio
    async def test_success_single_candidate(self):
        """map_elements returns validated candidates from Ollama."""
        candidates = [
            {
                "element_type": "button",
                "semantic_intent": "Submit form",
                "suggested_tool_schema": {"type": "object", "properties": {}},
                "requires_human_approval": True,
            }
        ]
        resp = _mock_ollama_candidates(candidates)

        with patch("app.core.mapper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.ollama_base_url = "http://localhost:11434"
                mock_settings.ollama_model = "moondream"
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
        resp = _mock_ollama_candidates(candidates)

        with patch("app.core.mapper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.ollama_base_url = "http://localhost:11434"
                mock_settings.ollama_model = "moondream"
                result = await map_elements(
                    screenshot_b64="fake",
                    accessibility_tree={},
                    url="https://example.com",
                    title="Test",
                )

        assert len(result) == 3
        assert all(isinstance(c, MCPToolCandidate) for c in result)

    @pytest.mark.asyncio
    async def test_retries_on_invalid_json(self):
        """map_elements retries on invalid JSON, then succeeds."""
        valid_candidates = [{"element_type": "button", "semantic_intent": "Click", "suggested_tool_schema": {}}]
        invalid_resp = _mock_ollama_response("not valid json")
        valid_resp = _mock_ollama_candidates(valid_candidates)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return invalid_resp if call_count == 1 else valid_resp

        with patch("app.core.mapper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=side_effect)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.ollama_base_url = "http://localhost:11434"
                mock_settings.ollama_model = "moondream"
                result = await map_elements(
                    screenshot_b64=None,
                    accessibility_tree={},
                    url="https://example.com",
                    title="Test",
                )

        assert len(result) == 1
        assert call_count == 2  # initial + 1 retry

    @pytest.mark.asyncio
    async def test_retries_on_validation_failure(self):
        """map_elements retries when model returns invalid candidates."""
        invalid = [{"bad_field": "data"}]
        valid = [{"element_type": "button", "semantic_intent": "Click", "suggested_tool_schema": {}}]
        invalid_resp = _mock_ollama_candidates(invalid)
        valid_resp = _mock_ollama_candidates(valid)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return invalid_resp if call_count == 1 else valid_resp

        with patch("app.core.mapper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=side_effect)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.ollama_base_url = "http://localhost:11434"
                mock_settings.ollama_model = "moondream"
                result = await map_elements(
                    screenshot_b64=None,
                    accessibility_tree={},
                    url="https://example.com",
                    title="Test",
                )

        assert len(result) == 1
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_empty_candidates_raises(self):
        """map_elements raises VisionMappingError when no candidates returned."""
        resp = _mock_ollama_candidates([])

        with patch("app.core.mapper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.ollama_base_url = "http://localhost:11434"
                mock_settings.ollama_model = "moondream"
                with pytest.raises(VisionMappingError, match="no tool candidates"):
                    await map_elements(
                        screenshot_b64=None,
                        accessibility_tree={},
                        url="https://example.com",
                        title="Test",
                    )

    @pytest.mark.asyncio
    async def test_connection_error(self):
        """map_elements raises ClaudeAPIError on connection failure."""
        with patch("app.core.mapper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.ollama_base_url = "http://localhost:11434"
                mock_settings.ollama_model = "moondream"
                with pytest.raises(ClaudeAPIError, match="connection error"):
                    await map_elements(
                        screenshot_b64=None,
                        accessibility_tree={},
                        url="https://example.com",
                        title="Test",
                    )

    @pytest.mark.asyncio
    async def test_format_json_request(self):
        """Verify format='json' is sent in the Ollama request."""
        candidates = [{"element_type": "button", "semantic_intent": "Click", "suggested_tool_schema": {}}]
        resp = _mock_ollama_candidates(candidates)

        with patch("app.core.mapper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            with patch("app.core.mapper.settings") as mock_settings:
                mock_settings.ollama_base_url = "http://localhost:11434"
                mock_settings.ollama_model = "moondream"
                await map_elements(
                    screenshot_b64=None,
                    accessibility_tree={},
                    url="https://example.com",
                    title="Test",
                )

        call_kwargs = mock_client.post.call_args
        json_body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert json_body["format"] == "json"
        assert json_body["model"] == "moondream"
        assert json_body["stream"] is False
