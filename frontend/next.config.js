/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output is only needed for the Docker image; local `next start`
  // works with the regular build output.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  reactStrictMode: true,
};

module.exports = nextConfig;
