import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  pauseSession,
  resumeSession,
  startSession,
  stopSession,
  type AudioSource,
  type StartResponse,
  type TranscriptSegment,
} from "./api";
import { WS_BASE } from "./config";

export type RecorderStatus =
  | "idle"
  | "starting"
  | "recording"
  | "paused"
  | "stopping";

interface RecorderState {
  status: RecorderStatus;
  session: StartResponse | null;
  level: number; // 0..1 smoothed meter level
  speechActive: boolean; // VAD: someone is speaking right now
  transcripts: TranscriptSegment[];
  elapsedMs: number;
  error: string | null;
}

const RMS_GAIN = 6; // maps speech RMS (~0.05–0.15) to a lively bar
const DECAY = 0.85; // meter release per audio block (attack is instant)

const INITIAL: RecorderState = {
  status: "idle",
  session: null,
  level: 0,
  speechActive: false,
  transcripts: [],
  elapsedMs: 0,
  error: null,
};

export function useRecorder() {
  const [state, setState] = useState<RecorderState>(INITIAL);

  const audioWsRef = useRef<WebSocket | null>(null);
  const transcriptWsRef = useRef<WebSocket | null>(null);
  const levelRef = useRef(0);
  const startedAtRef = useRef(0); // start of the current recording stretch
  const accumulatedMsRef = useRef(0); // recorded time before the current stretch

  const closeSocket = useCallback((ref: { current: WebSocket | null }) => {
    const ws = ref.current;
    ref.current = null;
    if (ws) {
      ws.onmessage = null;
      ws.onclose = null;
      ws.onerror = null;
      ws.close();
    }
  }, []);

  const closeSockets = useCallback(() => {
    closeSocket(audioWsRef);
    closeSocket(transcriptWsRef);
  }, [closeSocket]);

  const start = useCallback(
    async (source: AudioSource) => {
      setState((s) => ({ ...s, status: "starting", error: null }));

      let session: StartResponse;
      try {
        session = await startSession(source);
      } catch (err) {
        const message =
          err instanceof ApiError ? err.message : "Could not reach the backend.";
        setState((s) => ({ ...s, status: "idle", error: message }));
        return;
      }

      levelRef.current = 0;
      startedAtRef.current = Date.now();
      accumulatedMsRef.current = 0;

      // Audio stream — drives the volume meter and the speech dot.
      const audioWs = new WebSocket(`${WS_BASE}/audio/stream/${session.session_id}`);
      audioWsRef.current = audioWs;
      audioWs.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "end") {
          closeSocket(audioWsRef);
          return;
        }
        if (msg.type !== "audio") return;

        const bytes = Uint8Array.from(atob(msg.data), (c) => c.charCodeAt(0));
        const samples = new Float32Array(bytes.buffer);
        let sumSquares = 0;
        for (let i = 0; i < samples.length; i++) {
          sumSquares += samples[i] * samples[i];
        }
        const rms = Math.sqrt(sumSquares / samples.length);
        const target = Math.min(1, rms * RMS_GAIN);
        levelRef.current =
          target > levelRef.current ? target : levelRef.current * DECAY;
        setState((s) => ({
          ...s,
          level: levelRef.current,
          speechActive: msg.speech === true,
        }));
      };
      audioWs.onerror = () => {
        setState((s) => ({ ...s, error: "Audio stream error." }));
      };

      // Transcript stream — text as speech is recognised. Reconnects if the
      // socket drops mid-recording (the backend keeps recording regardless, so
      // no data is lost — this just resumes the live view).
      const connectTranscript = (sessionId: string, attempt: number) => {
        const ws = new WebSocket(`${WS_BASE}/transcription/stream/${sessionId}`);
        transcriptWsRef.current = ws;
        ws.onmessage = (event) => {
          const msg = JSON.parse(event.data);
          if (msg.type === "end") {
            closeSocket(transcriptWsRef);
            return;
          }
          if (msg.type !== "transcript") return;
          const segment: TranscriptSegment = {
            text: msg.text,
            start_ms: msg.start_ms,
            end_ms: msg.end_ms,
            language: msg.language,
            confidence: msg.confidence,
          };
          setState((s) => ({ ...s, transcripts: [...s.transcripts, segment] }));
        };
        ws.onclose = () => {
          // Not intentionally closed (ref still points here) and attempts left.
          if (transcriptWsRef.current === ws && attempt < 3) {
            setTimeout(
              () => connectTranscript(sessionId, attempt + 1),
              600 * (attempt + 1),
            );
          }
        };
      };
      connectTranscript(session.session_id, 0);

      setState((s) => ({
        ...s,
        status: "recording",
        session,
        level: 0,
        speechActive: false,
        transcripts: [],
        elapsedMs: 0,
      }));
    },
    [closeSocket],
  );

  const pause = useCallback(async () => {
    try {
      await pauseSession();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't pause.";
      setState((s) => ({ ...s, error: message }));
      return;
    }
    accumulatedMsRef.current += Date.now() - startedAtRef.current;
    setState((s) => ({
      ...s,
      status: "paused",
      level: 0,
      speechActive: false,
      elapsedMs: accumulatedMsRef.current,
    }));
  }, []);

  const resume = useCallback(async () => {
    try {
      await resumeSession();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't resume.";
      setState((s) => ({ ...s, error: message }));
      return;
    }
    startedAtRef.current = Date.now();
    setState((s) => ({ ...s, status: "recording" }));
  }, []);

  const stop = useCallback(async () => {
    setState((s) => ({ ...s, status: "stopping" }));
    try {
      await stopSession();
    } catch {
      // Stopping an already-gone session must not strand the UI.
    }
    closeSockets();
    setState((s) => ({ ...s, status: "idle", level: 0, speechActive: false }));
  }, [closeSockets]);

  // Elapsed timer — runs only while recording (paused time doesn't count).
  useEffect(() => {
    if (state.status !== "recording") return;
    const id = setInterval(() => {
      setState((s) => ({
        ...s,
        elapsedMs: accumulatedMsRef.current + (Date.now() - startedAtRef.current),
      }));
    }, 500);
    return () => clearInterval(id);
  }, [state.status]);

  // Kill any live sockets if the component unmounts.
  useEffect(() => closeSockets, [closeSockets]);

  return { ...state, start, stop, pause, resume };
}
