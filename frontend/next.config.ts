import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: [
    "192.168.189.192",
    "192.168.189.192:3000",
    "192.168.189.189",
    "192.168.189.189:3000",
    "localhost:3000",
    "127.0.0.1",
    "127.0.0.1:3000",
  ],
 devIndicators: false ,
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: "http://127.0.0.1:8000/api/v1/:path*",
      },
    ];
  },
};

export default nextConfig;
