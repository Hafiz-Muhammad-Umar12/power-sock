"""
Observer module — Playwright-based legacy UI observation.

Launches a headless browser, navigates to a legacy application,
and captures a structured snapshot of its UI state: accessibility tree,
screenshot, and normalized DOM.

No raw Playwright objects are returned to callers.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from pydantic import BaseModel, Field

from app.config import settings
from app.core.exceptions import (
    AuthenticationError,
    DOMSnapshotError,
    NavigationError,
    ObserverError,
    PageLoadTimeout,
    ScreenshotError,
)

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_TIMEOUT_MS = 30_000
DOM_STABILITY_WAIT_MS = 2_000
DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}


# ── Output model ─────────────────────────────────────────────────────────────


class ObservationResult(BaseModel):
    """Structured output from observing a legacy application UI.
    Never contains raw Playwright objects.
    """

    accessibility_tree: dict = Field(default_factory=dict)
    screenshot_b64: str | None = None
    normalized_dom: dict = Field(default_factory=dict)
    state_hash: str = ""
    url: str = ""
    title: str = ""
    viewport_width: int = 1920
    viewport_height: int = 1080


# ── DOM normalizer ───────────────────────────────────────────────────────────


def _normalize_element(el: Any) -> dict | None:
    """Extract meaningful attributes from a DOM element for hashing."""
    if not isinstance(el, dict):
        return None

    tag = el.get("nodeName", "").lower()
    if not tag or tag.startswith("#") or tag.startswith("--"):
        return None

    # Only keep meaningful elements
    meaningful_tags = {
        "input", "button", "a", "select", "textarea", "form",
        "table", "tr", "td", "th", "label", "div", "span",
        "h1", "h2", "h3", "h4", "h5", "h6", "nav", "header",
        "footer", "main", "section", "aside", "img", "ul", "li",
    }
    if tag not in meaningful_tags:
        return None

    attributes = el.get("attributes", {})
    # Flatten attributes list-of-pairs into a dict
    attr_dict: dict[str, str] = {}
    if isinstance(attributes, list):
        for pair in attributes:
            if isinstance(pair, list) and len(pair) == 2:
                attr_dict[str(pair[0])] = str(pair[1])
    elif isinstance(attributes, dict):
        attr_dict = {k: str(v) for k, v in attributes.items()}

    result: dict[str, Any] = {"tag": tag}

    # Keep attributes that help identify the element's purpose
    important_attrs = {
        "id", "name", "type", "role", "aria-label", "aria-describedby",
        "href", "action", "method", "placeholder", "value", "class",
        "data-testid", "title", "alt",
    }
    for key in important_attrs:
        if key in attr_dict and attr_dict[key]:
            result[key] = attr_dict[key]

    # Recurse into children
    children = el.get("children", [])
    normalized_children = []
    for child in children:
        nc = _normalize_element(child)
        if nc is not None:
            normalized_children.append(nc)
    if normalized_children:
        result["children"] = normalized_children

    return result


def _compute_state_hash(normalized_dom: dict) -> str:
    """Compute a deterministic SHA-256 hash from the normalized DOM."""
    dom_json = json.dumps(normalized_dom, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(dom_json.encode("utf-8")).hexdigest()


# ── Auth handler ─────────────────────────────────────────────────────────────


async def _handle_auth(
    page: Page,
    auth_credentials: dict,
    base_url: str,
) -> None:
    """
    Perform login if auth_credentials are provided.

    Supports:
    - Form-based login: keys "login_url", "username_selector", "password_selector",
      "submit_selector", "username", "password"
    - Cookie/token-based: keys "cookies" (list of cookie dicts) or
      "headers" (dict of header name -> value)
    """
    if not auth_credentials:
        return

    # Cookie-based auth
    if "cookies" in auth_credentials:
        cookies = auth_credentials["cookies"]
        if isinstance(cookies, list):
            context = page.context
            for cookie in cookies:
                # Ensure url is set for Playwright
                if "url" not in cookie and "domain" not in cookie:
                    cookie["url"] = base_url
                await context.add_cookies([cookie])
            logger.info("Injected %d cookies for %s", len(cookies), base_url)
            return

    # Header-based auth (stored for later injection)
    if "headers" in auth_credentials:
        headers = auth_credentials["headers"]
        if isinstance(headers, dict):
            await page.set_extra_http_headers(headers)
            logger.info("Set extra HTTP headers for %s", base_url)
            # If there's also a login_url, navigate to it after setting headers
            if "login_url" in auth_credentials:
                login_url = auth_credentials["login_url"]
                if not login_url.startswith("http"):
                    login_url = base_url.rstrip("/") + "/" + login_url.lstrip("/")
                await page.goto(login_url, wait_until="domcontentloaded")
            return

    # Form-based login
    login_url = auth_credentials.get("login_url")
    username = auth_credentials.get("username", "")
    password = auth_credentials.get("password", "")
    username_sel = auth_credentials.get("username_selector", 'input[name="username"], input[type="email"]')
    password_sel = auth_credentials.get("password_selector", 'input[name="password"], input[type="password"]')
    submit_sel = auth_credentials.get("submit_selector", 'button[type="submit"], input[type="submit"]')

    if login_url:
        if not login_url.startswith("http"):
            login_url = base_url.rstrip("/") + "/" + login_url.lstrip("/")
        await page.goto(login_url, wait_until="domcontentloaded")
        logger.info("Navigated to login page: %s", login_url)

    try:
        # Fill username
        username_input = page.locator(username_sel).first
        await username_input.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
        await username_input.fill(username)

        # Fill password
        password_input = page.locator(password_sel).first
        await password_input.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
        await password_input.fill(password)

        # Click submit
        submit_btn = page.locator(submit_sel).first
        await submit_btn.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
        await submit_btn.click()

        # Wait for navigation after login
        await page.wait_for_load_state("networkidle", timeout=DEFAULT_TIMEOUT_MS)
        logger.info("Form-based login successful for %s", base_url)
    except Exception as e:
        raise AuthenticationError(base_url, str(e)) from e


# ── Core observation ─────────────────────────────────────────────────────────


async def observe_application(
    base_url: str,
    auth_credentials: dict | None = None,
    url_path: str = "/",
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> ObservationResult:
    """
    Launch a headless browser, navigate to the legacy app, and capture
    its UI state.

    Returns an ObservationResult with no raw Playwright objects.
    Raises typed ObserverError subclasses on failure.
    """
    full_url = base_url.rstrip("/") + "/" + url_path.lstrip("/")
    logger.info("Starting observation of %s", full_url)

    playwright_instance: Playwright | None = None
    browser: Browser | None = None

    try:
        playwright_instance = await async_playwright().start()
        browser = await playwright_instance.chromium.launch(
            headless=settings.playwright_headless,
        )
        context: BrowserContext = await browser.new_context(
            viewport=DEFAULT_VIEWPORT,
            ignore_https_errors=True,
        )
        page: Page = await context.new_page()

        # ── Navigate ────────────────────────────────────────────────────
        try:
            await page.goto(full_url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as e:
            raise NavigationError(full_url, str(e)) from e

        # ── Auth ────────────────────────────────────────────────────────
        if auth_credentials:
            await _handle_auth(page, auth_credentials, base_url)
            # After auth, navigate to the target URL (auth may have redirected)
            current_url = page.url
            target_origin = base_url.rstrip("/")
            if not current_url.startswith(target_origin):
                try:
                    await page.goto(full_url, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception as e:
                    raise NavigationError(full_url, f"After auth redirect: {e}") from e

        # ── Wait for DOM stability ──────────────────────────────────────
        try:
            # Wait for network idle (no pending requests for a beat)
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            logger.warning(
                "Network idle timeout for %s — proceeding with current state", full_url
            )

        # Additional stability wait for JS-rendered content
        await asyncio.sleep(DOM_STABILITY_WAIT_MS / 1000)

        # ── Capture page title ──────────────────────────────────────────
        title = await page.title()

        # ── Capture accessibility tree ──────────────────────────────────
        try:
            a11y_snapshot = await page.accessibility.snapshot()
            accessibility_tree = a11y_snapshot if isinstance(a11y_snapshot, dict) else {}
        except Exception as e:
            logger.warning("Failed to capture accessibility tree: %s", e)
            accessibility_tree = {}

        # ── Capture screenshot ──────────────────────────────────────────
        try:
            screenshot_bytes = await page.screenshot(type="png", full_page=True)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
        except Exception as e:
            raise ScreenshotError(f"Failed to capture screenshot: {e}") from e

        # ── Capture normalized DOM ──────────────────────────────────────
        try:
            raw_dom = await page.evaluate("""() => {
                function serialize(node) {
                    if (!node) return null;
                    const result = {
                        nodeName: node.nodeName,
                        attributes: {},
                        children: []
                    };
                    if (node.attributes) {
                        for (let i = 0; i < node.attributes.length; i++) {
                            const attr = node.attributes[i];
                            result.attributes[attr.name] = attr.value;
                        }
                    }
                    if (node.childNodes) {
                        for (const child of node.childNodes) {
                            if (child.nodeType === 1) { // Element node
                                const serialized = serialize(child);
                                if (serialized) result.children.push(serialized);
                            }
                        }
                    }
                    return result;
                }
                return serialize(document.documentElement);
            }""")
            normalized_dom = _normalize_element(raw_dom) or {}
        except Exception as e:
            raise DOMSnapshotError(f"Failed to snapshot DOM: {e}") from e

        # ── Compute state hash ──────────────────────────────────────────
        state_hash = _compute_state_hash(normalized_dom)

        # ── Build result ────────────────────────────────────────────────
        result = ObservationResult(
            accessibility_tree=accessibility_tree,
            screenshot_b64=screenshot_b64,
            normalized_dom=normalized_dom,
            state_hash=state_hash,
            url=page.url,
            title=title,
            viewport_width=DEFAULT_VIEWPORT["width"],
            viewport_height=DEFAULT_VIEWPORT["height"],
        )

        logger.info(
            "Observation complete: url=%s, state_hash=%s, elements=%d",
            result.url,
            result.state_hash[:12],
            len(accessibility_tree.get("children", [])),
        )
        return result

    except ObserverError:
        raise
    except Exception as e:
        raise ObserverError(f"Unexpected error during observation: {e}") from e
    finally:
        if browser:
            await browser.close()
        if playwright_instance:
            await playwright_instance.stop()
