"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { type Execution } from "@/app/lib/api";
import ApprovalModal from "./approval-modal";
import { approveExecution } from "@/app/lib/api";

const WS_BASE =
  process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8001";

interface WSMessage {
  type: "initial" | "update" | "error";
  logs?: Execution[];
  message?: string;
}

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  success: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  awaiting_human: "bg-orange-100 text-orange-800",
};

export default function LiveViewer() {
  const [logs, setLogs] = useState<Execution[]>([]);
  const [connected, setConnected] = useState(false);
  const [approvalLog, setApprovalLog] = useState<Execution | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(`${WS_BASE}/ws/executions`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data);
          if (msg.type === "initial" && msg.logs) {
            setLogs(msg.logs);
          } else if (msg.type === "update" && msg.logs) {
            setLogs((prev) => {
              const merged = [...msg.logs!, ...prev];
              // Dedupe by id
              const seen = new Set<string>();
              return merged.filter((l) => {
                if (seen.has(l.id)) return false;
                seen.add(l.id);
                return true;
              });
            });
          }
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onclose = () => {
        setConnected(false);
        // Reconnect after 3s
        reconnectTimer.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      // WebSocket not available or invalid URL
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // Auto-scroll to top when new logs arrive
  useEffect(() => {
    if (containerRef.current && logs.length > 0) {
      containerRef.current.scrollTop = 0;
    }
  }, [logs.length]);

  const handleApprove = async (executionId: string) => {
    try {
      await approveExecution(executionId);
      setApprovalLog(null);
      // Log will update via WebSocket
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      alert(`Approval failed: ${msg}`);
    }
  };

  // Check for awaiting_human logs and show approval modal
  useEffect(() => {
    const awaiting = logs.find(
      (l) => l.execution_status === "awaiting_human"
    );
    if (awaiting && !approvalLog) {
      setApprovalLog(awaiting);
    }
  }, [logs, approvalLog]);

  return (
    <>
      <div className="rounded-lg border bg-white shadow-sm">
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <h3 className="font-semibold">Live Execution Feed</h3>
          <span
            className={`inline-flex items-center gap-1.5 text-xs ${
              connected ? "text-green-600" : "text-gray-400"
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                connected ? "bg-green-500" : "bg-gray-300"
              }`}
            />
            {connected ? "Connected" : "Disconnected"}
          </span>
        </div>

        <div
          ref={containerRef}
          className="max-h-96 overflow-y-auto divide-y"
        >
          {logs.length === 0 ? (
            <div className="px-6 py-8 text-center text-gray-400 text-sm">
              {connected
                ? "Waiting for execution events..."
                : "Connecting to WebSocket..."}
            </div>
          ) : (
            logs.map((log) => (
              <div key={log.id} className="px-6 py-3 hover:bg-gray-50">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-block rounded-full text-xs px-2 py-0.5 font-medium ${
                        STATUS_COLORS[log.execution_status] ??
                        "bg-gray-100 text-gray-800"
                      }`}
                    >
                      {log.execution_status}
                    </span>
                    {log.execution_status === "awaiting_human" && (
                      <button
                        onClick={() => setApprovalLog(log)}
                        className="text-xs text-orange-600 hover:underline font-medium"
                      >
                        Review
                      </button>
                    )}
                  </div>
                  <span className="text-xs text-gray-400">
                    {log.created_at
                      ? new Date(log.created_at).toLocaleTimeString()
                      : ""}
                  </span>
                </div>
                {log.tool_id && (
                  <p className="text-xs text-gray-500 mt-1">
                    Tool: <span className="font-mono">{log.tool_id.slice(0, 8)}...</span>
                  </p>
                )}
                {log.error_message && (
                  <p className="text-xs text-red-600 mt-1 truncate">
                    {log.error_message}
                  </p>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {approvalLog && (
        <ApprovalModal
          executionId={approvalLog.id}
          actionPayload={approvalLog.action_payload}
          onApprove={() => handleApprove(approvalLog.id)}
          onReject={() => setApprovalLog(null)}
        />
      )}
    </>
  );
}
