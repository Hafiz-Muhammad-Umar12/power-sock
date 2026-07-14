"use client";

/**
 * ApprovalModal — shown when an execution requires human approval.
 * Stub for Phase 1; full implementation in Phase 5.
 */

interface ApprovalModalProps {
  executionId: string;
  actionPayload: Record<string, unknown>;
  onApprove: () => void;
  onReject: () => void;
}

export default function ApprovalModal({
  executionId,
  actionPayload,
  onApprove,
  onReject,
}: ApprovalModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="rounded-lg bg-white p-6 shadow-xl max-w-md w-full">
        <h3 className="text-lg font-semibold mb-2">Human Approval Required</h3>
        <p className="text-sm text-gray-600 mb-4">
          Execution <code className="bg-gray-100 px-1 rounded">{executionId}</code> is
          awaiting your approval.
        </p>
        <pre className="bg-gray-50 rounded p-3 text-xs overflow-auto mb-4">
          {JSON.stringify(actionPayload, null, 2)}
        </pre>
        <div className="flex gap-3 justify-end">
          <button
            onClick={onReject}
            className="rounded-lg border px-4 py-2 text-sm font-medium hover:bg-gray-50 transition"
          >
            Reject
          </button>
          <button
            onClick={onApprove}
            className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 transition"
          >
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}
