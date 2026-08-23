/// <reference types="vite/client" />

/** Only VITE_-prefixed values reach the browser; provider keys never appear here. */
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
