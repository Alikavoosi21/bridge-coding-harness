/**
 * The renderer's authenticated client for the local task API.
 *
 * Two rules matter here:
 *
 * - the app token travels in `Authorization`, never in the URL. A URL ends up in
 *   logs, history and error reports, and a query string is not a secret store;
 * - there is no provider key in this file. Keys live in the backend keychain and
 *   are never sent to the renderer, so a Next route or a React component cannot
 *   leak one.
 *
 * Events are read from the durable journal at `GET /tasks/{id}/events`. The
 * current backend answers with JSON `{items, last_event_seq}`; the same function
 * already understands `text/event-stream` so the SSE endpoint can arrive later
 * without a second transport in the UI.
 */

import type { EventEnvelope, EventType, TaskState } from './schema';
import { EVENT_TYPES } from './schema';
export type HarnessGrant = {id:string;task_id:string;capability:string;fingerprint:string;expiry:number|null;revoked_at:number|null;created_at:number;active:boolean};
export type RepairBudgetData={task_id:string;allowed:number;total_attempts:number;revision:number};
export type CheckEvidence={id:string;target_kind:'working_copy'|'apply_candidate';selection_id:string|null;profile_hash:string;input_manifest_hash:string;runtime_fingerprint:string;outcome:'passed'|'failed'|'skipped'|'not_configured'|'stopped'|'timed_out';created_at:number;details:{check_id:string;command:string;phase:'baseline'|'current';output:string;truncated:boolean;failure_kind:'assertion'|'installation'|'network'|'runtime'|null}};
export type TaskChecks={items:CheckEvidence[];quality:{quality_status:'verified_snapshot'|'not_verified'|'stale'|'failed';check_refs:string[];baseline_missing?:boolean;check_inputs_changed?:boolean;profile_changed?:boolean};required:string[];input_manifest_hash:string|null;profile_hash:string|null;runtime_fingerprint:string|null;repair_budget:RepairBudgetData;execution_budget:HarnessBudgetData};
import type { CanonicalMessage, HarnessBudgetData, HarnessEvent, HarnessPlanData } from './projection';

export type HarnessEventPage = {
  items: HarnessEvent[];
  last_event_seq: number;
};

export type HarnessRun = {
  id: string;
  task_id: string;
  segment: number;
  state: string;
  budget_id?: string | null;
  worker_lease_id?: string | null;
  created_at?: number;
  started_at?: number | null;
  ended_at?: number | null;
};

/** The list rows of `GET /tasks`; a list row has no journal cursor or plan. */
export type HarnessTaskSummary = {
  id: string;
  workspace_id: string;
  thread_id?: string | null;
  title?: string | null;
  prompt?: string | null;
  status: TaskState;
  outcome?: string | null;
  mode?: string;
  read_only?: boolean;
  revision?: number;
  created_at?: number;
  updated_at?: number;
};

export type HarnessTaskList = {
  items: HarnessTaskSummary[];
  next: string | null;
};

export type HarnessTaskSnapshot = {
  id: string;
  workspace_id: string;
  thread_id?: string | null;
  title?: string | null;
  prompt?: string | null;
  status: TaskState;
  outcome?: string | null;
  mode?: string;
  read_only?: boolean;
  revision?: number;
  created_at?: number;
  updated_at?: number;
  last_event_seq: number;
  budget?: HarnessBudgetData | null;
  runs?: HarnessRun[];
  plan?: HarnessPlanData | null;
  /** The future canonical snapshot; the projector needs it to continue partial text. */
  messages?: CanonicalMessage[];
  worker_lease?: Record<string, unknown> | null;
  workspace_lease?: Record<string, unknown> | null;
};

export type StartTaskInput = {
  prompt: string;
  workspace_id?: string;
  title?: string;
  model_id?: string;
  mode?: 'ask' | 'grant' | 'auto';
  read_only?: boolean;
  references?: string[];
  limits?: Partial<Record<'active_ms' | 'model_calls' | 'tool_calls', number>>;
  idempotency_key?: string;
};

export type StartTaskResult = {
  task: HarnessTaskSnapshot;
  run: HarnessRun | null;
  last_event_seq: number;
};

