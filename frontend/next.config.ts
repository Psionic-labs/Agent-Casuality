import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export: `npm run build` emits plain HTML/CSS/JS into frontend/out/,
  // which the read-only Python backend (explorer/server.py) serves at `/`.
  // No Node server is needed in production; `python -m explorer.server`
  // remains the single run command.
  output: "export",
  // In `npm run dev` the page runs on the Next dev server, so API calls are
  // proxied to a locally running explorer backend (default port 8766).
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://127.0.0.1:8766/api/:path*" },
    ];
  },
};

export default nextConfig;
