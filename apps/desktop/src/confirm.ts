/** In-app confirm dialog, replacing window.confirm.
 *
 * Tauri's WKWebView doesn't implement window.confirm — it returns false
 * without showing anything, so every confirm-gated action silently no-ops in
 * the packaged app (the dev browser shows a real dialog, hiding the bug).
 * Plain DOM like toast.ts, so any module can await it without React plumbing.
 */

export interface ConfirmOptions {
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Style the confirm button as destructive and focus Cancel instead. */
  danger?: boolean;
}

export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    const previouslyFocused = document.activeElement as HTMLElement | null;

    const backdrop = document.createElement("div");
    backdrop.className = "confirm-backdrop";

    const dialog = document.createElement("div");
    dialog.className = "confirm";
    dialog.setAttribute("role", "alertdialog");
    dialog.setAttribute("aria-modal", "true");

    const message = document.createElement("p");
    message.className = "confirm__message";
    message.textContent = options.message;

    const actions = document.createElement("div");
    actions.className = "confirm__actions";

    const cancel = document.createElement("button");
    cancel.className = "confirm__btn";
    cancel.textContent = options.cancelLabel ?? "Cancel";

    const ok = document.createElement("button");
    ok.className =
      "confirm__btn " +
      (options.danger ? "confirm__btn--danger" : "confirm__btn--primary");
    ok.textContent = options.confirmLabel ?? "OK";

    const close = (answer: boolean) => {
      document.removeEventListener("keydown", onKey, true);
      backdrop.remove();
      previouslyFocused?.focus?.();
      resolve(answer);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation(); // don't also dismiss a sheet underneath
        close(false);
      }
    };

    cancel.onclick = () => close(false);
    ok.onclick = () => close(true);
    backdrop.onclick = (event) => {
      if (event.target === backdrop) close(false);
    };
    document.addEventListener("keydown", onKey, true);

    actions.append(cancel, ok);
    dialog.append(message, actions);
    backdrop.append(dialog);
    document.body.append(backdrop);

    // Destructive: focus Cancel so Enter can't destroy; otherwise focus OK.
    (options.danger ? cancel : ok).focus();
  });
}
