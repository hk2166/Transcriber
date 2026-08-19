import { useEffect, useRef, useState } from "react";

import { streamChat, type ChatSource } from "./api";

interface Message {
  role: "user" | "assistant";
  text: string;
  sources?: ChatSource[];
}

export function MeetingChat({ meetingId }: { meetingId: number }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);

  // Fresh conversation when switching meetings.
  useEffect(() => {
    setMessages([]);
    setInput("");
  }, [meetingId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const updateLast = (patch: (m: Message) => Message) =>
    setMessages((msgs) =>
      msgs.map((m, i) => (i === msgs.length - 1 ? patch(m) : m)),
    );

  const send = async () => {
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);
    setMessages((msgs) => [
      ...msgs,
      { role: "user", text: question },
      { role: "assistant", text: "", sources: [] },
    ]);

    try {
      await streamChat(meetingId, question, {
        onSources: (sources) => updateLast((m) => ({ ...m, sources })),
        onToken: (token) => updateLast((m) => ({ ...m, text: m.text + token })),
        onError: (message) => updateLast((m) => ({ ...m, text: message })),
      });
    } catch {
      updateLast((m) => ({ ...m, text: "Couldn't reach the assistant." }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="chat">
      <div className="chat__log">
        {messages.length === 0 && (
          <p className="chat__hint">
            Ask anything about this meeting — answers come from the transcript.
          </p>
        )}
        {messages.map((message, index) => (
          <div className={`chat__msg chat__msg--${message.role}`} key={index}>
            <div className="chat__bubble">
              {message.text || (message.role === "assistant" && busy ? "…" : "")}
            </div>
            {message.role === "assistant" &&
              message.sources &&
              message.sources.length > 0 && (
                <details className="chat__sources">
                  <summary>{message.sources.length} sources</summary>
                  <ul>
                    {message.sources.map((source) => (
                      <li key={source.segment_id}>{source.text}</li>
                    ))}
                  </ul>
                </details>
              )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className="chat__composer">
        <input
          className="chat__input"
          placeholder="Ask about this meeting…"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && send()}
          disabled={busy}
        />
        <button className="chat__send" onClick={send} disabled={busy || !input.trim()}>
          Ask
        </button>
      </div>
    </div>
  );
}
