"""
Tests for observer.py — mocked Playwright browser.
Tests observe_application, _handle_auth with mocked Playwright.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.observer import ObservationResult, _handle_auth, observe_application
from app.core.exceptions import (
    AuthenticationError,
    NavigationError,
    PageLoadTimeout,
)


# ── Mock factories ───────────────────────────────────────────────────────────


def _make_mock_page(
    url: str = "https://example.com/",
    title: str = "Test Page",
    a11y_snapshot: dict | None = None,
    screenshot_bytes: bytes = b"\x89PNG_FAKE",
    dom_snapshot: dict | None = None,
) -> MagicMock:
    """Create a mock Playwright Page with configurable return values."""
    page = AsyncMock()
    page.url = url
    page.title = AsyncMock(return_value=title)
    page.accessibility.snapshot = AsyncMock(
        return_value=a11y_snapshot or {"role": "WebArea", "name": title}
    )
    page.screenshot = AsyncMock(return_value=screenshot_bytes)
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.set_extra_http_headers = AsyncMock()
    page.evaluate = AsyncMock(
        return_value=dom_snapshot or {"nodeName": "html", "attributes": {}, "children": []}
    )
    # For _handle_auth
    locator_mock = AsyncMock()
    locator_mock.first = AsyncMock()
    locator_mock.first.wait_for = AsyncMock()
    locator_mock.first.fill = AsyncMock()
    locator_mock.first.click = AsyncMock()
    page.locator = MagicMock(return_value=locator_mock)
    return page


def _make_mock_browser(page: MagicMock | None = None) -> MagicMock:
    """Create a mock Browser that returns the given page."""
    mock_page = page or _make_mock_page()
    browser = AsyncMock()
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=mock_page)
    browser.new_context = AsyncMock(return_value=context)
    return browser, context, mock_page


# ── Tests for observe_application ────────────────────────────────────────────


class TestObserveApplication:
    @pytest.mark.asyncio
    async def test_success_basic(self):
        """observe_application returns structured result with no auth."""
        browser, ctx, page = _make_mock_browser()
        pw = AsyncMock()
        pw.chromium.launch = AsyncMock(return_value=browser)
        pw.start = AsyncMock(return_value=pw)
        pw.stop = AsyncMock()

        with patch("app.core.observer.async_playwright", return_value=AsyncMock(start=AsyncMock(return_value=pw))):
            result = await observe_application(
                base_url="https://example.com",
                auth_credentials=None,
                url_path="/",
            )

        assert isinstance(result, ObservationResult)
        assert result.url == "https://example.com/"
        assert result.title == "Test Page"
        assert len(result.state_hash) == 64  # SHA-256 hex
        assert result.screenshot_b64 is not None
        assert len(result.screenshot_b64) > 0

    @pytest.mark.asyncio
    async def test_navigation_failure(self):
        """observe_application raises NavigationError on goto failure."""
        browser, ctx, page = _make_mock_browser()
        page.goto = AsyncMock(side_effect=Exception("net::ERR_NAME_NOT_RESOLVED"))
        pw = AsyncMock()
        pw.chromium.launch = AsyncMock(return_value=browser)
        pw.start = AsyncMock(return_value=pw)
        pw.stop = AsyncMock()

        with patch("app.core.observer.async_playwright", return_value=AsyncMock(start=AsyncMock(return_value=pw))):
            with pytest.raises(NavigationError):
                await observe_application(
                    base_url="https://nonexistent.invalid",
                    url_path="/",
                )

    @pytest.mark.asyncio
    async def test_screenshot_failure(self):
        """observe_application raises on screenshot failure."""
        browser, ctx, page = _make_mock_browser()
        page.screenshot = AsyncMock(side_effect=Exception("Screenshot error"))
        pw = AsyncMock()
        pw.chromium.launch = AsyncMock(return_value=browser)
        pw.start = AsyncMock(return_value=pw)
        pw.stop = AsyncMock()

        with patch("app.core.observer.async_playwright", return_value=AsyncMock(start=AsyncMock(return_value=pw))):
            with pytest.raises(Exception):
                await observe_application(
                    base_url="https://example.com",
                    url_path="/",
                )

    @pytest.mark.asyncio
    async def test_custom_viewport(self):
        """observe_application uses the configured viewport."""
        browser, ctx, page = _make_mock_browser()
        pw = AsyncMock()
        pw.chromium.launch = AsyncMock(return_value=browser)
        pw.start = AsyncMock(return_value=pw)
        pw.stop = AsyncMock()

        with patch("app.core.observer.async_playwright", return_value=AsyncMock(start=AsyncMock(return_value=pw))):
            await observe_application(base_url="https://example.com", url_path="/")

        # Verify viewport was passed to new_context
        ctx_call = browser.new_context.call_args
        assert ctx_call.kwargs.get("viewport") == {"width": 1920, "height": 1080}


# ── Tests for _handle_auth ───────────────────────────────────────────────────


class TestHandleAuth:
    @pytest.mark.asyncio
    async def test_cookie_auth(self):
        """_handle_auth injects cookies when cookies are provided."""
        page = _make_mock_page()
        auth = {
            "cookies": [
                {"name": "session", "value": "abc123", "domain": "example.com"}
            ]
        }
        await _handle_auth(page, auth, "https://example.com")

        page.context.add_cookies.assert_called_once()
        cookies = page.context.add_cookies.call_args[0][0]
        assert cookies[0]["name"] == "session"
        assert cookies[0]["value"] == "abc123"

    @pytest.mark.asyncio
    async def test_header_auth(self):
        """_handle_auth sets extra HTTP headers when headers are provided."""
        page = _make_mock_page()
        auth = {"headers": {"Authorization": "Bearer token123"}}
        await _handle_auth(page, auth, "https://example.com")

        page.set_extra_http_headers.assert_called_once_with(
            {"Authorization": "Bearer token123"}
        )

    @pytest.mark.asyncio
    async def test_form_login(self):
        """_handle_auth performs form-based login with selectors."""
        page = _make_mock_page()
        auth = {
            "login_url": "/login",
            "username": "admin",
            "password": "secret",
            "username_selector": "#user",
            "password_selector": "#pass",
            "submit_selector": "#submit",
        }
        await _handle_auth(page, auth, "https://example.com")

        # Verify goto was called for login page
        page.goto.assert_called()
        # Verify fill was called for username and password
        page.locator.assert_any_call("#user")
        page.locator.assert_any_call("#pass")
        page.locator.assert_any_call("#submit")

    @pytest.mark.asyncio
    async def test_no_auth_does_nothing(self):
        """_handle_auth with empty credentials does nothing."""
        page = _make_mock_page()
        await _handle_auth(page, {}, "https://example.com")
        page.goto.assert_not_called()
        page.set_extra_http_headers.assert_not_called()
