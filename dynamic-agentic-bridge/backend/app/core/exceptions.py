"""
Typed exceptions for the Dynamic Agentic Bridge core pipeline.
Every I/O boundary raises a specific exception — no bare excepts.
"""


class BridgeError(Exception):
    """Base exception for all bridge pipeline errors."""


# ── Observer errors ──────────────────────────────────────────────────────────


class ObserverError(BridgeError):
    """Base for observer-related failures."""


class NavigationError(ObserverError):
    """Browser failed to navigate to the target URL."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Failed to navigate to {url}: {reason}")


class PageLoadTimeout(ObserverError):
    """Page did not reach a stable state within the timeout."""

    def __init__(self, url: str, timeout_ms: int) -> None:
        self.url = url
        self.timeout_ms = timeout_ms
        super().__init__(f"Page at {url} did not stabilize within {timeout_ms}ms")


class AuthenticationError(ObserverError):
    """Login flow failed — wrong credentials, missing selectors, etc."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Auth failed for {url}: {reason}")


class ScreenshotError(ObserverError):
    """Failed to capture a screenshot."""


class DOMSnapshotError(ObserverError):
    """Failed to extract a normalized DOM snapshot."""


# ── Mapper errors ────────────────────────────────────────────────────────────


class MapperError(BridgeError):
    """Base for mapper-related failures."""


class ClaudeAPIError(MapperError):
    """Anthropic API call failed (rate limit, auth, server error)."""

    def __init__(self, status_code: int | None, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Claude API error ({status_code}): {message}")


class ClaudeRateLimitError(ClaudeAPIError):
    """Rate limited by Anthropic API — caller should back off."""

    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(429, f"Rate limited. Retry after {retry_after}s" if retry_after else "Rate limited")


class VisionMappingError(MapperError):
    """Claude returned a response that could not be parsed as valid tool candidates."""


class SchemaValidationError(MapperError):
    """Claude's output failed Pydantic validation after retry."""

    def __init__(self, errors: list[dict]) -> None:
        self.validation_errors = errors
        super().__init__(f"Schema validation failed: {errors}")


# ── MCP Generator errors ────────────────────────────────────────────────────


class MCPGeneratorError(BridgeError):
    """Base for MCP generator failures."""


# ── Executor errors ──────────────────────────────────────────────────────────


class ExecutionError(BridgeError):
    """Base for tool execution failures."""


class ElementNotFoundError(ExecutionError):
    """Could not locate the target element on the live page."""


class ToolSchemaError(MCPGeneratorError):
    """Generated MCP tool schema is malformed or incomplete."""


class PersistenceError(MCPGeneratorError):
    """Failed to persist tool definitions to the database."""
