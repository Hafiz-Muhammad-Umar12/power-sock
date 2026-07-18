"""Check raw moondream output for brandsob.com."""
import asyncio
import sys
import os
import json
import logging

os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Enable raw output logging
logging.basicConfig(level=logging.INFO, format="%(message)s")

from app.core.observer import observe_application
from app.core.mapper import _call_ollama, _build_ollama_messages, DEFAULT_MODEL


async def main():
    print("Observing brandsob.com...")
    obs = await observe_application("https://www.brandsob.com")
    print(f"  Screenshot: {len(obs.screenshot_b64)} chars")
    print(f"  A11y tree keys: {list(obs.accessibility_tree.keys())}")

    messages = _build_ollama_messages(
        screenshot_b64=obs.screenshot_b64,
        accessibility_tree=obs.accessibility_tree,
        url=obs.url,
        title=obs.title,
    )

    # Show the user message size
    user_content = messages[1]["content"]
    print(f"\n  User message length: {len(user_content)} chars")
    print(f"  Has image: {'images' in messages[1]}")

    print("\nCalling moondream...")
    raw = await _call_ollama(messages, model=DEFAULT_MODEL)
    print(f"\n  Raw output ({len(raw)} chars):")
    print(f"  {raw[:2000]}")
    if len(raw) > 2000:
        print(f"  ... ({len(raw) - 2000} more chars)")

asyncio.run(main())
