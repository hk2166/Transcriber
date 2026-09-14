import { useEffect, useState } from "react";

import { getHostedStatus, signinHosted, signoutHosted, type HostedStatus } from "./api";
import { toast } from "./toast";

/**
 * Confab Hosted (opt-in free tier): sign in with an email to get a metered
 * monthly allowance — no API key needed. Transcripts run through Confab's
 * hosted service; Local (Ollama) stays the fully-private default.
 */
export function HostedConnect() {
  const [status, setStatus] = useState<HostedStatus | null>(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = () =>
    getHostedStatus().then(setStatus).catch(() => setStatus({ signed_in: false }));

  useEffect(() => {
    refresh();
  }, []);

  const signIn = async () => {
    if (!email.trim()) return;
    setBusy(true);
    try {
      setStatus(await signinHosted(email.trim()));
      toast("Signed in to Confab Hosted.");
    } catch {
      toast("Couldn't sign in to Confab Hosted.");
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    await signoutHosted().catch(() => {});
    setEmail("");
    refresh();
  };

  if (status?.signed_in) {
    return (
      <div className="settings__field">
        <span>Confab Hosted</span>
        <div className="google__connected">
          <span className="google__badge">{status.email ?? "Signed in"}</span>
          <button className="settings__secondary" onClick={signOut}>
            Sign out
          </button>
        </div>
        {status.remaining != null && status.token_limit != null ? (
          <small>
            {status.remaining.toLocaleString()} of {status.token_limit.toLocaleString()} free
            tokens left this month.
          </small>
        ) : (
          <small>Local (Ollama) keeps everything on this Mac.</small>
        )}
        {status.error && <small className="settings__error">{status.error}</small>}
      </div>
    );
  }

  return (
    <div className="settings__field">
      <span>Confab Hosted (free tier)</span>
      <small>
        Sign in with your email for a free monthly allowance — no API key needed.
        Transcripts run through Confab’s hosted service; switch to Local (Ollama)
        to keep everything on this Mac.
      </small>
      <input
        type="email"
        autoComplete="email"
        placeholder="you@example.com"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") signIn();
        }}
      />
      <button className="settings__secondary" onClick={signIn} disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </div>
  );
}
