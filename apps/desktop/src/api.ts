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
  id?: number; // present on stored segments (needed for editing)
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

export function pauseSession(): Promise<{ paused: boolean }> {
  return postJson<{ paused: boolean }>("/audio/pause");
}

export function resumeSession(): Promise<{ paused: boolean }> {
  return postJson<{ paused: boolean }>("/audio/resume");
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new ApiError(res.status, res.statusText);
  }
  return (await res.json()) as T;
}

export interface SearchResult {
  meeting_id: number;
  meeting_title: string;
  segment_id: number;
  text: string;
  start_ms: number;
  score: number;
}

export interface Settings {
  transcription_engine: string;
  whisper_model: string;
  ollama_model: string;
  vad_threshold: number;
  default_source: AudioSource;
  auto_summarize: boolean;
  auto_record: "off" | "prompt" | "auto";
  integrations_enabled: Record<string, boolean>;
  llm_provider: string;
  llm_model: string;
  llm_base_url: string;
  api_keys: Record<string, string>;
}

export interface SyncProposal {
  id: number;
  meeting_id: number;
  kind: "reminder" | "event" | "note" | "page";
  target: string;
  title: string;
  body: string;
  payload: { start_iso?: string; duration_min?: number; due_iso?: string };
  status: "proposed" | "applied" | "skipped" | "failed" | "stale";
  external_ref: string | null;
  error: string | null;
}

export interface IntegrationInfo {
  id: string;
  label: string;
  available: boolean;
  enabled: boolean;
}

export function getIntegrations(): Promise<IntegrationInfo[]> {
  return getJson<IntegrationInfo[]>("/integrations");
}

export function getMeetingProposals(meetingId: number): Promise<SyncProposal[]> {
  return getJson<SyncProposal[]>(`/meetings/${meetingId}/proposals`);
}

export function patchProposal(
  proposalId: number,
  patch: Partial<Pick<SyncProposal, "title" | "body" | "payload" | "status">>,
): Promise<SyncProposal> {
  return patchJson<SyncProposal>(`/proposals/${proposalId}`, patch);
}

export function applyProposal(proposalId: number): Promise<SyncProposal> {
  return postJson<SyncProposal>(`/proposals/${proposalId}/apply`);
}

export function applyAllProposals(meetingId: number): Promise<SyncProposal[]> {
  return postJson<SyncProposal[]>(`/meetings/${meetingId}/proposals/apply`);
}

export interface ASREngine {
  id: string;
  label: string;
  note: string;
  languages: string;
  size_mb: number;
  family: "whisper" | "parakeet";
}

export function getASREngines(): Promise<ASREngine[]> {
  return getJson<ASREngine[]>("/asr/engines");
}

export interface LLMProvider {
  id: string;
  label: string;
  default_model: string;
  needs_key: boolean;
  needs_base_url: boolean;
  key_url: string;
  local: boolean;
}

export function getLLMProviders(): Promise<LLMProvider[]> {
  return getJson<LLMProvider[]>("/llm/providers");
}

export function testLLM(
  candidate: Settings,
): Promise<{ ok: boolean; error?: string; reply?: string }> {
  return postJson<{ ok: boolean; error?: string; reply?: string }>(
    "/llm/test",
    candidate,
  );
}

export interface SystemStatus {
  ollama_available: boolean;
  ollama_models: string[];
  blackhole_available: boolean;
  whisper_model: string;
}

export function getSettings(): Promise<Settings> {
  return getJson<Settings>("/settings");
}

