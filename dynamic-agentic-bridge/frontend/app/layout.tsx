import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dynamic Agentic Bridge",
  description:
    "Observe legacy web UIs and expose them as dynamic MCP tools for AI agents.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 antialiased">
        <nav className="border-b bg-white">
          <div className="mx-auto max-w-7xl px-4 flex items-center h-12">
            <Link
              href="/"
              className="font-bold text-sm mr-8"
            >
              Dynamic Agentic Bridge
            </Link>
            <div className="flex gap-6 text-sm">
              <Link
                href="/dashboard"
                className="text-gray-600 hover:text-gray-900 transition"
              >
                Dashboard
              </Link>
              <Link
                href="/dashboard/applications"
                className="text-gray-600 hover:text-gray-900 transition"
              >
                Applications
              </Link>
            </div>
          </div>
        </nav>
        {children}
      </body>
    </html>
  );
}
