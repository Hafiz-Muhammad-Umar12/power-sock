"""Debug a11y tree structure."""
import asyncio
import sys
import os
import json

os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.observer import observe_application
from app.core.mapper import _trim_a11y_tree


async def main():
    for url in ["https://example.com", "https://www.brandsob.com"]:
        print(f"\n{'='*60}")
        print(f"  {url}")
        print(f"{'='*60}")
        obs = await observe_application(url)
        tree = obs.accessibility_tree
        print(f"\n  Raw tree keys: {list(tree.keys())}")
        print(f"  Raw tree (first 500 chars):")
        print(json.dumps(tree, indent=2)[:500])

        trimmed = _trim_a11y_tree(tree)
        trimmed_json = json.dumps(trimmed, ensure_ascii=False)
        print(f"\n  Trimmed tree ({len(trimmed_json)} chars):")
        print(trimmed_json[:1000])

asyncio.run(main())
