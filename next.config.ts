import type { NextConfig } from 'next';

// The desktop preview loads a static export through Electron's app:// protocol.
const isDesktopExport = process.env.DESKTOP_EXPORT === '1';

const nextConfig: NextConfig = {
  ...(isDesktopExport ? { output: 'export' as const, images: { unoptimized: true } } : {}),
  // The app lives inside a larger folder that has its own lockfile; pinning the
  // root stops Next from walking up and mis-resolving the project.
  turbopack: { root: __dirname },
  devIndicators: false,
  experimental: {
    optimizePackageImports: ['@phosphor-icons/react'],
  },
};

export default nextConfig;
