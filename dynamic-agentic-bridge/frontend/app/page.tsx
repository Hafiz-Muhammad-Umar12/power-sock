import Link from "next/link";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center">
      <h1 className="text-4xl font-bold mb-4">Dynamic Agentic Bridge</h1>
      <p className="text-lg text-gray-600 mb-8">
        Observe legacy web UIs and expose them as dynamic MCP tools.
      </p>
      <Link
        href="/dashboard"
        className="rounded-lg bg-blue-600 px-6 py-3 text-white font-medium hover:bg-blue-700 transition"
      >
        Open Dashboard
      </Link>
    </main>
  );
}
