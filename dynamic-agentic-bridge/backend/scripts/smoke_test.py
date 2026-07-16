"""
Live smoke test: observe example.com and map its UI elements via Claude Vision.
No mocking -- real Playwright browser + real Anthropic API call.
"""

import asyncio
import json
import sys
import os
import io

# Fix Windows terminal encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Ensure we're in the right directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    print("=" * 70)
    print("LIVE SMOKE TEST -- example.com (no auth)")
    print("=" * 70)

    # -- Step 1: Observe --------------------------------------------------
    print("\n>>> Step 1: Observing example.com with Playwright...")
    from app.core.observer import observe_application

    try:
        result = await observe_application(
            base_url="https://example.com",
            auth_credentials=None,
            url_path="/",
        )
    except Exception as e:
        print(f"X Observer failed: {e}")
        return

    print("[OK] Observation complete!")
    print(f"   URL: {result.url}")
    print(f"   Title: {result.title}")
    print(f"   State hash: {result.state_hash}")
    print(f"   Screenshot size: {len(result.screenshot_b64) if result.screenshot_b64 else 0} chars (base64)")
    print(f"   Accessibility tree keys: {list(result.accessibility_tree.keys())}")
    print(f"   Normalized DOM keys: {list(result.normalized_dom.keys())}")

    # Show accessibility tree summary
    a11y = result.accessibility_tree
    def count_nodes(node, depth=0):
        count = 1
        for child in node.get("children", []):
            count += count_nodes(child, depth + 1)
        return count

    node_count = count_nodes(a11y) if a11y else 0
    print(f"   A11y tree nodes: {node_count}")

    # Show normalized DOM summary
    dom = result.normalized_dom
    def summarize_dom(node, depth=0):
        summary = []
        tag = node.get("tag", "?")
        attrs = {k: v for k, v in node.items() if k not in ("tag", "children")}
        summary.append(f"{'  ' * depth}<{tag} {attrs}>")
        for child in node.get("children", []):
            summary.extend(summarize_dom(child, depth + 1))
        return summary

    dom_lines = summarize_dom(dom) if dom else []
    print(f"   Normalized DOM structure:")
    for line in dom_lines[:30]:
        print(f"     {line}")
    if len(dom_lines) > 30:
        print(f"     ... and {len(dom_lines) - 30} more elements")

    # -- Step 2: Map with Claude Vision -----------------------------------
    print("\n>>> Step 2: Mapping elements via Claude Vision API...")
    from app.core.mapper import map_elements

    try:
        candidates = await map_elements(
            screenshot_b64=result.screenshot_b64,
            accessibility_tree=result.accessibility_tree,
            url=result.url,
            title=result.title,
        )
    except Exception as e:
        print(f"X Mapper failed: {e}")
        import traceback
        traceback.print_exc()
        return

    print(f"[OK] Mapping complete! Found {len(candidates)} tool candidates.\n")

    # -- Show results -----------------------------------------------------
    print("=" * 70)
    print("MCP TOOL CANDIDATES (from Claude Vision)")
    print("=" * 70)

    for i, c in enumerate(candidates, 1):
        print(f"\n--- Candidate {i} ---")
        print(f"  Element type:          {c.element_type}")
        print(f"  Semantic intent:       {c.semantic_intent}")
        print(f"  Requires approval:     {c.requires_human_approval}")
        if c.bounding_box:
            print(f"  Bounding box:          {json.dumps(c.bounding_box)}")
        print(f"  Tool schema:           {json.dumps(c.suggested_tool_schema, indent=4)}")

    # -- Step 3: Generate MCP tools ---------------------------------------
    print("\n" + "=" * 70)
    print("GENERATED MCP TOOL DEFINITIONS")
    print("=" * 70)

    from app.core.mcp_generator import generate_mcp_tool_definition

    for i, c in enumerate(candidates, 1):
        tool_def = generate_mcp_tool_definition(c)
        print(f"\n--- Tool {i} ---")
        print(f"  Name:          {tool_def['name']}")
        print(f"  Description:   {tool_def['description']}")
        print(f"  Input Schema:  {json.dumps(tool_def['inputSchema'], indent=4)}")
        print(f"  Annotations:   {json.dumps(tool_def['annotations'], indent=4)}")

    # -- Summary ----------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"SMOKE TEST COMPLETE")
    print(f"  Site:           {result.url}")
    print(f"  Elements found: {len(candidates)}")
    print(f"  Approval gates: {sum(1 for c in candidates if c.requires_human_approval)}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
