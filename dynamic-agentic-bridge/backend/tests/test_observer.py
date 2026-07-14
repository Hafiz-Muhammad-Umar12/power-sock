"""
Unit tests for the observer module.
Playwright is mocked — we test DOM normalization, state hashing, and auth logic.
"""

import json

import pytest

from app.core.observer import (
    ObservationResult,
    _compute_state_hash,
    _normalize_element,
)
from app.core.exceptions import ObserverError


class TestNormalizeElement:
    """Test the DOM normalization logic."""

    def test_returns_none_for_non_dict(self):
        assert _normalize_element("not a dict") is None
        assert _normalize_element(None) is None
        assert _normalize_element(42) is None

    def test_returns_none_for_comment_nodes(self):
        assert _normalize_element({"nodeName": "#comment"}) is None

    def test_returns_none_for_non_meaningful_tags(self):
        assert _normalize_element({"nodeName": "br"}) is None
        assert _normalize_element({"nodeName": "script"}) is None
        assert _normalize_element({"nodeName": "style"}) is None

    def test_extracts_meaningful_element(self):
        el = {
            "nodeName": "button",
            "attributes": [
                ["type", "submit"],
                ["class", "btn-primary"],
                ["id", "submit-btn"],
            ],
            "children": [],
        }
        result = _normalize_element(el)
        assert result is not None
        assert result["tag"] == "button"
        assert result["type"] == "submit"
        assert result["id"] == "submit-btn"

    def test_handles_dict_attributes(self):
        el = {
            "nodeName": "input",
            "attributes": {"type": "email", "placeholder": "Email"},
        }
        result = _normalize_element(el)
        assert result is not None
        assert result["type"] == "email"
        assert result["placeholder"] == "Email"

    def test_recurses_into_children(self):
        el = {
            "nodeName": "form",
            "attributes": {"action": "/submit"},
            "children": [
                {
                    "nodeName": "input",
                    "attributes": {"type": "text", "name": "username"},
                    "children": [],
                },
                {
                    "nodeName": "button",
                    "attributes": {"type": "submit"},
                    "children": [],
                },
            ],
        }
        result = _normalize_element(el)
        assert result is not None
        assert result["tag"] == "form"
        assert result["action"] == "/submit"
        assert len(result["children"]) == 2
        assert result["children"][0]["tag"] == "input"
        assert result["children"][1]["tag"] == "button"

    def test_filters_out_non_meaningful_children(self):
        el = {
            "nodeName": "div",
            "attributes": {},
            "children": [
                {"nodeName": "br", "attributes": {}, "children": []},
                {"nodeName": "span", "attributes": {"class": "text"}, "children": []},
            ],
        }
        result = _normalize_element(el)
        assert result is not None
        # Only span should survive
        assert len(result["children"]) == 1
        assert result["children"][0]["tag"] == "span"

    def test_empty_element(self):
        el = {"nodeName": "div", "attributes": {}, "children": []}
        result = _normalize_element(el)
        assert result is not None
        assert result["tag"] == "div"
        assert "children" not in result  # Empty children omitted


class TestComputeStateHash:
    def test_deterministic(self):
        dom = {"tag": "html", "children": [{"tag": "button"}]}
        h1 = _compute_state_hash(dom)
        h2 = _compute_state_hash(dom)
        assert h1 == h2

    def test_different_doms_different_hashes(self):
        dom1 = {"tag": "html", "children": [{"tag": "button"}]}
        dom2 = {"tag": "html", "children": [{"tag": "link"}]}
        assert _compute_state_hash(dom1) != _compute_state_hash(dom2)

    def test_order_independent(self):
        dom1 = {"tag": "html", "b": 1, "a": 2}
        dom2 = {"tag": "html", "a": 2, "b": 1}
        assert _compute_state_hash(dom1) == _compute_state_hash(dom2)

    def test_produces_sha256_hex(self):
        h = _compute_state_hash({"tag": "test"})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestObservationResult:
    def test_default_values(self):
        result = ObservationResult()
        assert result.accessibility_tree == {}
        assert result.screenshot_b64 is None
        assert result.normalized_dom == {}
        assert result.state_hash == ""
        assert result.url == ""

    def test_serialization(self):
        result = ObservationResult(
            url="https://example.com",
            state_hash="abc123",
            title="Test Page",
        )
        data = result.model_dump()
        assert data["url"] == "https://example.com"
        assert data["state_hash"] == "abc123"
        assert isinstance(data, dict)