export type SendMessageInput = {
  text: string;
  references?: string[];
  expected_revision?: number;
  idempotency_key?: string;
};

export type PlanProposalInput = {
  /** A correction after a plan was shown. It becomes a durable user message. */
  instruction?: string;
  references?: string[];
  expected_revision?: number;
  idempotency_key?: string;
};

export type ContinuationInput = {
  /** The plan revision the user saw approved. The server re-checks it. */
  expected_plan_revision?: number;
  idempotency_key?: string;
};

export type PlanStepInput = {
  id?: string | null;
  title: string;
  status?: 'pending' | 'in_progress' | 'completed';
  detail?: string | null;
};

export type UpdatePlanInput = {
  expected_revision: number;
  steps: PlanStepInput[];
  scope?: string[];
  checks?: string[];
};

export type PlanDecisionInput = {
  decision: 'approve' | 'reject';
  expected_revision: number;
  idempotency_key?: string;
};

export type HarnessMessage = {
  id: string;
  task_id?: string;
  role: 'system' | 'user' | 'assistant';
  parts: CanonicalMessage['parts'];
  references?: string[];
  offset?: number;
  created_at?: number;
  delivered_at?: number | null;
};

export type PlanProposalResult = {
  task: HarnessTaskSnapshot;
  plan: HarnessPlanData | null;
  message: HarnessMessage | null;
};

export type SendMessageResult = { message: HarnessMessage; task: HarnessTaskSnapshot };

export type HarnessApproval = {
  id: string; task_id: string; action_id: string; action_hash: string; revision: number;
  state: 'pending' | 'decided' | 'superseded' | 'cancelled'; decision: string | null;
  request: { tool: string; args: Record<string,unknown>; cwd: string; shell: string; runtime: string; environment_profile: string; plan_revision: number; rejection_reason?: string; review?:{reason:string;effect:string;path:string|null;sandbox_network:boolean} } | null;
};
export type ApprovalDecisionInput = { decision: 'approve'|'reject'; fingerprint: string; revision: number; grant?: boolean; reason?: string };
export type ApprovalMutation = { approval: HarnessApproval; task: HarnessTaskSnapshot };

export type ContinuationResult = {
  task: HarnessTaskSnapshot;
  plan: HarnessPlanData | null;
  run: HarnessRun | null;
};

export type PlanMutationResult = {
  plan: HarnessPlanData;
  task: HarnessTaskSnapshot;
};

export type HarnessApiErrorBody = {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  retryable?: boolean;
  current_revision?: number;
};

/** A typed failure from the API or from the event stream. */
export class HarnessRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
    readonly retryable = false,
    readonly currentRevision?: number,
  ) {
    super(message);
    this.name = 'HarnessRequestError';
  }
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export type HarnessClientOptions = {
  baseUrl: string;
  token: string;
  fetchImpl?: FetchLike;
};

type RequestOptions = {
  body?: unknown;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  idempotencyKey?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isAbort(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { name?: unknown }).name === 'AbortError';
}

/** Validate one journal envelope before it reaches the projector. */
export function isHarnessEvent(value: unknown): value is HarnessEvent {
  if (!isRecord(value)) return false;
  return (
    value.schema_version === 1 &&
    typeof value.task_id === 'string' &&
    (value.run_id === null || typeof value.run_id === 'string') &&
    typeof value.sequence === 'number' &&
    Number.isInteger(value.sequence) &&
    value.sequence > 0 &&
    typeof value.event_id === 'string' &&
    typeof value.type === 'string' &&
    (EVENT_TYPES as readonly string[]).includes(value.type) &&
    typeof value.occurred_at === 'number' &&
    isRecord(value.payload)
  );
}

// ── SSE ─────────────────────────────────────────────────────────────────────

export type SseFrame = {
  event: string;
  id?: string;
  data: string;
};

/**
 * Incremental SSE decoder. It accepts frames split across arbitrary chunks,
 * ignores `:` comments (keepalive), joins multi-line `data:` fields and treats a
 * blank line as the dispatch point.
 */
