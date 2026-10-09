import type { NextConfig } from "next";

const config: NextConfig = {
  // Docker 이미지용: node_modules 없이 server.js 하나로 실행
  output: "standalone",
};

export default config;
