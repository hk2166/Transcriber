import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  startSession,
  stopSession,
  type AudioSource,
  type StartResponse,
} from "./api";
import { WS_BASE } from "./config";

export type RecorderStatus = "idle" | "starting" | "recording" | "stopping";

interface RecorderState {
  status: RecorderStatus;
  session: StartResponse | null;
  level: number; // 0..1 smoothed meter level
  elapsedMs: number;
  error: string | null;
}

const RMS_GAIN = 6; // maps speech RMS (~0.05–0.15) to a lively bar
const DECAY = 0.85; // meter release per audio block (attack is instant)

const INITIAL: RecorderState = {
  status: "idle",
  session: null,
  level: 0,
  elapsedMs: 0,
  error: null,
};

export function useRecorder() {
  const [state, setState] = useState<RecorderState>(INITIAL);

  const wsRef = useRef<WebSocket | null>(null);
  const levelRef = useRef(0);
  const startedAtRef = useRef(0);

  const closeSocket = useCallback(() => {
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws) {
      ws.onmessage = null;
      ws.onclose = null;
      ws.onerror = null;
      ws.close();
    }
  }, []);

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

      const ws = new WebSocket(`${WS_BASE}/audio/stream/${session.session_id}`);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "end") {
          closeSocket();
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
        setState((s) => ({ ...s, level: levelRef.current }));
      };

      ws.onerror = () => {
        setState((s) => ({ ...s, error: "Audio stream error." }));
      };

      setState((s) => ({
        ...s,
        status: "recording",
        session,
        level: 0,
        elapsedMs: 0,
      }));
    },
    [closeSocket],
  );

  const stop = useCallback(async () => {
    setState((s) => ({ ...s, status: "stopping" }));
    try {
      await stopSession();
    } catch {
      // Stopping an already-gone session must not strand the UI.
    }
    closeSocket();
    setState((s) => ({ ...s, status: "idle", level: 0 }));
  }, [closeSocket]);

  // Elapsed timer — runs only while recording.
  useEffect(() => {
    if (state.status !== "recording") return;
    const id = setInterval(() => {
      setState((s) => ({ ...s, elapsedMs: Date.now() - startedAtRef.current }));
    }, 500);
    return () => clearInterval(id);
  }, [state.status]);

  // Kill any live socket if the component unmounts.
  useEffect(() => closeSocket, [closeSocket]);

  return { ...state, start, stop };
}