export async function putSettings(settings: Settings): Promise<Settings> {
  const res = await fetch(`${API_BASE}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return (await res.json()) as Settings;
}

export function getSystemStatus(): Promise<SystemStatus> {
  return getJson<SystemStatus>("/system/status");
}

export function resetAllData(): Promise<{ reset: boolean }> {
  return postJson<{ reset: boolean }>("/system/reset");
}

export function getMeetings(): Promise<Meeting[]> {
  return getJson<Meeting[]>("/meetings");
}

export function searchSegments(query: string): Promise<SearchResult[]> {
  return postJson<SearchResult[]>("/search", { query, k: 20 });
}

export interface ChatSource {
  segment_id: number;
  text: string;
  score: number;
}

// Dev/browser download. In the packaged Tauri app this is swapped for the
// native save dialog (plugin-dialog + plugin-fs) alongside the Day-16 sidecar.
export async function downloadExport(
  meetingId: number,
  format: string,
  title: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/meetings/${meetingId}/export/${format}`);
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  const blob = await res.blob();
  const ext = format === "markdown" ? "md" : format;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${title}.${ext}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

interface ChatHandlers {
  onSources?: (sources: ChatSource[]) => void;
  onToken?: (token: string) => void;
  onError?: (message: string) => void;
}

/** POST a question and consume the SSE stream (sources → tokens → done). */
export async function streamChat(
  meetingId: number,
  question: string,
  handlers: ChatHandlers,
): Promise<void> {
  const res = await fetch(`${API_BASE}/meetings/${meetingId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok || !res.body) {
    throw new ApiError(res.status, res.statusText);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);

      const lines = chunk.split("\n");
      const event = lines.find((l) => l.startsWith("event:"))?.slice(6).trim();
      const dataLine = lines.find((l) => l.startsWith("data:"))?.slice(5).trim();
      if (!event || !dataLine) continue;
      const data = JSON.parse(dataLine);

      if (event === "sources") handlers.onSources?.(data.sources);
      else if (event === "token") handlers.onToken?.(data.text);
      else if (event === "error") handlers.onError?.(data.message);
    }
  }
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

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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

/** URL for the meeting's WAV — point an <audio> element straight at it. */
export function meetingAudioUrl(meetingId: number): string {
  return `${API_BASE}/meetings/${meetingId}/audio`;
}

export function updateSegmentText(
  meetingId: number,
  segmentId: number,
  text: string,
): Promise<{ updated: boolean }> {
  return patchJson<{ updated: boolean }>(
    `/meetings/${meetingId}/segments/${segmentId}`,
    { text },
  );
}

export interface ActionItem {
  id: number;
  meeting_id: number;
  meeting_title: string;
  meeting_started_at: string;
  text: string;
  done: boolean;
}

export function getActionItems(): Promise<ActionItem[]> {
  return getJson<ActionItem[]>("/action-items");
}

export function setActionItemDone(
  itemId: number,
  done: boolean,
): Promise<{ updated: boolean }> {
  return patchJson<{ updated: boolean }>(`/action-items/${itemId}`, { done });
}

export interface ModelStatus {
  state: "unknown" | "absent" | "downloading" | "ready" | "error";
  model: string | null;
  progress: number;
  done_bytes: number;
  total_bytes: number;
  error: string | null;
}

export function getModelStatus(): Promise<ModelStatus> {
  return getJson<ModelStatus>("/system/model-status");
}

export function startModelDownload(): Promise<ModelStatus> {
  return postJson<ModelStatus>("/system/model-download");
}

export interface MeetingApp {
  app: string | null;
  since: number | null;
  recording: boolean;
  mode: "off" | "prompt" | "auto";
}

export function getMeetingApp(): Promise<MeetingApp> {
  return getJson<MeetingApp>("/system/meeting-app");
}

export interface SpeakerPackStatus {
  state: "idle" | "downloading" | "error";
  progress: number;
  error: string | null;
  installed: boolean;
}

export function getSpeakerPackStatus(): Promise<SpeakerPackStatus> {
  return getJson<SpeakerPackStatus>("/system/speaker-pack");
}

export function installSpeakerPack(): Promise<SpeakerPackStatus> {
  return postJson<SpeakerPackStatus>("/system/speaker-pack-install");
}