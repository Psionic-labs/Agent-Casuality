import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent-Casuality DAG Explorer",
  description: "Read-only visual explorer for agent causal traces: failure diagnosis, causal DAG, timeline, and evidence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
