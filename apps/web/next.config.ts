import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@chair/shared-types"],
  outputFileTracingRoot: path.join(__dirname, "../../"),
};

export default nextConfig;
