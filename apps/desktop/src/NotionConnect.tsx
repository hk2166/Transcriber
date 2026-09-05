import { useState } from "react";

import { testNotion, type NotionTest, type Settings } from "./api";
import { openExternal } from "./openExternal";

const CONNECTIONS_URL = "https://app.notion.com/developers/connections";

/**
 * Notion connection: paste an internal-integration token and a parent page or
 * database link, then Test. Nothing is sent to Notion until a page is approved
 * on the Sync tab; Test only identifies the connection and resolves the parent.
 */
export function NotionConnect({
  settings,
  patch,
}: {
  settings: Settings;
  patch: (p: Partial<Settings>) => void;
  configured: boolean;
}) {
  const [test, setTest] = useState<
    { kind: "idle" } | { kind: "testing" } | { kind: "ok"; result: NotionTest } | { kind: "fail"; message: string }
  >({ kind: "idle" });

  const runTest = async () => {
    setTest({ kind: "testing" });
    try {
      const result = await testNotion(settings);
      setTest(
        result.ok
          ? { kind: "ok", result }
          : { kind: "fail", message: result.error ?? "Couldn't reach Notion." },
      );
    } catch {
      setTest({ kind: "fail", message: "Couldn't reach the backend." });
    }
  };

  return (
    <div className="settings__field">
      <span>Notion</span>
      <small>
        Notion is a cloud service. Confab sends nothing to it on its own — only
        the pages you approve on the Sync tab, plus a token check when you press
        Test. The page you share with the connection is the only place Confab
        can write.
      </small>

      <input
        type="password"
        autoComplete="off"
        placeholder="Internal integration token"
        value={settings.api_keys.notion ?? ""}
        onChange={(e) => {
          patch({ api_keys: { ...settings.api_keys, notion: e.target.value } });
          setTest({ kind: "idle" });
        }}
      />
      <input
        type="text"
        placeholder="Parent page or database link"
        value={settings.notion_parent}
        onChange={(e) => {
          patch({ notion_parent: e.target.value });
          setTest({ kind: "idle" });
        }}
      />

      <div className="settings__testrow">
        <button
          className="settings__secondary"
          onClick={runTest}
          disabled={test.kind === "testing"}
        >
          {test.kind === "testing" ? "Testing…" : "Test connection"}
        </button>
        {test.kind === "ok" && (
          <small className="settings__test-ok">
            Will file under {test.result.parent?.title} ({test.result.parent?.kind})
            {test.result.bot_name ? ` as ${test.result.bot_name}` : ""}
          </small>
        )}
        {test.kind === "fail" && (
          <small className="settings__error">{test.message}</small>
        )}
      </div>

      <button className="google__link" onClick={() => openExternal(CONNECTIONS_URL)}>
        Create a connection ↗
      </button>
      <small>
        Open the page in Notion → ••• → Connections → + Add connection → pick
        your connection.
      </small>
    </div>
  );
}
