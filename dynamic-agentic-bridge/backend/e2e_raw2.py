"""Test moondream with different prompt variations."""
import asyncio
import sys
import os
import json

os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.observer import observe_application
from app.core.mapper import _call_ollama, DEFAULT_MODEL


async def test_prompt(label, messages):
    print(f"\n--- {label} ---")
    raw = await _call_ollama(messages, model=DEFAULT_MODEL)
    print(f"  Response ({len(raw)} chars): {raw[:500]}")


async def main():
    obs = await observe_application("https://www.brandsob.com")

    # Test 1: Minimal prompt, image only, no a11y
    await test_prompt("Test 1: Ultra-minimal, image only", [
        {"role": "system", "content": "Reply with a JSON array of interactive elements you see."},
        {"role": "user", "content": "What buttons and links do you see?", "images": [obs.screenshot_b64]},
    ])

    # Test 2: With example output
    await test_prompt("Test 2: With example", [
        {"role": "system", "content": "You see a website screenshot. Return a JSON array of clickable elements."},
        {"role": "user", "content": 'List buttons and links. Example: [{"type":"button","label":"Click me"}]\nNow list what you see:', "images": [obs.screenshot_b64]},
    ])

    # Test 3: No image, text only with a11y
    from app.core.mapper import _flatten_a11y_tree
    flat = _flatten_a11y_tree(obs.accessibility_tree)
    a11y_text = "\n".join(flat)
    await test_prompt("Test 3: Text only (a11y tree, no image)", [
        {"role": "system", "content": "You see an accessibility tree. Return a JSON array of interactive elements."},
        {"role": "user", "content": f"Accessibility tree:\n{a11y_text}\n\nList interactive elements as JSON array."},
    ])

    # Test 4: Simple question format
    await test_prompt("Test 4: Simple question", [
        {"role": "user", "content": "This is a website. List the buttons and links as a JSON array like [{\"type\":\"button\",\"label\":\"...\"}]", "images": [obs.screenshot_b64]},
    ])


asyncio.run(main())