export class SseDecoder {
  private buffer = '';
  private dataLines: string[] = [];
  private event = 'message';
  private id: string | undefined;

  push(chunk: string): SseFrame[] {
    this.buffer += chunk;
    const frames: SseFrame[] = [];
    let newline = this.buffer.indexOf('\n');
    while (newline >= 0) {
      const line = this.buffer.slice(0, newline).replace(/\r$/, '');
      this.buffer = this.buffer.slice(newline + 1);
      this.line(line, frames);
      newline = this.buffer.indexOf('\n');
    }
    return frames;
  }

  end(): SseFrame[] {
    const frames: SseFrame[] = [];
    if (this.buffer.length > 0) {
      this.line(this.buffer.replace(/\r$/, ''), frames);
      this.buffer = '';
    }
    this.dispatch(frames);
    return frames;
  }

  private line(line: string, frames: SseFrame[]): void {
    if (line === '') {
      this.dispatch(frames);
      return;
    }
    if (line.startsWith(':')) return; // keepalive / comment, never transcript
    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'data') this.dataLines.push(value);
    else if (field === 'event') this.event = value || 'message';
    else if (field === 'id') this.id = value;
  }

  private dispatch(frames: SseFrame[]): void {
    if (this.dataLines.length > 0) {
      frames.push({
        event: this.event,
        ...(this.id === undefined ? {} : { id: this.id }),
        data: this.dataLines.join('\n'),
      });
    }
    this.dataLines = [];
    this.event = 'message';
    this.id = undefined;
  }
}

export async function* readSseFrames(body: ReadableStream<Uint8Array>): AsyncGenerator<SseFrame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const sse = new SseDecoder();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const frame of sse.push(decoder.decode(value, { stream: true }))) yield frame;
    }
    for (const frame of sse.end()) yield frame;
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

// ── client ──────────────────────────────────────────────────────────────────

export class HarnessClient {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly fetchImpl: FetchLike;

  constructor(options: HarnessClientOptions) {
    let parsed: URL;
    try {
      parsed = new URL(options.baseUrl);
    } catch {
      throw new HarnessRequestError(0, 'invalid_base_url', 'The backend address is not a valid URL.');
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      throw new HarnessRequestError(0, 'invalid_base_url', 'The backend address must be http(s).');
    }
    this.baseUrl = parsed.toString().replace(/\/$/, '');
    this.token = options.token;
    this.fetchImpl = options.fetchImpl ?? ((input, init) => fetch(input, init));
  }

  /** Read the canonical snapshot for one task. */
  task(taskId: string): Promise<HarnessTaskSnapshot> {
    return this.send<HarnessTaskSnapshot>('GET', `/tasks/${encodeURIComponent(taskId)}`);
  }

  /** Create a new task. The response is a replay when the idempotency key repeats. */
  startTask(input: StartTaskInput): Promise<StartTaskResult> {
    return this.send<StartTaskResult>('POST', '/tasks', {
      body: input,
      idempotencyKey: input.idempotency_key,
    });
  }

  /** Tasks in the open workspace (or one explicit workspace). */
  listTasks(
    options: { workspace_id?: string; status?: TaskState; limit?: number; after?: string } = {},
  ): Promise<HarnessTaskList> {
    const params = new URLSearchParams();
    if (options.workspace_id) params.set('workspace_id', options.workspace_id);
    if (options.status) params.set('status', options.status);
    if (options.limit !== undefined) params.set('limit', String(options.limit));
    if (options.after) params.set('after', options.after);
    const query = params.toString();
    return this.send<HarnessTaskList>('GET', `/tasks${query ? `?${query}` : ''}`);
  }

  /** Steer an existing task. This never starts a second run segment. */
  sendMessage(taskId: string, input: SendMessageInput): Promise<SendMessageResult> {
    return this.send<SendMessageResult>('POST', `/tasks/${encodeURIComponent(taskId)}/messages`, {
      body: input,
      idempotencyKey: input.idempotency_key,
    });
  }

