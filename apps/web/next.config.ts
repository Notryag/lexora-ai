import type { NextConfig } from "next";

const apiBaseUrl = process.env.LEXORA_API_URL ?? "http://127.0.0.1:8010";

const nextConfig: NextConfig = {
  agentRules: false,
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiBaseUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
