/**
 * Typed API client for the Dynamic Agentic Bridge backend.
 * No hardcoded URLs — uses environment variable.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }

  return res.json();
}

// ── Types ───────────────────────────────────────────────────────────────────

export interface Application {
  id: string;
  name: string;
  base_url: string;
  created_at: string;
}

export interface MCPTool {
  id: string;
  state_node_id: string;
  element_type: string;
  semantic_intent: string;
  bounding_box: Record<string, unknown> | null;
  mcp_tool_schema: Record<string, unknown>;
  requires_human_approval: boolean;
  created_at: string;
}

export interface Execution {
  id: string;
  session_id: string;
  app_id: string;
  tool_id: string | null;
  action_payload: Record<string, unknown>;
  execution_status: string;
  error_message: string | null;
  screenshot_after_action: string | null;
  created_at: string;
}

// ── API functions ───────────────────────────────────────────────────────────

export async function listApplications(): Promise<Application[]> {
  return apiFetch<Application[]>("/api/applications");
}

export async function createApplication(data: {
  name: string;
  base_url: string;
  auth_credentials?: Record<string, unknown>;
}): Promise<Application> {
  return apiFetch<Application>("/api/applications", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function observeApplication(
  appId: string,
): Promise<{ session_id: string; status: string }> {
  return apiFetch(`/api/applications/${appId}/observe`, {
    method: "POST",
  });
}

export async function listTools(appId: string): Promise<MCPTool[]> {
  return apiFetch<MCPTool[]>(`/api/applications/${appId}/tools`);
}

export async function executeTool(
  toolId: string,
  payload: Record<string, unknown> = {},
): Promise<Execution> {
  return apiFetch<Execution>(`/api/tools/${toolId}/execute`, {
    method: "POST",
    body: JSON.stringify({ tool_id: toolId, action_payload: payload }),
  });
}

export async function approveExecution(
  executionId: string,
): Promise<Execution> {
  return apiFetch<Execution>(
    `/api/executions/${executionId}/approve`,
    { method: "POST" },
  );
}
