import type { NextConfig } from 'next'

// Pinned so Next does not adopt a parent directory's lockfile as the workspace root.
const config: NextConfig = { turbopack: { root: __dirname } }

export default config
