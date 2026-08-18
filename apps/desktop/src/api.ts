import { API_BASE } from "./config";

export type AudioSource = "mic" | "system" | "both";

export interface StartResponse {
  session_id: string;
  source: AudioSource;
  system_available: boolean;
  wav_path: string;
}

export interface StopResponse {
  session_id: string;
  duration_seconds: number;
  frames_written: number;
  wav_path: string;
}

export interface TranscriptSegment {
  text: string;
  start_ms: number;
  end_ms: number;
  language: string;
  confidence: number;
  speaker_id?: number | null; // set on stored segments after diarization
}

export interface Speaker {
  id: number;
  meeting_id: number;
  label: string; // "Speaker 1" (auto)
  name: string | null; // user-assigned override
  color: string;
}

export interface MeetingSummary {
  summary: string;
  key_points: string[];
  action_items: string[];
  decisions: string[];
  open_questions: string[];
}

export interface Meeting {
  id: number;
  title: string;
  source: AudioSource;
  status: string;
  wav_path: string | null;
  started_at: string;
  ended_at: string | null;
  segment_count: number;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      // Non-JSON error body — fall back to the status text.
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export function startSession(source: AudioSource): Promise<StartResponse> {
  return postJson<StartResponse>("/audio/start", { source });
}

export function stopSession(): Promise<StopResponse> {
  return postJson<StopResponse>("/audio/stop");
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new ApiError(res.status, res.statusText);
  }
  return (await res.json()) as T;
}

export function getMeetings(): Promise<Meeting[]> {
  return getJson<Meeting[]>("/meetings");
}

export function getMeetingSegments(id: number): Promise<TranscriptSegment[]> {
  return getJson<TranscriptSegment[]>(`/meetings/${id}/segments`);
}

export function getMeetingSpeakers(id: number): Promise<Speaker[]> {
  return getJson<Speaker[]>(`/meetings/${id}/speakers`);
}

export async function getMeetingSummary(
  id: number,
): Promise<MeetingSummary | null> {
  try {
    return await getJson<MeetingSummary>(`/meetings/${id}/summary`);
  } catch {
    return null; // 404 = not generated yet (or Ollama was unavailable)
  }
}

export function renameSpeaker(
  speaker_id: number,
  name: string,
): Promise<{ renamed: boolean }> {
  return postJson<{ renamed: boolean }>("/speakers/rename", { speaker_id, name });
}