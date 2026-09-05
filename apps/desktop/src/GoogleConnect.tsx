import { useEffect, useState } from "react";

import {
  connectGoogle,
  disconnectGoogle,
  getGoogleSetup,
  getGoogleStatus,
  saveGoogleCredentials,
  type GoogleSetup,
  type GoogleStatus,
} from "./api";
import { toast } from "./toast";

import { openExternal } from "./openExternal";

/**
 * Bring-your-own-credentials Google connection. The user runs a one-time
 * gcloud setup, creates a Desktop OAuth client in the console (deep-linked),
 * pastes the two values, and connects — Confab never touches their Google
 * session, only the credentials they explicitly copy.
 */
export function GoogleConnect() {
  const [status, setStatus] = useState<GoogleStatus | null>(null);
  const [setup, setSetup] = useState<GoogleSetup | null>(null);
  const [showSetup, setShowSetup] = useState(false);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [connecting, setConnecting] = useState(false);

  const refresh = () =>
    getGoogleStatus().then(setStatus).catch(() => setStatus(null));

  useEffect(() => {
    refresh();
    getGoogleSetup().then(setSetup).catch(() => setSetup(null));
  }, []);

  const saveCreds = async () => {
    if (!clientId.trim() || !clientSecret.trim()) return;
    try {
      await saveGoogleCredentials(clientId.trim(), clientSecret.trim());
      setClientId("");
      setClientSecret("");
      await refresh();
      toast("Google credentials saved.");
    } catch {
      toast("Couldn't save those credentials.");
    }
  };

  const connect = async () => {
    setConnecting(true);
    try {
      const { auth_url } = await connectGoogle();
      await openExternal(auth_url);
      toast("Approve access in your browser, then come back.");
      // Poll for the loopback callback to complete the connection.
      const started = Date.now();
      const poll = window.setInterval(async () => {
        const next = await getGoogleStatus().catch(() => null);
        if (next?.connected || Date.now() - started > 180_000) {
          window.clearInterval(poll);
          setConnecting(false);
          if (next) setStatus(next);
          if (next?.connected) toast(`Connected as ${next.email ?? "Google"}.`);
        }
      }, 2000);
    } catch (err) {
      setConnecting(false);
      toast(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Couldn't start the Google connection.",
      );
    }
  };

  const disconnect = async () => {
    await disconnectGoogle().catch(() => {});
    await refresh();
  };

  if (status?.connected) {
    return (
      <div className="settings__field">
        <span>Google</span>
        <div className="google__connected">
          <span className="google__badge">
            Connected{status.email ? ` · ${status.email}` : ""}
          </span>
          <button className="settings__secondary" onClick={disconnect}>
            Disconnect
          </button>
        </div>
        <small>Calendar events and Docs can be sent from the Sync tab.</small>
      </div>
    );
  }

  return (
    <div className="settings__field">
      <span>Google Calendar &amp; Docs</span>
      <small>
        Uses your own Google Cloud credentials — your data stays under your
        Google project; Confab is never a middleman.
      </small>

      {!status?.has_client && (
        <button
          className="settings__secondary"
          onClick={() => setShowSetup((v) => !v)}
        >
          {showSetup ? "Hide setup steps" : "How to get credentials"}
        </button>
      )}

      {showSetup && setup && (
        <div className="google__setup">
          <p className="google__step">
            <strong>1.</strong> Create a project + enable the APIs. Paste this
            in Terminal{setup.gcloud_available ? "" : " (needs the gcloud CLI)"}:
          </p>
          <pre className="google__script">{setup.script}</pre>
          <p className="google__step">
            <strong>2.</strong> Open these pages and create a{" "}
            <strong>Desktop app</strong> OAuth client:
          </p>
          {setup.links.map((link) => (
            <button
              key={link.url}
              className="google__link"
              onClick={() => openExternal(link.url)}
            >
              {link.label} ↗
            </button>
          ))}
          <p className="google__step">
            <strong>3.</strong> Paste the two values it gives you below.
          </p>
        </div>
      )}

      <input
        type="text"
        placeholder="Client ID (…apps.googleusercontent.com)"
        value={clientId}
        onChange={(e) => setClientId(e.target.value)}
      />
      <input
        type="password"
        placeholder="Client secret"
        value={clientSecret}
        onChange={(e) => setClientSecret(e.target.value)}
      />
      <div className="google__actions">
        <button className="settings__secondary" onClick={saveCreds}>
          Save credentials
        </button>
        {status?.has_client && (
          <button
            className="google__connect"
            onClick={connect}
            disabled={connecting}
          >
            {connecting ? "Waiting for approval…" : "Connect Google"}
          </button>
        )}
      </div>
    </div>
  );
}
