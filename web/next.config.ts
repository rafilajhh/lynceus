import type { NextConfig } from "next";

/**
 * Lynceus web — static export.
 *
 * The frontend builds to `out/` with zero server runtime. FastAPI serves
 * that directory (see backend/lynceus/api.py StaticFiles mount), so the
 * whole app ships as plain files behind the API origin.
 *
 * Routes are top-level: / (landing), /app (workspace), /inspections (ledger).
 */
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: false,
};

export default nextConfig;
