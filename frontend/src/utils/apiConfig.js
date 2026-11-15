/**
 * Centralised API base-URL configuration.
 *
 * All values are driven by Vite VITE_* env vars so the same build artefact
 * can be pointed at different environments without rebuilding.
 *
 * In development (Vite dev-server) leave the vars empty — Vite's proxy
 * handles routing `/api/*` to the correct microservice on your behalf.
 *
 * In production (nginx container) the vars should also remain empty because
 * nginx itself proxies the relative `/api/*` paths. Set them only when you
 * need to override to an explicit external domain (e.g. staging vs prod).
 *
 * Env vars (in frontend/.env):
 *   VITE_BACKEND_URL   → main backend  (default port 8000)
 *   VITE_RAG_URL       → rag-service   (default port 8001)
 *   VITE_TOOLS_URL     → tools-service (default port 8002)
 */

/** Main backend service – handles /api/auth, /api/* general routes */
export const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? '';

/** RAG / data-sources service – handles /api/data-sources/* */
export const RAG_URL = import.meta.env.VITE_RAG_URL ?? '';

/** Tools registry service – handles /api/tools/* */
export const TOOLS_URL = import.meta.env.VITE_TOOLS_URL ?? '';
