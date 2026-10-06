import type { NextConfig } from "next"

// STATIC_EXPORT=1 builds plain files (out/) for S3 + CloudFront; the default build runs as a Node server for local use.
const nextConfig: NextConfig = {
  devIndicators: false,
  ...(process.env.STATIC_EXPORT === "1" ? { output: "export", trailingSlash: true, images: { unoptimized: true } } : {}),
}

export default nextConfig
