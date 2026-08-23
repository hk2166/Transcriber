/** Product name — single source of truth. Change here only. */
export const APP_NAME = "Confab";

declare global {
  interface Window {
    /** Injected by the Tauri host from the sidecar's `CONFAB_PORT=` line. */
    __CONFAB_PORT__?: number;
  }
}

// Packaged app: the Tauri host binds the backend to a free port and injects it
// before the webview loads. Dev / browser: fall back to the fixed dev port.
const BACKEND_PORT =
  (typeof window !== "undefined" && window.__CONFAB_PORT__) || 8765;

export const API_BASE = `http://127.0.0.1:${BACKEND_PORT}`;
export const WS_BASE = `ws://127.0.0.1:${BACKEND_PORT}`;
