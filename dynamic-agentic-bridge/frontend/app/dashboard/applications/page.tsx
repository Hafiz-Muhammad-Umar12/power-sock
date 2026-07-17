"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  listApplications,
  observeApplication,
  type Application,
} from "@/app/lib/api";
import RegisterModal from "@/app/components/register-modal";

export default function ApplicationsPage() {
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showRegister, setShowRegister] = useState(false);
  const [observing, setObserving] = useState<string | null>(null);

  const fetchApps = useCallback(() => {
    setLoading(true);
    listApplications()
      .then(setApps)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchApps();
  }, [fetchApps]);

  const handleRegistered = () => {
    setShowRegister(false);
    fetchApps();
  };

  const handleObserve = async (appId: string) => {
    setObserving(appId);
    try {
      await observeApplication(appId);
      alert("Observation pipeline triggered! Check the live feed for progress.");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      alert(`Failed to trigger observation: ${msg}`);
    } finally {
      setObserving(null);
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Legacy Applications</h1>
          <p className="text-sm text-gray-500 mt-1">
            Register apps and trigger observation pipelines
          </p>
        </div>
        <button
          onClick={() => setShowRegister(true)}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition"
        >
          + Register Application
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 p-4 mb-6 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="rounded-lg border bg-white p-12 text-center text-gray-400 shadow-sm">
          Loading applications...
        </div>
      ) : apps.length === 0 ? (
        <div className="rounded-lg border bg-white p-12 text-center text-gray-400 shadow-sm">
          No applications registered yet. Click &quot;Register Application&quot; to
          get started.
        </div>
      ) : (
        <div className="rounded-lg border bg-white shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-6 py-3 font-medium text-gray-600">
                  Name
                </th>
                <th className="text-left px-6 py-3 font-medium text-gray-600">
                  Base URL
                </th>
                <th className="text-left px-6 py-3 font-medium text-gray-600">
                  Created
                </th>
                <th className="text-right px-6 py-3 font-medium text-gray-600">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {apps.map((app) => (
                <tr key={app.id} className="hover:bg-gray-50 transition">
                  <td className="px-6 py-4">
                    <Link
                      href={`/dashboard/applications/${app.id}`}
                      className="font-medium text-blue-600 hover:underline"
                    >
                      {app.name}
                    </Link>
                  </td>
                  <td className="px-6 py-4 text-gray-500 font-mono text-xs">
                    {app.base_url}
                  </td>
                  <td className="px-6 py-4 text-gray-500">
                    {new Date(app.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-6 py-4 text-right space-x-2">
                    <button
                      onClick={() => handleObserve(app.id)}
                      disabled={observing === app.id}
                      className="rounded-md bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 transition disabled:opacity-50"
                    >
                      {observing === app.id ? "Observing..." : "Observe"}
                    </button>
                    <Link
                      href={`/dashboard/applications/${app.id}`}
                      className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-gray-50 transition inline-block"
                    >
                      View Tools
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showRegister && (
        <RegisterModal
          onRegistered={handleRegistered}
          onClose={() => setShowRegister(false)}
        />
      )}
    </div>
  );
}
