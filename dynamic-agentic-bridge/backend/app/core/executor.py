"""
Playwright element executor — the core interaction engine.

Given a mapped MCP tool (element_type, bounding_box, semantic_intent) and
action parameters from the user, this module:
1. Launches a headless browser against the legacy app
2. Locates the actual element on the live page
3. Performs the real action (click, fill, select)
4. Captures a screenshot after the action
5. Returns a structured ExecutionResult
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import (
    Browser,
    Locator,
    Page,
    Playwright,
    async_playwright,
)
from pydantic import BaseModel

from app.config import settings
from app.core.exceptions import (
    ExecutionError,
    ElementNotFoundError,
    NavigationError,
)
from app.core.playwright_runner import run_playwright_coro

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 15_000
VIEWPORT = {"width": 1920, "height": 1080}


def _sanitize_error(exc: Exception) -> str:
    """Extract a safe error message, stripping URLs and sensitive content."""
    msg = str(exc)
    # Remove URLs that might contain tokens
    import re
    msg = re.sub(r'https?://\S+', '[URL]', msg)
    # Remove anything that looks like a key or token
    msg = re.sub(r'(sk-[a-zA-Z0-9_-]{20,})', '[REDACTED]', msg)
    # Truncate
    return msg[:500]


# ── Result model ─────────────────────────────────────────────────────────────


class ExecutionResult(BaseModel):
    """Structured result from executing an action against a live legacy app."""
    success: bool
    action_performed: str
    screenshot_b64: str | None = None
    element_found: bool = False
    post_action_url: str = ""
    error_message: str | None = None


# ── Element locator ──────────────────────────────────────────────────────────


async def _locate_by_bounding_box(
    page: Page,
    bounding_box: dict,
    element_type: str,
) -> Locator | None:
    """
    Locate an element by its bounding_box coordinates from the mapper.

    The bounding_box is {x, y, width, height} as percentages of the viewport.
    We convert to pixel coordinates and find the topmost interactive element
    at that position.
    """
    vp_w = VIEWPORT["width"]
    vp_h = VIEWPORT["height"]

    # Convert percentage coordinates to pixels
    x_pct = bounding_box.get("x", 0)
    y_pct = bounding_box.get("y", 0)
    w_pct = bounding_box.get("width", 5)
    h_pct = bounding_box.get("height", 5)

    # Center of the bounding box in pixels
    center_x = (x_pct + w_pct / 2) / 100 * vp_w
    center_y = (y_pct + h_pct / 2) / 100 * vp_h

    # Clamp to viewport
    center_x = max(1, min(center_x, vp_w - 1))
    center_y = max(1, min(center_y, vp_h - 1))

    logger.debug(
        "Locating element at pixel (%.0f, %.0f) from bbox %s",
        center_x, center_y, bounding_box,
    )

    # Strategy: use elementFromPoint to find what's at that coordinate
    element_handle = await page.evaluate_handle(
        """(coords) => {
            const el = document.elementFromPoint(coords.x, coords.y);
            if (!el) return null;
            // Walk up to find the nearest interactive ancestor
            const interactive = ['BUTTON', 'A', 'INPUT', 'SELECT', 'TEXTAREA', 'LABEL'];
            let current = el;
            while (current && current !== document.body) {
                if (interactive.includes(current.tagName)) return current;
                if (current.getAttribute('role') === 'button' ||
                    current.getAttribute('role') === 'link' ||
                    current.getAttribute('tabindex') === '0') return current;
                current = current.parentElement;
            }
            // Return the element itself if nothing interactive found
            return el;
        }""",
        {"x": center_x, "y": center_y},
    )

    if element_handle is None:
        return None

    # Convert the JSHandle to a Locator by generating a unique selector
    selector = await page.evaluate(
        """(el) => {
            // Generate a unique CSS selector for the element
            if (el.id) return '#' + CSS.escape(el.id);

            // Try data-testid
            const testId = el.getAttribute('data-testid');
            if (testId) return '[data-testid="' + testId + '"]';

            // Build a path
            const path = [];
            let current = el;
            while (current && current !== document.body) {
                let selector = current.tagName.toLowerCase();
                if (current.id) {
                    selector = '#' + CSS.escape(current.id);
                    path.unshift(selector);
                    break;
                }
                const parent = current.parentElement;
                if (parent) {
                    const siblings = Array.from(parent.children).filter(
                        c => c.tagName === current.tagName
                    );
                    if (siblings.length > 1) {
                        const index = siblings.indexOf(current) + 1;
                        selector += ':nth-of-type(' + index + ')';
                    }
                }
                path.unshift(selector);
                current = current.parentElement;
            }
            return path.join(' > ');
        }""",
        element_handle,
    )

    if not selector:
        return None

    logger.debug("Resolved element selector: %s", selector)
    locator = page.locator(selector).first
    return locator


async def _locate_by_text_and_type(
    page: Page,
    semantic_intent: str,
    element_type: str,
) -> Locator | None:
    """
    Fallback: locate element by matching its visible text against the
    semantic_intent, filtered by element_type.
    """
    tag_map = {
        "button": "button",
        "link": "a",
        "input": "input",
        "select": "select",
        "textarea": "textarea",
        "form": "form",
    }
    tag = tag_map.get(element_type, element_type)

    # Try exact text match first
    locator = page.locator(f"{tag}:has-text('{semantic_intent}')").first
    try:
        if await locator.count() > 0:
            return locator
    except Exception:
        pass

    # Try aria-label match
    locator = page.locator(f'{tag}[aria-label*="{semantic_intent}"]').first
    try:
        if await locator.count() > 0:
            return locator
    except Exception:
        pass

    # Try placeholder match (for inputs)
    if element_type in ("input", "textarea"):
        locator = page.locator(
            f'{tag}[placeholder*="{semantic_intent}"]'
        ).first
        try:
            if await locator.count() > 0:
                return locator
        except Exception:
            pass

    return None


async def _locate_element(
    page: Page,
    bounding_box: dict | None,
    semantic_intent: str,
    element_type: str,
) -> Locator:
    """
    Locate an element on the page using multiple strategies in order:
    1. Bounding box coordinates (most reliable when mapper is accurate)
    2. Text/aria-label matching with element type filter
    3. Raise ElementNotFoundError if all strategies fail
    """
    # Strategy 1: bounding box
    if bounding_box:
        locator = await _locate_by_bounding_box(page, bounding_box, element_type)
        if locator:
            try:
                # Verify the element is actually visible and interactive
                await locator.wait_for(state="visible", timeout=3000)
                logger.info("Located element via bounding_box")
                return locator
            except Exception:
                logger.debug("Bounding box locator not visible, trying next strategy")

    # Strategy 2: text/type matching
    locator = await _locate_by_text_and_type(page, semantic_intent, element_type)
    if locator:
        try:
            await locator.wait_for(state="visible", timeout=3000)
            logger.info("Located element via text/type matching")
            return locator
        except Exception:
            logger.debug("Text locator not visible, trying next strategy")

    # Strategy 3: broad search — find any element matching the type with
    # partial text match
    try:
        all_elements = page.locator(element_type)
        count = await all_elements.count()
        for i in range(count):
            el = all_elements.nth(i)
            text = (await el.inner_text()).lower()
            if any(word in text for word in semantic_intent.lower().split()):
                logger.info("Located element via broad text search (index %d)", i)
                return el
    except Exception:
        pass

    raise ElementNotFoundError(
        f"Could not locate {element_type} element matching "
        f"'{semantic_intent}' on the page"
    )


# ── Action performers ────────────────────────────────────────────────────────


async def _perform_click(locator: Locator) -> str:
    """Click the located element."""
    await locator.click(timeout=DEFAULT_TIMEOUT_MS)
    return "click"


async def _perform_fill(locator: Locator, value: str) -> str:
    """Fill an input/textarea with the given value."""
    await locator.fill(value, timeout=DEFAULT_TIMEOUT_MS)
    return f"fill('{value}')"


async def _perform_select(locator: Locator, value: str) -> str:
    """Select a dropdown option by value or label."""
    await locator.select_option(value=value, timeout=DEFAULT_TIMEOUT_MS)
    return f"select('{value}')"


async def _perform_type(locator: Locator, value: str) -> str:
    """Type text character-by-character (for inputs that need keystroke events)."""
    await locator.press_sequentially(value, timeout=DEFAULT_TIMEOUT_MS)
    return f"type('{value}')"


async def _perform_action(
    locator: Locator,
    element_type: str,
    action_params: dict,
) -> str:
    """
    Dispatch the appropriate action based on element type and parameters.

    action_params keys:
    - value: the text/value to fill/select/type
    - action: override the default action ("click", "fill", "select", "type")
    """
    explicit_action = action_params.get("action")
    value = action_params.get("value", "")

    if explicit_action == "click" or (
        not explicit_action and not value and element_type in ("button", "link", "a")
    ):
        return await _perform_click(locator)

    if explicit_action == "fill" or (
        not explicit_action and element_type in ("input", "textarea")
    ):
        if not value:
            raise ExecutionError(
                f"Action 'fill' requires a 'value' parameter for {element_type}"
            )
        return await _perform_fill(locator, value)

    if explicit_action == "select" or (
        not explicit_action and element_type == "select"
    ):
        if not value:
            raise ExecutionError(
                "Action 'select' requires a 'value' parameter"
            )
        return await _perform_select(locator, value)

    if explicit_action == "type":
        if not value:
            raise ExecutionError(
                "Action 'type' requires a 'value' parameter"
            )
        return await _perform_type(locator, value)

    # Default: click
    return await _perform_click(locator)


# ── Main executor ────────────────────────────────────────────────────────────


async def _execute_inner(
    full_url: str,
    base_url: str,
    element_type: str,
    semantic_intent: str,
    bounding_box: dict | None,
    action_params: dict,
    auth_credentials: dict | None,
) -> ExecutionResult:
    """
    Inner async function that runs Playwright in an isolated thread.
    All ``await`` calls here execute inside the dedicated Playwright thread's
    event loop, not the main FastAPI/asyncpg loop.
    """
    playwright_instance: Playwright | None = None
    browser: Browser | None = None

    try:
        playwright_instance = await async_playwright().start()
        browser = await playwright_instance.chromium.launch(
            headless=settings.playwright_headless,
        )
        context = await browser.new_context(
            viewport=VIEWPORT,
            ignore_https_errors=True,
        )

        # Inject auth cookies if present
        if auth_credentials and "cookies" in auth_credentials:
            for cookie in auth_credentials["cookies"]:
                if "url" not in cookie and "domain" not in cookie:
                    cookie["url"] = base_url
                await context.add_cookies([cookie])

        page = await context.new_page()

        # Set extra headers if present
        if auth_credentials and "headers" in auth_credentials:
            await page.set_extra_http_headers(auth_credentials["headers"])

        # Navigate
        try:
            await page.goto(full_url, wait_until="networkidle", timeout=DEFAULT_TIMEOUT_MS)
        except Exception as e:
            return ExecutionResult(
                success=False,
                action_performed="navigate",
                element_found=False,
                error_message=f"Navigation failed: {_sanitize_error(e)}",
            )

        # If form-based login needed
        if auth_credentials and "login_url" in auth_credentials:
            from app.core.observer import _handle_auth
            try:
                await _handle_auth(page, auth_credentials, base_url)
                await page.goto(full_url, wait_until="networkidle", timeout=DEFAULT_TIMEOUT_MS)
            except Exception as e:
                return ExecutionResult(
                    success=False,
                    action_performed="auth",
                    element_found=False,
                    error_message=f"Authentication failed: {_sanitize_error(e)}",
                )

        # Locate the element
        try:
            locator = await _locate_element(
                page, bounding_box, semantic_intent, element_type
            )
        except ElementNotFoundError as e:
            return ExecutionResult(
                success=False,
                action_performed="locate",
                element_found=False,
                error_message=str(e),
            )

        # Perform the action
        try:
            action_desc = await _perform_action(locator, element_type, action_params)
        except Exception as e:
            return ExecutionResult(
                success=False,
                action_performed="action",
                element_found=True,
                error_message=f"Action failed: {_sanitize_error(e)}",
            )

        # Wait for any resulting navigation or DOM update
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        await asyncio.sleep(0.5)

        # Capture screenshot
        try:
            screenshot_bytes = await page.screenshot(type="png", full_page=True)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
        except Exception as e:
            logger.warning("Screenshot capture failed: %s", e)
            screenshot_b64 = None

        result = ExecutionResult(
            success=True,
            action_performed=action_desc,
            screenshot_b64=screenshot_b64,
            element_found=True,
            post_action_url=page.url,
        )
        logger.info(
            "Tool executed successfully: %s -> %s at %s",
            semantic_intent, action_desc, page.url,
        )
        return result

    finally:
        if browser:
            await browser.close()
        if playwright_instance:
            await playwright_instance.stop()


async def execute_tool_action(
    base_url: str,
    url_path: str,
    element_type: str,
    semantic_intent: str,
    bounding_box: dict | None,
    action_params: dict,
    auth_credentials: dict | None = None,
) -> ExecutionResult:
    """
    Execute a tool action against a live legacy application.

    Playwright runs in an isolated thread with its own event loop so that
    ProactorEventLoop is used on Windows (required for subprocess launch).

    1. Launches Playwright browser
    2. Navigates to the app URL
    3. Locates the target element
    4. Performs the action (click/fill/select)
    5. Captures screenshot after action
    6. Returns structured result
    """
    full_url = base_url.rstrip("/") + "/" + url_path.lstrip("/")
    logger.info("Executing tool: %s at %s", semantic_intent, full_url)

    try:
        return await run_playwright_coro(
            _execute_inner(
                full_url, base_url, element_type, semantic_intent,
                bounding_box, action_params, auth_credentials,
            )
        )
    except ExecutionError:
        raise
    except Exception as e:
        return ExecutionResult(
            success=False,
            action_performed="unknown",
            element_found=False,
            error_message=f"Unexpected error: {_sanitize_error(e)}",
        )
