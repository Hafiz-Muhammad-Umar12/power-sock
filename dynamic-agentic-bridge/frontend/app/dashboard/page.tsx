import Link from "next/link";

export default function DashboardPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <h1 className="text-2xl font-bold mb-6">Dashboard</h1>
      <div className="grid gap-6 md:grid-cols-2">
        <Link
          href="/dashboard/applications"
          className="rounded-lg border bg-white p-6 shadow-sm hover:shadow-md transition"
        >
          <h2 className="text-lg font-semibold mb-2">Legacy Applications</h2>
          <p className="text-gray-600">
            Register and manage legacy web applications, trigger observation
            pipelines, and view mapped MCP tools.
          </p>
        </Link>
        <div className="rounded-lg border bg-white p-6 shadow-sm opacity-50">
          <h2 className="text-lg font-semibold mb-2">Live Execution Feed</h2>
          <p className="text-gray-600">
            Real-time agent execution logs. Coming in Phase 5.
          </p>
        </div>
      </div>
    </div>
  );
}