  /**
   * Start a read-only planning pass. This is a separate product action: creating
   * a task does not plan, and a correction is stored before the pass starts.
   */
  proposePlan(taskId: string, input: PlanProposalInput = {}): Promise<PlanProposalResult> {
    return this.send<PlanProposalResult>('POST', `/tasks/${encodeURIComponent(taskId)}/plan-proposals`, {
      body: input,
      idempotencyKey: input.idempotency_key,
    });
  }

  /** Open an execution segment for the exact approved plan revision. */
  continueTask(taskId: string, input: ContinuationInput = {}): Promise<ContinuationResult> {
    return this.send<ContinuationResult>('POST', `/tasks/${encodeURIComponent(taskId)}/continuations`, {
      body: input,
      idempotencyKey: input.idempotency_key,
    });
  }

  /** Save edited steps as a new revision. The server refuses a stale revision. */
  updatePlan(taskId: string, input: UpdatePlanInput): Promise<PlanMutationResult> {
    return this.send<PlanMutationResult>('PATCH', `/tasks/${encodeURIComponent(taskId)}/plan`, { body: input });
  }

  /** Approve or reject exactly the revision the user saw. */
  decidePlan(taskId: string, input: PlanDecisionInput): Promise<PlanMutationResult> {
    return this.send<PlanMutationResult>('POST', `/tasks/${encodeURIComponent(taskId)}/plan-decisions`, {
      body: input,
      idempotencyKey: input.idempotency_key,
    });
  }

  /**
   * The product's Stop button. It is deliberately separate from cancelling a
   * consumer/stream: only an explicit Stop asks the runtime to stop the task.
   */
  stopTask(taskId: string, idempotencyKey?: string): Promise<Record<string, unknown>> {
    return this.send('POST', `/tasks/${encodeURIComponent(taskId)}/stop`, {
      body: { idempotency_key: idempotencyKey },
      idempotencyKey,
    });
  }

  approvals(taskId: string): Promise<{items: HarnessApproval[]}> {
    return this.send('GET',`/tasks/${encodeURIComponent(taskId)}/approvals`);
  }
  checks(taskId:string,signal?:AbortSignal):Promise<TaskChecks>{
    return this.send('GET',`/tasks/${encodeURIComponent(taskId)}/checks`,{signal});
  }
  extendRepair(taskId:string,key:string,revision:number):Promise<RepairBudgetData>{
    return this.send('POST',`/tasks/${encodeURIComponent(taskId)}/repair-extensions`,{body:{idempotency_key:key,expected_revision:revision}});
  }
  endUnverified(taskId:string,key:string,revision:number):Promise<{task:HarnessTaskSnapshot}>{
    return this.send('POST',`/tasks/${encodeURIComponent(taskId)}/quality-endings`,{body:{idempotency_key:key,expected_revision:revision}});
  }
  decideAction(taskId: string, approvalId: string, input: ApprovalDecisionInput): Promise<ApprovalMutation> {
    return this.send('POST',`/tasks/${encodeURIComponent(taskId)}/approvals/${encodeURIComponent(approvalId)}/decisions`,{body:input});
  }
  editAction(taskId: string, approval: HarnessApproval, args: Record<string,unknown>): Promise<ApprovalMutation> {
    return this.send('POST',`/tasks/${encodeURIComponent(taskId)}/approvals/${encodeURIComponent(approval.id)}/edits`,{body:{fingerprint:approval.action_hash,revision:approval.revision,args}});
  }
  changeAccess(taskId: string, mode: 'ask'|'grant'|'auto', expectedRevision: number, readOnly?: boolean): Promise<{task:HarnessTaskSnapshot}> {
    return this.send('PATCH',`/tasks/${encodeURIComponent(taskId)}/access`,{body:{mode,expected_revision:expectedRevision,...(readOnly===undefined?{}:{read_only:readOnly})}});
  }
  grants(taskId: string): Promise<{items:HarnessGrant[]}> {
    return this.send('GET', `/tasks/${encodeURIComponent(taskId)}/grants`);
  }

