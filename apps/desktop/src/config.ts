/** Product name — single source of truth. Renamed on Day 16; change here only. */
export const APP_NAME = "MeetingMind";

declare global {
  interface Window {
    /** Injected by the Tauri host from the sidecar's `MEETINGMIND_PORT=` line. */
    __MEETINGMIND_PORT__?: number;
  }
}

// Packaged app: the Tauri host binds the backend to a free port and injects it
// before the webview loads. Dev / browser: fall back to the fixed dev port.
const BACKEND_PORT =
  (typeof window !== "undefined" && window.__MEETINGMIND_PORT__) || 8765;

export const API_BASE = `http://127.0.0.1:${BACKEND_PORT}`;
export const WS_BASE = `ws://127.0.0.1:${BACKEND_PORT}`;
