"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  listTools,
  observeApplication,
  executeTool,
  type MCPTool,
} from "@/app/lib/api";

export default function ApplicationDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const { id } = params;
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [observing, setObserving] = useState(false);
  const [executing, setExecuting] = useState<string | null>(null);

  const fetchTools = useCallback(() => {
    setLoading(true);
    listTools(id)
      .then(setTools)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    fetchTools();
  }, [fetchTools]);

  const handleObserve = async () => {
    setObserving(true);
    try {
      await observeApplication(id);
      // Wait a bit then refresh tools
      setTimeout(fetchTools, 3000);
      alert(
        "Observation pipeline triggered! Tools will appear shortly."
      );
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      alert(`Failed: ${msg}`);
    } finally {
      setObserving(false);
    }
  };

  const handleExecute = async (toolId: string) => {
    setExecuting(toolId);
    try {
      const result = await executeTool(toolId);
      if (result.execution_status === "awaiting_human") {
        alert(
          "This tool requires human approval. Check the live feed for the approval modal."
        );
      } else {
        alert(`Execution queued! Status: ${result.execution_status}`);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      alert(`Execution failed: ${msg}`);
    } finally {
      setExecuting(null);
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <Link
          href="/dashboard/applications"
          className="text-sm text-blue-600 hover:underline mb-2 inline-block"
        >
          ← Back to Applications
        </Link>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Application Tools</h1>
            <p className="text-sm text-gray-500 mt-1 font-mono">{id}</p>
          </div>
          <button
            onClick={handleObserve}
            disabled={observing}
            className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 transition disabled:opacity-50"
          >
            {observing ? "Observing..." : "🔍 Run Observation"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 p-4 mb-6 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Tools list */}
      {loading ? (
        <div className="rounded-lg border bg-white p-12 text-center text-gray-400 shadow-sm">
          Loading tools...
        </div>
      ) : tools.length === 0 ? (
        <div className="rounded-lg border bg-white p-12 text-center shadow-sm">
          <p className="text-gray-400 mb-4">
            No tools discovered yet. Run an observation pipeline to map UI
            elements.
          </p>
          <button
            onClick={handleObserve}
            disabled={observing}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition disabled:opacity-50"
          >
            {observing ? "Observing..." : "Run Observation Pipeline"}
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-gray-500">
            {tools.length} tool{tools.length !== 1 ? "s" : ""} discovered
          </p>
          {tools.map((tool) => (
            <div
              key={tool.id}
              className="rounded-lg border bg-white p-5 shadow-sm"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="inline-block rounded-full bg-blue-100 text-blue-800 text-xs px-2 py-0.5 font-medium">
                      {tool.element_type}
                    </span>
                    {tool.requires_human_approval && (
                      <span className="inline-block rounded-full bg-amber-100 text-amber-800 text-xs px-2 py-0.5 font-medium">
                        ⚠️ Approval Required
                      </span>
                    )}
                  </div>
                  <h3 className="font-semibold text-gray-900">
                    {tool.semantic_intent}
                  </h3>
                  <p className="text-xs text-gray-400 mt-1 font-mono">
                    {tool.id}
                  </p>

                  {/* Tool schema preview */}
                  {tool.mcp_tool_schema &&
                    Object.keys(tool.mcp_tool_schema).length > 0 && (
                      <details className="mt-3">
                        <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">
                          View MCP Tool Schema
                        </summary>
                        <pre className="mt-2 bg-gray-50 rounded p-3 text-xs overflow-auto max-h-48">
                          {JSON.stringify(tool.mcp_tool_schema, null, 2)}
                        </pre>
                      </details>
                    )}

                  {tool.bounding_box && (
                    <p className="text-xs text-gray-400 mt-2">
                      Position: {JSON.stringify(tool.bounding_box)}
                    </p>
                  )}
                </div>

                <button
                  onClick={() => handleExecute(tool.id)}
                  disabled={executing === tool.id}
                  className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition disabled:opacity-50 shrink-0 ml-4"
                >
                  {executing === tool.id ? "Executing..." : "Execute"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
