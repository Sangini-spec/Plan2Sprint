import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  /* ── Production ── */
  output: "standalone",

  /* Pin workspace root to this project — prevents Next.js from
     picking up stray package.json files in parent directories */
  outputFileTracingRoot: path.join(__dirname, "../../"),

  /* ── Dev-mode speed optimizations ── */
  reactStrictMode: false, // prevents double-render in dev

  /* Skip type-checking & linting during dev builds (run separately) */
  typescript: { ignoreBuildErrors: process.env.NODE_ENV === "development" },
  eslint: { ignoreDuringBuilds: process.env.NODE_ENV === "development" },

  /* Tree-shake heavy barrel-file packages on import */
  experimental: {
    optimizePackageImports: [
      "lucide-react",
      "framer-motion",
      "recharts",
      "date-fns",
      "@tanstack/react-table",
    ],
  },

  /* ── Proxy /api/* to FastAPI backend ── */
  async rewrites() {
    const apiUrl = process.env.API_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },

  /* Webpack tweaks for faster dev compilation */
  webpack: (config, { dev }) => {
    if (dev) {
      // Reduce filesystem polling overhead (OneDrive path)
      config.watchOptions = {
        ...config.watchOptions,
        poll: 1000,
        aggregateTimeout: 300,
        ignored: ["**/node_modules/**", "**/.git/**", "**/.next/**"],
      };
    }
    return config;
  },
};

export default nextConfig;
