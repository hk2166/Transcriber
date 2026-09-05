/** Open a URL in the user's real browser — the Tauri opener in the packaged
 *  app, window.open in the dev browser. Shared by GoogleConnect, the Notion
 *  setup link, and the Sync tab's "Open in Notion". */

export const isTauri =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export async function openExternal(url: string): Promise<void> {
  if (isTauri) {
    try {
      const { openUrl } = await import("@tauri-apps/plugin-opener");
      await openUrl(url);
      return;
    } catch {
      // fall through to window.open
    }
  }
  window.open(url, "_blank", "noopener");
}
