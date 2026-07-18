"""Debug moondream retry failures."""
import asyncio
import sys
import os
import logging

os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(message)s")

from app.core.observer import observe_application
from app.core.mapper import _call_ollama, _parse_candidates, DEFAULT_MODEL, MAX_RETRIES


async def main():
    obs = await observe_application("https://example.com")
    from app.core.mapper import _build_ollama_messages
    messages = _build_ollama_messages(
        screenshot_b64=obs.screenshot_b64,
        accessibility_tree=obs.accessibility_tree,
        url=obs.url,
        title=obs.title,
    )

    for i in range(5):
        print(f"\n--- Attempt {i+1} ---")
        raw = await _call_ollama(messages, DEFAULT_MODEL)
        print(f"  Raw ({len(raw)} chars): {repr(raw[:300])}")
        try:
            parsed = _parse_candidates(raw)
            print(f"  Parsed OK: {len(parsed)} candidates")
            for c in parsed:
                print(f"    {c}")
        except Exception as e:
            print(f"  Parse FAILED: {e}")


asyncio.run(main())