  revokeGrants(taskId: string): Promise<{revoked:boolean}> {
    return this.send('POST',`/tasks/${encodeURIComponent(taskId)}/grants/revoke`);
  }
  resumeApprovals(taskId: string, key: string): Promise<{task:HarnessTaskSnapshot}> {
    return this.send('POST',`/tasks/${encodeURIComponent(taskId)}/approval-resumptions`,{body:{idempotency_key:key}});
  }

  /** One page of the journal. The backend currently answers with JSON. */
  async events(taskId: string, options: { afterSeq?: number; limit?: number; signal?: AbortSignal } = {}): Promise<HarnessEventPage> {
    const response = await this.open(this.eventsPath(taskId, options.afterSeq ?? 0, options.limit), {
      signal: options.signal,
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw await this.errorFrom(response);
    return this.parsePage(await response.json().catch(() => null));
  }

  /**
   * Read the whole journal as JSON pages. This is for rebuilding state on a
   * reload: it is a read, never a run. The SSE endpoint is used when following
   * a live task.
   */
  async journal(
    taskId: string,
    options: { afterSeq?: number; limit?: number; signal?: AbortSignal } = {},
  ): Promise<HarnessEventPage> {
    const limit = Math.max(1, options.limit ?? 500);
    let cursor = options.afterSeq ?? 0;
    const items: HarnessEvent[] = [];
    let declared = cursor;
    while (true) {
      const page = await this.events(taskId, { afterSeq: cursor, limit, signal: options.signal });
      items.push(...page.items);
      declared = Math.max(declared, page.last_event_seq);
      if (page.items.length === 0) return { items, last_event_seq: declared };
      cursor = page.items[page.items.length - 1].sequence;
      if (page.items.length < limit) return { items, last_event_seq: Math.max(declared, cursor) };
    }
  }

  /**
   * Stream the journal from a cursor. JSON pages are followed until the last
   * page; an SSE response is decoded frame by frame. No call here creates a
   * task, invokes a tool or repeats a command.
   */
  async *streamEvents(
    taskId: string,
    options: { afterSeq?: number; limit?: number; signal?: AbortSignal } = {},
  ): AsyncGenerator<HarnessEvent> {
    const response = await this.open(this.eventsPath(taskId, options.afterSeq ?? 0, options.limit), {
      signal: options.signal,
      headers: { Accept: 'text/event-stream, application/json' },
    });
    if (!response.ok) throw await this.errorFrom(response);

    const contentType = response.headers.get('content-type') ?? '';
    if (contentType.includes('text/event-stream')) {
      if (response.body === null) {
        throw new HarnessRequestError(0, 'invalid_stream', 'The event stream had no body.');
      }
      for await (const frame of readSseFrames(response.body)) {
        if (frame.data === '[DONE]') return;
        if (frame.event === 'error') throw this.errorFromFrame(frame.data);
        let value: unknown;
        try {
          value = JSON.parse(frame.data);
        } catch {
          throw new HarnessRequestError(0, 'invalid_stream', 'The event stream sent malformed JSON.');
        }
        if (!isHarnessEvent(value)) {
          throw new HarnessRequestError(0, 'invalid_stream', 'The event stream sent an event that is not in the contract.');
        }
        yield value;
      }
      return;
    }

    const page = this.parsePage(await response.json().catch(() => null));
    for (const event of page.items) yield event;

    // A JSON replay can be longer than one page. Continue from the last sequence
    // the server returned; an empty page ends the segment.
    const limit = Math.max(1, options.limit ?? 500);
    let cursor = page.items.length > 0 ? page.items[page.items.length - 1].sequence : options.afterSeq ?? 0;
    while (page.items.length >= limit) {
      const next = await this.open(this.eventsPath(taskId, cursor, limit), {
        signal: options.signal,
        headers: { Accept: 'application/json' },
      });
      if (!next.ok) throw await this.errorFrom(next);
      const more = this.parsePage(await next.json().catch(() => null));
      for (const event of more.items) yield event;
      if (more.items.length === 0) return;
      cursor = more.items[more.items.length - 1].sequence;
      if (more.items.length < limit) return;
    }
  }

  // ── internals ─────────────────────────────────────────────────────────────

  private eventsPath(taskId: string, afterSeq: number, limit?: number): string {
    const params = new URLSearchParams({ after_seq: String(Math.max(0, afterSeq)) });
    if (limit !== undefined) params.set('limit', String(limit));
    return `/tasks/${encodeURIComponent(taskId)}/events?${params.toString()}`;
  }

  private async send<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const headers: Record<string, string> = {
      Accept: 'application/json',
      ...options.headers,
    };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;
    if (this.token) headers.Authorization = `Bearer ${this.token}`;

    let response: Response;
    try {
      response = await this.fetchImpl(this.safeUrl(path), {
        method,
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: options.signal,
        credentials: 'omit',
      });
    } catch (error) {
      if (isAbort(error)) throw error;
      throw new HarnessRequestError(0, 'network_error', 'The local backend is not reachable.');
    }
    if (!response.ok) throw await this.errorFrom(response);
    return (await response.json()) as T;
  }

  private async open(path: string, options: { signal?: AbortSignal; headers?: Record<string, string> } = {}): Promise<Response> {
    const headers: Record<string, string> = { ...options.headers };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    try {
      return await this.fetchImpl(this.safeUrl(path), {
        method: 'GET',
        headers,
        signal: options.signal,
        credentials: 'omit',
      });
    } catch (error) {
      if (isAbort(error)) throw error;
      throw new HarnessRequestError(0, 'network_error', 'The local backend is not reachable.');
    }
  }

  /**
   * Build the URL and refuse to put a secret in it. The token belongs in the
   * header; a caller that tries `?token=` gets a clear error instead of a log
   * line with the token in it.
   */
  private safeUrl(path: string): string {
    const url = new URL(`${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`);
    for (const key of url.searchParams.keys()) {
      if (/token|secret|api[_-]?key|password/i.test(key)) {
        throw new HarnessRequestError(0, 'secret_in_url', 'Secrets must not be sent in a URL.');
      }
    }
    if (this.token && url.toString().includes(this.token)) {
      throw new HarnessRequestError(0, 'secret_in_url', 'Secrets must not be sent in a URL.');
    }
    return url.toString();
  }

  private parsePage(value: unknown): HarnessEventPage {
    if (!isRecord(value) || !Array.isArray(value.items)) {
      throw new HarnessRequestError(0, 'invalid_response', 'The events response is not in the contract.');
    }
    const items: HarnessEvent[] = [];
    for (const item of value.items) {
      if (!isHarnessEvent(item)) {
        throw new HarnessRequestError(0, 'invalid_response', 'The events response contains an event that is not in the contract.');
      }
      items.push(item);
    }
    const last = items.length > 0 ? items[items.length - 1].sequence : 0;
    const declared = typeof value.last_event_seq === 'number' ? value.last_event_seq : last;
    return { items, last_event_seq: declared };
  }

  private async errorFrom(response: Response): Promise<HarnessRequestError> {
    const body = (await response.json().catch(() => null)) as Partial<HarnessApiErrorBody> | null;
    if (body !== null && typeof body.code === 'string' && typeof body.message === 'string') {
      return new HarnessRequestError(
        response.status,
        body.code,
        body.message,
        isRecord(body.details) ? body.details : {},
        body.retryable === true,
        typeof body.current_revision === 'number' ? body.current_revision : undefined,
      );
    }
    return new HarnessRequestError(response.status, `http_${response.status}`, `The local API answered ${response.status}.`);
  }

  private errorFromFrame(data: string): HarnessRequestError {
    try {
      const body = JSON.parse(data) as Partial<HarnessApiErrorBody>;
      if (isRecord(body) && typeof body.code === 'string' && typeof body.message === 'string') {
        return new HarnessRequestError(
          0,
          body.code,
          body.message,
          isRecord(body.details) ? body.details : {},
          body.retryable === true,
          typeof body.current_revision === 'number' ? body.current_revision : undefined,
        );
      }
    } catch {
      // Fall through to the generic stream error.
    }
    return new HarnessRequestError(0, 'stream_error', 'The event stream reported an error.');
  }
}

export type EventTypeName = EventType;
export type EventEnvelopeShape = EventEnvelope;
