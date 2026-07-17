"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  listApplications,
  type Application,
} from "@/app/lib/api";
import LiveViewer from "@/app/components/live-viewer";

export default function DashboardPage() {
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listApplications()
      .then(setApps)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-gray-500 text-sm mt-1">
            Dynamic Agentic Bridge — observe legacy UIs, map to MCP tools
          </p>
        </div>
        <Link
          href="/dashboard/applications"
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition"
        >
          Manage Applications
        </Link>
      </div>

      {/* Stats row */}
      <div className="grid gap-4 md:grid-cols-3 mb-8">
        <div className="rounded-lg border bg-white p-4 shadow-sm">
          <p className="text-sm text-gray-500">Registered Apps</p>
          <p className="text-2xl font-bold mt-1">
            {loading ? "—" : apps.length}
          </p>
        </div>
        <div className="rounded-lg border bg-white p-4 shadow-sm">
          <p className="text-sm text-gray-500">Pipeline Status</p>
          <p className="text-2xl font-bold mt-1 text-green-600">Ready</p>
        </div>
        <div className="rounded-lg border bg-white p-4 shadow-sm">
          <p className="text-sm text-gray-500">Active Tools</p>
          <p className="text-2xl font-bold mt-1">—</p>
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 p-4 mb-6 text-sm text-red-700">
          Failed to load applications: {error}
        </div>
      )}

      {/* Recent applications */}
      <div className="rounded-lg border bg-white shadow-sm">
        <div className="px-6 py-4 border-b">
          <h2 className="font-semibold">Recent Applications</h2>
        </div>
        {loading ? (
          <div className="px-6 py-8 text-center text-gray-400">Loading...</div>
        ) : apps.length === 0 ? (
          <div className="px-6 py-8 text-center text-gray-400">
            No applications registered yet.{" "}
            <Link
              href="/dashboard/applications"
              className="text-blue-600 hover:underline"
            >
              Register one
            </Link>
            .
          </div>
        ) : (
          <div className="divide-y">
            {apps.slice(0, 5).map((app) => (
              <Link
                key={app.id}
                href={`/dashboard/applications/${app.id}`}
                className="flex items-center justify-between px-6 py-3 hover:bg-gray-50 transition"
              >
                <div>
                  <p className="font-medium">{app.name}</p>
                  <p className="text-sm text-gray-500">{app.base_url}</p>
                </div>
                <span className="text-sm text-gray-400">
                  {new Date(app.created_at).toLocaleDateString()}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* Live viewer */}
      <div className="mt-8">
        <LiveViewer />
      </div>
    </div>
  );
}
