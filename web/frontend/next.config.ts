import type { NextConfig } from "next";
// 业务仅由 Go 提供；开发和生产都保留同源请求。
const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // 验证与恢复邮件的查询参数带一次性令牌，不写开发请求日志。
  logging: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
  async rewrites() {
    const origin = process.env.API_ORIGIN ?? "http://127.0.0.1:8080";
    return [
      { source: "/api/:path*", destination: `${origin}/api/:path*` },
      { source: "/oauth/:path*", destination: `${origin}/oauth/:path*` },
    ];
  },
};
export default config;
