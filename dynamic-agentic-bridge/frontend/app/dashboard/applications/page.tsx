export default function ApplicationsPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Legacy Applications</h1>
        <button
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition"
          disabled
        >
          + Register Application
        </button>
      </div>
      <div className="rounded-lg border bg-white p-8 text-center text-gray-500 shadow-sm">
        No applications registered yet. Full UI coming in Phase 5.
      </div>
    </div>
  );
}
