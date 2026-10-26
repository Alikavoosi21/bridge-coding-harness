'use client';

// The one place the UI talks to the local backend (backend/server).
// In the desktop app the address and token come from Electron; in a browser
// during development the backend is expected on its default port.


const target = () => (typeof window !== 'undefined' && window.desktop?.api) || { url: 'http://127.0.0.1:8765', token: '' };

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code = 'error',
    public details: Record<string, any> = {},
    public retryable = false,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const { url, token } = target();
  let response: Response;
  try {
    response = await fetch(url + path, {
      method,
      headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, 'موتور برنامه در دسترس نیست.');
  }
  if (!response.ok) {
    // The backend has one error shape: {code,message,details,retryable}. Older
    // routes may still answer with FastAPI's {detail: "..."}.
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const message = typeof payload?.message === 'string' ? payload.message : typeof detail === 'string' ? detail : `خطای ${response.status}`;
    throw new ApiError(response.status, message, typeof payload?.code === 'string' ? payload.code : 'error', payload?.details ?? {}, Boolean(payload?.retryable));
  }
  return response.json() as Promise<T>;
}

/** A workspace image or PDF as a local object URL. The token travels in a header, so a plain `src` cannot fetch it. */
export async function fileUrl(path: string, type: string): Promise<string> {
  const { url, token } = target();
  const response = await fetch(`${url}/files/raw?path=${encodeURIComponent(path)}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!response.ok) throw new ApiError(response.status, `خطای ${response.status}`);
  // The type is ours, not the server's: the bytes are only ever treated as the picture or PDF we asked for.
  return URL.createObjectURL(new Blob([await response.arrayBuffer()], { type }));
}

/** An address a player can use for one sound or video file. It carries a short-lived ticket for that file only. */
export async function mediaUrl(path: string): Promise<string> {
  const { ticket } = await request<{ ticket: string }>('POST', '/files/media-ticket', { path });
  return `${target().url}/files/media/${ticket}`;
}

export type TablePreview = { kind: 'table'; sheets: string[]; sheet: string | null; columns: string[]; rows: (string | number)[][]; total_rows: number; truncated: boolean };
export type DocumentPreview = { kind: 'document'; markdown: string };

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
};

export async function downloadDiagnostics(identifier:string):Promise<Blob>{
  if(!/^diagnostic_[0-9a-f]{32}$/.test(identifier))throw new Error('شناسهٔ بسته معتبر نیست.');
  const {url,token}=target();
  const response=await fetch(`${url}/diagnostics/exports/${identifier}/download`,{headers:token?{Authorization:`Bearer ${token}`}:{}});
  if(!response.ok)throw new Error('دریافت بستهٔ محلی ممکن نشد.');
  return response.blob();
}

/* ───────────── types (mirror backend/harness/events.py and server routes) ───────────── */

export type RunEvent = { type: string; thread_id: string; at: number; data: Record<string, any> };

export type PendingAction = { tool: string; args: Record<string, any>; description: string; allowed: string[] };

export type RunSummary = {
  thread_id: string;
  title?: string;
  status: 'running' | 'waiting' | 'finished';
  stop_reason?: string;
  pending?: PendingAction[];
  updated_at: number;
  model?: string;
  model_id?: string;
  agent_id?: string | null;
  mode?: Mode;
  cost?: number;
  input_tokens?: number;
  output_tokens?: number;
  seconds?: number;
  error?: string;
  running?: boolean;
};

export type Mode = 'read_only' | 'ask' | 'auto';

/** The result of a real tool-call probe. `tools: null` means the check could not decide. */
export type ModelCapabilities = {
  model: string;
  tools: boolean | null;
  provider_reachable: boolean;
  demo: boolean;
  streaming: boolean;
  error_code: 'provider_auth' | 'provider_unreachable' | 'model_not_found' | 'tools_unsupported' | 'provider_error' | 'tools_not_observed' | null;
  error_message: string | null;
  checked_at: number;
};

export type Model = {
  id: string;
  name: string;
  base_url: string;
  model: string;
  has_key: boolean;
  is_default: boolean;
  streaming?: boolean;
  input_price?: number;
  output_price?: number;
  capabilities?: ModelCapabilities | null;
};

export type ProbeResponse = { id: string; probe: ModelCapabilities } & Partial<Model>;

export type FileEntry = { path: string; name: string; folder: string; size: number; modified: number; system: boolean };

export type Workspace = { path: string | null; name: string | null; known: { path: string; name: string }[] };

export type Skill = { id: string; name: string; description: string; body: string };
export type AgentProfile = { id: string; title: string; description: string; prompt: string; tools: string[] };

/* ───────────── setup, readiness and preflight (T005) ───────────── */

export type SetupStep = 1 | 2 | 3 | 4;

export type SetupState = {
  deferred?: boolean;
  step: SetupStep;
  completed: boolean;
  completed_at: number | null;
  acknowledgements: Record<string, boolean>;
};

export type DisclosureKey = 'model_api' | 'sandbox_network' | 'demo_state' | 'read_only';

export type Settings = {
  models: Model[];
  default_model: string | null;
  workspace: { open: boolean; id: string | null; name: string | null; path: string | null; profile: WorkspaceProfile | null };
  setup: SetupState;
  disclosures: Record<DisclosureKey, boolean>;
};

export type ReadinessIssue = {
  component: 'engine' | 'schema' | 'runtime' | 'workspace' | 'model' | string;
  code: string;
  message: string;
  retryable: boolean;
};

export type Readiness = {
  engine: { ok: boolean; python: string; platform: string };
  schema: { ok: boolean; version: number | null; expected: number };
  runtime: {
    available: boolean;
    reason: string;
    server_version: string | null;
    image: string;
    image_present: boolean;
    dockerfile?: string;
  };
  worker: { state: 'idle' | 'busy' | 'unknown'; fencing_token: number | null; reason?: string };
  model: {
    configured: boolean;
    id: string | null;
    name: string | null;
    demo: boolean;
    has_key: boolean;
    tools: boolean | null;
    capability_checked_at?: number | null;
    capability_error?: string | null;
  };
  workspace: { open: boolean; name: string | null };
  task: { can_chat: boolean; can_execute: boolean; can_write: boolean; mode: 'sandbox' | 'read_only'; reason: string };
  legacy_runs: { mode: string; reason: string };
  issues: ReadinessIssue[];
};

export type PreflightCommand = { id: string; label: string; command: string; source: string; required: boolean; timeout: number };

export type PreflightInstall = { command: string; source: string; requires_consent: boolean };

export type PreflightConflict = { code: string; message: string; files: string[] };

export type Preflight = {
  workspace?: WorkspaceDetail;
  root_name: string;
  scan: { file_count: number; bytes: number; symlinks: number; secret_files: number; truncated: boolean; skipped_folders: string[] };
  detected: {
    package_json: boolean;
    pyproject: boolean;
    node_lockfiles: string[];
    python_lockfiles: string[];
    node_manager: string | null;
    python_manager: string | null;
    kind: 'node' | 'python' | 'mixed' | 'generic';
  };
  profile: {
    commands: PreflightCommand[];
    install: PreflightInstall | null;
    installs: PreflightInstall[];
    notes: string[];
    suggested: boolean;
    requires_consent: boolean;
    executed: false;
  };
  conflicts: PreflightConflict[];
  read_only: true;
};

export type WorkspaceProfile = {
  commands: PreflightCommand[];
  install: PreflightInstall | null;
  profile_hash?: string;
  analysis_hash?: string;
};

export type WorkspaceDetail = {
  id: string;
  root: string;
  name: string;
  profile: WorkspaceProfile | null;
  exclusions: string[];
  manifest_hash: string | null;
  current: boolean;
};

export type WorkspacePatch = { name?: string; profile?: { commands: PreflightCommand[]; install?: PreflightInstall | null } };


/** Follow a run live. Replays what already happened, then streams until the run ends. Returns a stop function. */
export function watchRun(threadId: string, onEvent: (event: RunEvent) => void, onEnd: () => void): () => void {
  const { url, token } = target();
  const controller = new AbortController();

  // Read the event stream with fetch, not EventSource: EventSource cannot send
  // headers, and the token must not travel in the address.
  (async () => {
    try {
      const response = await fetch(`${url}/runs/${threadId}/events`, { headers: token ? { Authorization: `Bearer ${token}` } : {}, signal: controller.signal });
      if (!response.ok || !response.body) return;
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) return;
        buffer += value;
        for (let cut = buffer.indexOf('\n\n'); cut >= 0; cut = buffer.indexOf('\n\n')) {
          const block = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          if (block.startsWith('event: end')) return;
          if (block.startsWith('data: ')) onEvent(JSON.parse(block.slice(6)));
        }
      }
    } catch {
      // stopped by the caller, or the connection dropped
    } finally {
      if (!controller.signal.aborted) onEnd();
    }
  })();

  return () => controller.abort();
}
