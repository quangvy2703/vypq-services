import type { NextConfig } from "next";

const config: NextConfig = {
  // standalone để Dockerfile ở Task 13 copy đúng một cây runtime nhỏ,
  // không phải bê cả node_modules dev vào image.
  output: "standalone",
  reactStrictMode: true,
};

export default config;
