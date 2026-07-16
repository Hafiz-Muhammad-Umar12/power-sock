"""
Tests for executor.py — mocked Playwright browser.
Tests element location strategies, action dispatch, and full execution lifecycle.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.executor import (
    ExecutionResult,
    _perform_action,
    _perform_click,
    _perform_fill,
    _perform_select,
    _perform_type,
    execute_tool_action,
)
from app.core.exceptions import ElementNotFoundError, ExecutionError


# ── Action performer tests ───────────────────────────────────────────────────


class TestPerformClick:
    @pytest.mark.asyncio
    async def test_click(self):
        locator = AsyncMock()
        result = await _perform_click(locator)
        locator.click.assert_called_once()
        assert result == "click"


class TestPerformFill:
    @pytest.mark.asyncio
    async def test_fill(self):
        locator = AsyncMock()
        result = await _perform_fill(locator, "hello world")
        locator.fill.assert_called_once_with("hello world", timeout=15000)
        assert result == "fill('hello world')"


class TestPerformSelect:
    @pytest.mark.asyncio
    async def test_select(self):
        locator = AsyncMock()
        result = await _perform_select(locator, "blue")
        locator.select_option.assert_called_once_with(value="blue", timeout=15000)
        assert result == "select('blue')"


class TestPerformType:
    @pytest.mark.asyncio
    async def test_type(self):
        locator = AsyncMock()
        result = await _perform_type(locator, "keys")
        locator.press_sequentially.assert_called_once_with("keys", timeout=15000)
        assert result == "type('keys')"


# ── Action dispatch tests ────────────────────────────────────────────────────


class TestPerformAction:
    @pytest.mark.asyncio
    async def test_click_button(self):
        """Button with no value → click."""
        locator = AsyncMock()
        result = await _perform_action(locator, "button", {})
        locator.click.assert_called_once()
        assert result == "click"

    @pytest.mark.asyncio
    async def test_click_link(self):
        """Link with no value → click."""
        locator = AsyncMock()
        result = await _perform_action(locator, "link", {})
        locator.click.assert_called_once()
        assert result == "click"

    @pytest.mark.asyncio
    async def test_fill_input(self):
        """Input with value → fill."""
        locator = AsyncMock()
        result = await _perform_action(locator, "input", {"value": "test"})
        locator.fill.assert_called_once()
        assert "fill" in result

    @pytest.mark.asyncio
    async def test_fill_requires_value(self):
        """Input without value → ExecutionError."""
        locator = AsyncMock()
        with pytest.raises(ExecutionError, match="requires a 'value'"):
            await _perform_action(locator, "input", {})

    @pytest.mark.asyncio
    async def test_select_dropdown(self):
        """Select with value → select_option."""
        locator = AsyncMock()
        result = await _perform_action(locator, "select", {"value": "red"})
        locator.select_option.assert_called_once()
        assert "select" in result

    @pytest.mark.asyncio
    async def test_select_requires_value(self):
        """Select without value → ExecutionError."""
        locator = AsyncMock()
        with pytest.raises(ExecutionError, match="requires a 'value'"):
            await _perform_action(locator, "select", {})

    @pytest.mark.asyncio
    async def test_explicit_action_override(self):
        """Explicit action=click overrides default for input."""
        locator = AsyncMock()
        result = await _perform_action(locator, "input", {"action": "click"})
        locator.click.assert_called_once()
        assert result == "click"

    @pytest.mark.asyncio
    async def test_explicit_type_action(self):
        """Explicit action=type uses press_sequentially."""
        locator = AsyncMock()
        result = await _perform_action(locator, "input", {"action": "type", "value": "keys"})
        locator.press_sequentially.assert_called_once()
        assert "type" in result

    @pytest.mark.asyncio
    async def test_type_requires_value(self):
        """Explicit action=type without value → ExecutionError."""
        locator = AsyncMock()
        with pytest.raises(ExecutionError, match="requires a 'value'"):
            await _perform_action(locator, "input", {"action": "type"})


# ── ExecutionResult model tests ──────────────────────────────────────────────


class TestExecutionResult:
    def test_success_result(self):
        r = ExecutionResult(
            success=True,
            action_performed="click",
            element_found=True,
        )
        assert r.success is True
        assert r.screenshot_b64 is None
        assert r.error_message is None

    def test_failure_result(self):
        r = ExecutionResult(
            success=False,
            action_performed="locate",
            element_found=False,
            error_message="Element not found",
        )
        assert r.success is False
        assert r.error_message == "Element not found"


# ── Full executor lifecycle tests (mocked Playwright) ────────────────────────


def _make_mock_page_for_executor(
    url: str = "https://example.com/",
    screenshot: bytes = b"\x89PNG_FAKE",
) -> MagicMock:
    """Create a mock Page for executor tests."""
    page = AsyncMock()
    page.url = url
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.screenshot = AsyncMock(return_value=screenshot)

    # Mock elementFromPoint → returns a mock element
    mock_element = MagicMock()
    mock_element.tagName = "BUTTON"
    mock_element.id = "test-btn"
    mock_element.getAttribute = MagicMock(return_value=None)
    handle = AsyncMock()
    handle.json_value = AsyncMock(return_value=mock_element)
    page.evaluate_handle = AsyncMock(return_value=handle)

    # Mock evaluate → returns a CSS selector
    page.evaluate = AsyncMock(return_value="#test-btn")

    # Mock locator
    locator = AsyncMock()
    locator.count = AsyncMock(return_value=1)
    locator.wait_for = AsyncMock()
    locator.click = AsyncMock()
    locator.fill = AsyncMock()
    page.locator = MagicMock(return_value=locator)

    # Mock set_extra_http_headers
    page.set_extra_http_headers = AsyncMock()

    return page


class TestExecuteToolAction:
    @pytest.mark.asyncio
    async def test_click_button_success(self):
        """Full lifecycle: locate button by bounding box, click it, capture screenshot."""
        page = _make_mock_page_for_executor()
        browser = AsyncMock()
        context = AsyncMock()
        context.new_page = AsyncMock(return_value=page)
        browser.new_context = AsyncMock(return_value=context)

        pw = AsyncMock()
        pw.chromium.launch = AsyncMock(return_value=browser)
        pw_instance = AsyncMock()
        pw_instance.chromium = pw.chromium
        pw.start = AsyncMock(return_value=pw_instance)
        pw.stop = AsyncMock()

        with patch("app.core.executor.async_playwright", return_value=AsyncMock(start=AsyncMock(return_value=pw_instance))):
            result = await execute_tool_action(
                base_url="https://example.com",
                url_path="/",
                element_type="button",
                semantic_intent="Click Me",
                bounding_box={"x": 5, "y": 20, "width": 10, "height": 5},
                action_params={},
            )

        assert result.success is True
        assert result.element_found is True
        assert result.action_performed == "click"
        assert result.screenshot_b64 is not None
        assert result.post_action_url == "https://example.com/"

    @pytest.mark.asyncio
    async def test_fill_input_success(self):
        """Full lifecycle: locate input, fill with value."""
        page = _make_mock_page_for_executor()
        browser, context, _ = (AsyncMock(), AsyncMock(), page)
        context.new_page = AsyncMock(return_value=page)
        browser.new_context = AsyncMock(return_value=context)

        pw_instance = AsyncMock()
        pw_instance.chromium.launch = AsyncMock(return_value=browser)

        with patch("app.core.executor.async_playwright", return_value=AsyncMock(start=AsyncMock(return_value=pw_instance))):
            result = await execute_tool_action(
                base_url="https://example.com",
                url_path="/",
                element_type="input",
                semantic_intent="Search",
                bounding_box={"x": 5, "y": 20, "width": 10, "height": 5},
                action_params={"value": "test query"},
            )

        assert result.success is True
        assert "fill" in result.action_performed

    @pytest.mark.asyncio
    async def test_navigation_failure(self):
        """Returns failure result when navigation fails."""
        page = _make_mock_page_for_executor()
        page.goto = AsyncMock(side_effect=Exception("DNS error"))
        browser, context, _ = (AsyncMock(), AsyncMock(), page)
        context.new_page = AsyncMock(return_value=page)
        browser.new_context = AsyncMock(return_value=context)

        pw_instance = AsyncMock()
        pw_instance.chromium.launch = AsyncMock(return_value=browser)

        with patch("app.core.executor.async_playwright", return_value=AsyncMock(start=AsyncMock(return_value=pw_instance))):
            result = await execute_tool_action(
                base_url="https://nonexistent.invalid",
                url_path="/",
                element_type="button",
                semantic_intent="Click",
                bounding_box=None,
                action_params={},
            )

        assert result.success is False
        assert "Navigation failed" in result.error_message

    @pytest.mark.asyncio
    async def test_auth_credentials_injected(self):
        """Auth cookies and headers are injected into browser context."""
        page = _make_mock_page_for_executor()
        browser, context, _ = (AsyncMock(), AsyncMock(), page)
        context.new_page = AsyncMock(return_value=page)
        browser.new_context = AsyncMock(return_value=context)

        pw_instance = AsyncMock()
        pw_instance.chromium.launch = AsyncMock(return_value=browser)

        with patch("app.core.executor.async_playwright", return_value=AsyncMock(start=AsyncMock(return_value=pw_instance))):
            await execute_tool_action(
                base_url="https://example.com",
                url_path="/",
                element_type="button",
                semantic_intent="Click",
                bounding_box=None,
                action_params={},
                auth_credentials={
                    "cookies": [{"name": "sid", "value": "abc"}],
                    "headers": {"X-Token": "test"},
                },
            )

        context.add_cookies.assert_called_once()
        page.set_extra_http_headers.assert_called_once()
