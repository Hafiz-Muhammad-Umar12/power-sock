"""Live E2E test: observe -> map -> show tool candidates."""
import asyncio
import sys
import os

os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.observer import observe_application
from app.core.mapper import map_elements, _resize_screenshot


async def run_pipeline(url, label):
    print(f"\n{'='*60}")
    print(f"  {label}: {url}")
    print(f"{'='*60}")

    # Step 1: Observe
    print("\n[1/2] Observing...")
    obs = await observe_application(url)
    print(f"  URL: {obs.url}")
    print(f"  Title: {obs.title}")
    orig_size = len(obs.screenshot_b64) if obs.screenshot_b64 else 0
    print(f"  Screenshot (original): {orig_size:,} chars base64")
    a11y_children = len(obs.accessibility_tree.get("children", []))
    print(f"  A11y tree: {a11y_children} top-level children")

    # Show resized size
    if obs.screenshot_b64:
        resized = _resize_screenshot(obs.screenshot_b64)
        print(f"  Screenshot (resized):  {len(resized):,} chars base64")

    # Step 2: Map
    print("\n[2/2] Mapping with moondream...")
    try:
        candidates = await map_elements(
            screenshot_b64=obs.screenshot_b64,
            accessibility_tree=obs.accessibility_tree,
            url=obs.url,
            title=obs.title,
        )

        print(f"\n  Tools discovered: {len(candidates)}")
        for i, c in enumerate(candidates, 1):
            print(f"     {i}. [{c.element_type}] {c.semantic_intent}")
            if c.bounding_box:
                print(f"        bounding_box: {c.bounding_box}")
            if c.suggested_tool_schema:
                print(f"        suggested_tool: {c.suggested_tool_schema}")
        return candidates
    except Exception as e:
        print(f"\n  FAILED: {type(e).__name__}: {e}")
        return None


async def main():
    all_results = {}

    # Test 1 & 2: example.com (simple case) x2
    r1 = await run_pipeline("https://example.com", "TEST 1: example.com (run 1)")
    all_results["example_run1"] = len(r1) if r1 is not None else "FAIL"

    r2 = await run_pipeline("https://example.com", "TEST 2: example.com (run 2)")
    all_results["example_run2"] = len(r2) if r2 is not None else "FAIL"

    # Test 3 & 4: brandsob.com (previously failed with context error) x2
    r3 = await run_pipeline("https://www.brandsob.com", "TEST 3: brandsob.com (run 1)")
    all_results["brandsob_run1"] = len(r3) if r3 is not None else "FAIL"

    r4 = await run_pipeline("https://www.brandsob.com", "TEST 4: brandsob.com (run 2)")
    all_results["brandsob_run2"] = len(r4) if r4 is not None else "FAIL"

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    for k, v in all_results.items():
        print(f"  {k}: {v} tools" if isinstance(v, int) else f"  {k}: {v}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
