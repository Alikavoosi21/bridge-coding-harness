/**
 * Canonical harness events -> AI SDK UI chunks.
 *
 * The journal is the single source of truth. This module is the only place that
 * turns it into what `useChat` renders, and it is deliberately strict:
 *
 * - a sequence is applied once; a replay from an older cursor is a no-op, and a
 *   missing sequence is a `EventGapError` instead of text silently jumping;
 * - a text delta carries its absolute offset, so a reconnect cannot append the
 *   same words twice. Offsets are counted in Unicode code points, which matches
 *   Python's `len()` on the backend and avoids breaking an emoji in half;
 * - a `finish` chunk ends a *segment*, never the task. Only a terminal task
 *   state marks the task closed. A task waiting for a decision is still open;
 * - domain events (plan, approval, action, budget, lease, quality, file,
 *   verification, repair, task state, recovery) become typed `data-harness`
 *   parts. The model's text is never used as permission state.
 *
 * The projector keeps its own state so both live streaming and a reloaded page
 * can continue from the same cursor without asking the runtime to run anything
 * again.
 */

import type { FinishReason, UIMessage, UIMessageChunk } from 'ai';

import type {
  ActionState,
  EventEnvelope,
  EventType,
  FileChangeKind,
  LeaseState,
  QualityStatus,
  TaskState,
  VerificationOutcome,
  VerificationTarget,
} from './schema';

export type HarnessEvent<T = unknown> = EventEnvelope<T>;

/** A task state that means no further events will arrive on their own. */
const TERMINAL_STATES: ReadonlySet<TaskState> = new Set<TaskState>(['closed', 'failed', 'cancelled']);

export function isTerminalTaskState(state: TaskState | null | undefined): boolean {
  return state != null && TERMINAL_STATES.has(state);
}

// ── typed domain data ───────────────────────────────────────────────────────

export type HarnessPlanStep = {
  id: string;
  title: string;
  detail?: string;
  status?: string;
};

export type HarnessPlanData = {
  revision: number | null;
  steps: HarnessPlanStep[];
  scope: string[];
  checks: string[];
  approved_revision?: number | null;
};

export type HarnessApprovalData = {
  approval_id: string;
  revision: number | null;
  action_hash: string | null;
  tool: string | null;
  state: 'required' | 'decided';
  decision?: 'approve' | 'edit' | 'reject' | null;
  scope?: string[];
  summary?: string | null;
};

export type HarnessActionData = {
  /** Stable across run segments. Never derived from the command text. */
  operation_id: string;
  action_id: string | null;
  tool: string | null;
  state: ActionState;
  summary?: string | null;
  receipt?: unknown;
};

export type HarnessBudgetData = {
  revision: number;
  active_ms: number;
  model_calls: number;
  tool_calls: number;
  max_active_ms: number;
  max_model_calls: number;
  max_tool_calls: number;
};

export type HarnessLeaseData = {
  workspace_id: string;
  state: LeaseState;
  fencing_token: number;
  kind?: string | null;
  operation_id?: string | null;
};

export type HarnessQualityData = {
  selection_id: string;
  quality_status: QualityStatus;
  target_kind: VerificationTarget;
  candidate_manifest_hash?: string | null;
  check_refs?: string[];
};

export type HarnessFileData = {
  file_id: string;
  path: string;
  change_kind: FileChangeKind;
  hash?: string | null;
  size?: number | null;
};

export type HarnessVerificationData = {
  target_kind: VerificationTarget;
  outcome: VerificationOutcome;
  selection_id?: string | null;
  candidate_manifest_hash?: string | null;
  check_refs?: string[];
};

export type HarnessRepairData = {
  repair_index: number;
  reason: string | null;
};

export type HarnessTaskStateData = {
  revision?: number;
  state: TaskState;
  reason: string | null;
  outcome: string | null;
};

export type HarnessApplyFileData = {
  file_id: string;
  state: string;
  operation_id: string;
};

export type HarnessRecoveryData = {
  operation_id: string | null;
  reason: string;
  reconcile_required: boolean;
};

type HarnessDataBase = {
  task_id: string;
  sequence: number;
  event_id: string;
  run_id: string | null;
  occurred_at: number;
};

/**
 * The one data part the UI reads. `kind` is the discriminant; every branch is a
 * canonical domain fact, not a guess made from model text.
 */
export type HarnessDataPart =
  | (HarnessDataBase & { kind: 'plan'; plan: HarnessPlanData })
  | (HarnessDataBase & { kind: 'approval'; approval: HarnessApprovalData })
  | (HarnessDataBase & { kind: 'action'; action: HarnessActionData })
  | (HarnessDataBase & { kind: 'budget'; budget: HarnessBudgetData })
  | (HarnessDataBase & { kind: 'lease'; lease: HarnessLeaseData })
  | (HarnessDataBase & { kind: 'quality'; quality: HarnessQualityData })
  | (HarnessDataBase & { kind: 'file'; file: HarnessFileData })
  | (HarnessDataBase & { kind: 'verification'; verification: HarnessVerificationData })
  | (HarnessDataBase & { kind: 'repair'; repair: HarnessRepairData })
  | (HarnessDataBase & { kind: 'task-state'; task: HarnessTaskStateData })
  | (HarnessDataBase & { kind: 'apply-file'; file: HarnessApplyFileData })
  | (HarnessDataBase & { kind: 'recovery'; recovery: HarnessRecoveryData });

export type HarnessMessageMetadata = {
  task_id: string;
  last_event_seq: number;
  task_state: TaskState | null;
  /** True when this chunk set ends a transport segment, not the task. */
  segment_finished: boolean;
  task_closed: boolean;
  /** Files the user pointed at; a reference is not a permission grant. */
  references?: string[];
  /** When a running model turn actually received a steering message. */
  delivered_at?: number | null;
};

/** The message shape `useChat` renders for this product. */
export type HarnessChatMessage = UIMessage<HarnessMessageMetadata, { harness: HarnessDataPart }>;

/** A text part in a durable snapshot, with its stable part id. */
export type CanonicalTextPart = {
  id: string;
  text: string;
  state?: 'streaming' | 'done';
};

export type CanonicalMessage = {
  id: string;
  role: 'system' | 'user' | 'assistant';
  parts: CanonicalTextPart[];
  /** Project-relative files the message points at; user messages carry these. */
  references?: string[];
  delivered_at?: number | null;
  /** Product message order and creation time; an assistant message has neither. */
  offset?: number;
  created_at?: number;
};

/**
 * What a reloaded page can hydrate from. `messages` is required for continuing
 * a partially streamed assistant message; the backend snapshot supplies it.
 */
export type HarnessSnapshot = {
  task_id: string;
  last_event_seq: number;
  status?: TaskState | null;
  messages?: CanonicalMessage[];
  plan?: HarnessPlanData | null;
  budget?: HarnessBudgetData | null;
};

// ── state and errors ────────────────────────────────────────────────────────

export type ProjectionErrorCode =
  | 'invalid_payload'
  | 'task_mismatch'
  | 'duplicate_event_id'
  | 'message_missing'
  | 'message_finished'
  | 'offset_gap'
  | 'text_conflict'
  | 'state_conflict';

export class ProjectionError extends Error {
  constructor(
    readonly code: ProjectionErrorCode,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = 'ProjectionError';
  }
}

/** The journal skipped a sequence: re-read the task snapshot and resume. */
export class EventGapError extends Error {
  constructor(
    readonly expected: number,
    readonly received: number,
  ) {
    super(`Event sequence gap: expected ${expected}, received ${received}. Read the task snapshot again.`);
    this.name = 'EventGapError';
  }
}

export type HarnessDomainState = {
  taskState: TaskState | null;
  plan: HarnessPlanData | null;
  budget: HarnessBudgetData | null;
  approvals: Record<string, HarnessApprovalData>;
  actions: Record<string, HarnessActionData>;
  leases: Record<string, HarnessLeaseData>;
  quality: Record<string, HarnessQualityData>;
  files: Record<string, HarnessFileData>;
  verifications: HarnessVerificationData[];
  repairs: HarnessRepairData[];
  recovery: HarnessRecoveryData | null;
  applyFiles: Record<string, HarnessApplyFileData>;
};

type TextPartState = {
  id: string;
  text: string;
  state: 'streaming' | 'done';
};

type MessageState = {
  id: string;
  role: CanonicalMessage['role'];
  parts: TextPartState[];
  finished: boolean;
  references?: string[];
  delivered_at?: number | null;
};

export type ProjectorOptions = {
  taskId: string;
  cursor?: number;
  status?: TaskState | null;
  messages?: CanonicalMessage[];
  plan?: HarnessPlanData | null;
  budget?: HarnessBudgetData | null;
};

export type ProjectorSnapshot = {
  task_id: string;
  last_event_seq: number;
  task_state: TaskState | null;
  task_closed: boolean;
  messages: HarnessChatMessage[];
  domain: HarnessDomainState;
};

// ── payload readers ─────────────────────────────────────────────────────────

type Payload = Record<string, unknown>;

function asPayload(value: unknown): Payload {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new ProjectionError('invalid_payload', 'The event payload is not an object.');
  }
  return value as Payload;
}

function text(value: unknown, field: string, required = true): string | null {
  if (value === undefined || value === null || value === '') {
    if (required) throw new ProjectionError('invalid_payload', `The event payload is missing ${field}.`, { field });
    return null;
  }
  if (typeof value !== 'string') {
    throw new ProjectionError('invalid_payload', `The event payload field ${field} must be a string.`, { field });
  }
  return value;
}

function number(value: unknown, field: string, fallback?: number): number {
  if (value === undefined || value === null) {
    if (fallback !== undefined) return fallback;
    throw new ProjectionError('invalid_payload', `The event payload is missing ${field}.`, { field });
  }
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new ProjectionError('invalid_payload', `The event payload field ${field} must be a number.`, { field });
  }
  return value;
}

function list<T>(value: unknown, field: string, map: (item: unknown) => T): T[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    throw new ProjectionError('invalid_payload', `The event payload field ${field} must be a list.`, { field });
  }
  return value.map(map);
}

function oneOf<T extends string>(value: unknown, field: string, allowed: readonly T[]): T {
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) {
    throw new ProjectionError('invalid_payload', `The event payload field ${field} is not one of the contract values.`, {
      field,
      received: value,
    });
  }
  return value as T;
}

function planStep(value: unknown): HarnessPlanStep {
  const step = asPayload(value);
  return {
    id: text(step.id, 'steps[].id') as string,
    title: text(step.title, 'steps[].title') as string,
    ...(typeof step.detail === 'string' ? { detail: step.detail } : {}),
    ...(typeof step.status === 'string' ? { status: step.status } : {}),
  };
}

function planFromPayload(payload: Payload): HarnessPlanData {
  return {
    revision: payload.revision === undefined || payload.revision === null ? null : number(payload.revision, 'revision'),
    steps: list(payload.steps, 'steps', planStep),
    scope: list(payload.scope, 'scope', (item) => String(item)),
    checks: list(payload.checks, 'checks', (item) => String(item)),
    ...(payload.approved_revision === undefined || payload.approved_revision === null
      ? {}
      : { approved_revision: number(payload.approved_revision, 'approved_revision') }),
  };
}

function budgetFromPayload(payload: Payload): HarnessBudgetData {
  return {
    revision: number(payload.revision, 'revision', 1),
    active_ms: number(payload.active_ms, 'active_ms', 0),
    model_calls: number(payload.model_calls, 'model_calls', 0),
    tool_calls: number(payload.tool_calls, 'tool_calls', 0),
    max_active_ms: number(payload.max_active_ms, 'max_active_ms', 0),
    max_model_calls: number(payload.max_model_calls, 'max_model_calls', 0),
    max_tool_calls: number(payload.max_tool_calls, 'max_tool_calls', 0),
  };
}

function finishReason(value: unknown): FinishReason {
  switch (value) {
    case 'length':
    case 'limit':
    case 'budget':
      return 'length';
    case 'tool-calls':
    case 'tool':
      return 'tool-calls';
    case 'content-filter':
      return 'content-filter';
    case 'error':
    case 'failed':
      return 'error';
    case 'interrupted':
    case 'stopped':
      return 'interrupted';
    case 'other':
    case 'unknown':
      return 'other';
    default:
      return 'stop';
  }
}

function codePoints(value: string): string[] {
  return Array.from(value);
}

// ── the projector ───────────────────────────────────────────────────────────

export class HarnessEventProjector {
  readonly taskId: string;

  private cursor: number;
  private taskState: TaskState | null;
  private messagesState: MessageState[];
  private readonly seenEventIds = new Set<string>();
  private readonly domain: HarnessDomainState;
  private finishEmitted = false;
  /** The task state carried by the last finish chunk, so a later state change is visible. */
  private finishState: TaskState | null | undefined;
  private started = false;

  constructor(options: ProjectorOptions) {
    this.taskId = options.taskId;
    this.cursor = options.cursor ?? 0;
    this.taskState = options.status ?? null;
    this.messagesState = (options.messages ?? []).map((message) => ({
      id: message.id,
      role: message.role,
      parts: message.parts.map((part) => ({
        id: part.id,
        text: part.text,
        state: part.state ?? 'streaming',
      })),
      finished: message.parts.every((part) => (part.state ?? 'streaming') === 'done'),
      ...(message.references && message.references.length > 0 ? { references: [...message.references] } : {}),
      ...(message.delivered_at === undefined ? {} : { delivered_at: message.delivered_at }),
    }));
    this.domain = {
      taskState: this.taskState,
      plan: options.plan ?? null,
      budget: options.budget ?? null,
      approvals: {},
      actions: {},
      leases: {},
      quality: {},
      files: {},
      verifications: [],
      repairs: [],
      recovery: null,
      applyFiles: {},
    };
    this.started = this.messagesState.some((message) => message.parts.length > 0);
    this.finishEmitted =
      this.messagesState.length > 0 && this.messagesState.every((message) => message.finished && message.parts.length > 0);
    this.finishState = this.finishEmitted ? this.taskState : undefined;
  }

  static fromSnapshot(snapshot: HarnessSnapshot): HarnessEventProjector {
    return new HarnessEventProjector({
      taskId: snapshot.task_id,
      cursor: snapshot.last_event_seq,
      status: snapshot.status ?? null,
      messages: snapshot.messages,
      plan: snapshot.plan ?? null,
      budget: snapshot.budget ?? null,
    });
  }

  get lastEventSeq(): number {
    return this.cursor;
  }

  /** Rebuild only the open response in a fresh SDK reader, without replaying effects. */
  replayOpenResponse(): UIMessageChunk[] {
    const message = [...this.messagesState].reverse().find(item => item.role === 'assistant' && !item.finished);
    if (!message) return [];
    return [
      { type: 'start', messageId: message.id, messageMetadata: this.metadata(false) },
      ...message.parts.flatMap((part): UIMessageChunk[] => [
        { type: 'text-start', id: part.id },
        ...(part.text ? [{ type: 'text-delta' as const, id: part.id, delta: part.text }] : []),
        ...(part.state === 'done' ? [{ type: 'text-end' as const, id: part.id }] : []),
      ]),
    ];
  }

  get taskClosed(): boolean {
    return isTerminalTaskState(this.taskState);
  }

  get state(): HarnessTaskStateData | null {
    return this.taskState === null ? null : { state: this.taskState, reason: null, outcome: null };
  }

  /** The UI messages built from the snapshot and every event applied so far. */
  messages(): HarnessChatMessage[] {
    return this.messagesState.map((message) => ({
      id: message.id,
      role: message.role,
      parts: message.parts.map((part) => ({
        type: 'text' as const,
        text: part.text,
        state: part.state,
      })),
      metadata: {
        task_id: this.taskId,
        last_event_seq: this.cursor,
        task_state: this.taskState,
        segment_finished: message.finished,
        task_closed: this.taskClosed,
        ...(message.references ? { references: message.references } : {}),
        ...(message.delivered_at === undefined ? {} : { delivered_at: message.delivered_at }),
      },
    }));
  }

  snapshot(): ProjectorSnapshot {
    return {
      task_id: this.taskId,
      last_event_seq: this.cursor,
      task_state: this.taskState,
      task_closed: this.taskClosed,
      messages: this.messages(),
      domain: this.domain,
    };
  }

  /**
   * Apply exactly one event. Returns the chunks to enqueue, or `[]` when the
   * event was already applied. Throws `EventGapError` when a sequence is
   * missing rather than guessing at the missing text.
   */
  apply(event: HarnessEvent): UIMessageChunk[] {
    if (event.task_id !== this.taskId) {
      throw new ProjectionError('task_mismatch', `Event ${event.event_id} belongs to another task.`);
    }
    if (event.sequence <= this.cursor) return [];
    if (event.sequence !== this.cursor + 1) throw new EventGapError(this.cursor + 1, event.sequence);
    if (this.seenEventIds.has(event.event_id)) {
      throw new ProjectionError('duplicate_event_id', `Event ${event.event_id} appears twice with different sequences.`);
    }

    const payload = asPayload(event.payload);
    const previousCursor = this.cursor;
    this.cursor = event.sequence;
    try {
      const chunks = this.project(event, payload);
      this.seenEventIds.add(event.event_id);
      return chunks;
    } catch (error) {
      // A refused event leaves the cursor where it was, so the caller can
      // re-read the snapshot and try the same sequence again.
      this.cursor = previousCursor;
      throw error;
    }
  }

  private project(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    switch (event.type) {
      case 'message_started':
        return this.onMessageStarted(event, payload);
      case 'text_delta':
        return this.onTextDelta(payload);
      case 'message_finished':
        return this.onMessageFinished(event, payload);
      case 'plan_updated':
        return this.onPlan(event, payload);
      case 'approval_required':
        return this.onApproval(event, payload, 'required');
      case 'approval_decided':
        return this.onApproval(event, payload, 'decided');
      case 'action_started':
        this.onAction(event, payload);
        return [this.data(event, { kind: 'action', action: this.domain.actions[String(payload.operation_id)] })];
      case 'action_finished':
        this.onAction(event, payload);
        return [this.data(event, { kind: 'action', action: this.domain.actions[String(payload.operation_id)] })];
      case 'budget_updated':
        return this.onBudget(event, payload);
      case 'lease_state_changed':
        return this.onLease(event, payload);
      case 'selection_quality_changed':
        return this.onQuality(event, payload);
      case 'file_changed':
        return this.onFile(event, payload);
      case 'verification_finished':
        return this.onVerification(event, payload);
      case 'repair_started':
        return this.onRepair(event, payload);
      case 'task_state_changed':
        return this.onTaskState(event, payload);
      case 'apply_file_finished':
        return this.onApplyFile(event, payload);
      case 'recovery_required':
        return this.onRecovery(event, payload);
      default: {
        const unknown: never = event.type;
        throw new ProjectionError('invalid_payload', `Unknown event type: ${String(unknown)}`);
      }
    }
  }

  /**
   * End the current transport segment. This closes open text parts and emits a
   * finish chunk, but it never closes the task: a task waiting for a decision or
   * a later segment is still open.
   */
  endSegment(): UIMessageChunk[] {
    const chunks: UIMessageChunk[] = [];
    for (const message of this.messagesState) {
      for (const part of message.parts) {
        if (part.state === 'streaming' && this.started) {
          part.state = 'done';
          chunks.push({ type: 'text-end', id: part.id });
        }
      }
    }
    // A message can finish before the task reaches its next state (for example,
    // the plan is ready and the task is now `awaiting_decision`). Emit one final
    // finish with the latest state so the metadata is not stale, but never close
    // the task here.
    const stateMoved = this.finishEmitted && this.finishState !== this.taskState;
    if (this.started && (!this.finishEmitted || stateMoved)) {
      chunks.push({ type: 'finish', finishReason: 'stop', messageMetadata: this.metadata(true) });
      this.finishEmitted = true;
      this.finishState = this.taskState;
    }
    return chunks;
  }

  // ── text ──────────────────────────────────────────────────────────────────

  private onMessageStarted(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    const messageId = text(payload.message_id, 'message_id') as string;
    const partId = text(payload.part_id, 'part_id', false) ?? `${messageId}:text`;
    const existing = this.findMessage(messageId);
    if (existing !== undefined && (existing.parts.length > 0 || existing.finished)) {
      throw new ProjectionError('state_conflict', `Message ${messageId} started twice.`, { messageId });
    }
    const message = existing ?? this.addMessage(messageId, 'assistant');
    message.parts.push({ id: partId, text: '', state: 'streaming' });
    this.started = true;
    this.finishEmitted = false;
    return [
      { type: 'start', messageId, messageMetadata: this.metadata(false) },
      { type: 'text-start', id: partId },
    ];
  }

  private onTextDelta(payload: Payload): UIMessageChunk[] {
    const messageId = text(payload.message_id, 'message_id') as string;
    const partId = text(payload.part_id, 'part_id', false) ?? `${messageId}:text`;
    const delta = text(payload.delta, 'delta', false) ?? '';
    const offset = number(payload.offset, 'offset');
    if (!Number.isInteger(offset) || offset < 0) {
      throw new ProjectionError('invalid_payload', 'A text offset must be a non-negative integer.', { offset });
    }
    if (delta === '') return [];

    const message = this.findMessage(messageId);
    if (message === undefined) {
      throw new ProjectionError('message_missing', `Text for message ${messageId} arrived before it started.`, { messageId });
    }
    if (message.finished) {
      throw new ProjectionError('message_finished', `Text arrived after message ${messageId} finished.`, { messageId });
    }

    let part = message.parts.find((candidate) => candidate.id === partId);
    if (part === undefined) {
      if (offset !== 0) {
        throw new ProjectionError('offset_gap', `Text for part ${partId} starts at ${offset}, not at 0.`, {
          messageId,
          partId,
          expected: 0,
          received: offset,
        });
      }
      part = { id: partId, text: '', state: 'streaming' };
      message.parts.push(part);
      this.started = true;
      this.finishEmitted = false;
      const chunks: UIMessageChunk[] = [{ type: 'text-start', id: partId }];
      part.text += delta;
      chunks.push({ type: 'text-delta', id: partId, delta });
      return chunks;
    }

    if (part.state !== 'streaming') {
      throw new ProjectionError('message_finished', `Text for part ${partId} arrived after it ended.`, { partId });
    }

    const current = codePoints(part.text);
    if (offset > current.length) {
      throw new ProjectionError('offset_gap', `Text for part ${partId} starts at ${offset}, but only ${current.length} characters exist.`, {
        messageId,
        partId,
        expected: current.length,
        received: offset,
      });
    }
    if (offset < current.length) {
      const expected = current.slice(offset, offset + codePoints(delta).length).join('');
      if (expected === delta) return [];
      throw new ProjectionError('text_conflict', `Text at offset ${offset} of part ${partId} does not match what was already shown.`, {
        messageId,
        partId,
        offset,
      });
    }

    part.text += delta;
    return [{ type: 'text-delta', id: partId, delta }];
  }

  private onMessageFinished(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    const messageId = text(payload.message_id, 'message_id') as string;
    const onlyPart = text(payload.part_id, 'part_id', false);
    const message = this.findMessage(messageId);
    if (message === undefined) {
      throw new ProjectionError('message_missing', `Message ${messageId} finished before it started.`, { messageId });
    }
    if (message.finished && !onlyPart) {
      throw new ProjectionError('message_finished', `Message ${messageId} finished twice.`, { messageId });
    }

    const chunks: UIMessageChunk[] = [];
    for (const part of message.parts) {
      if ((onlyPart === null || part.id === onlyPart) && part.state === 'streaming') {
        part.state = 'done';
        chunks.push({ type: 'text-end', id: part.id });
      }
    }
    message.finished = onlyPart === null || message.parts.every((part) => part.state === 'done');
    if (message.finished) {
      chunks.push({
        type: 'finish',
        finishReason: finishReason(payload.finish_reason),
        messageMetadata: this.metadata(true),
      });
      this.finishEmitted = true;
      this.finishState = this.taskState;
    }
    return chunks;
  }

  // ── domain events ─────────────────────────────────────────────────────────

  private onPlan(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    const plan = planFromPayload(payload);
    this.domain.plan = plan;
    return [this.data(event, { kind: 'plan', plan })];
  }

  private onApproval(event: HarnessEvent, payload: Payload, state: 'required' | 'decided'): UIMessageChunk[] {
    const approvalId = text(payload.approval_id, 'approval_id', false) ?? event.event_id;
    const decision = text(payload.decision, 'decision', false);
    const approval: HarnessApprovalData = {
      approval_id: approvalId,
      revision: payload.revision === undefined || payload.revision === null ? null : number(payload.revision, 'revision'),
      action_hash: text(payload.action_hash, 'action_hash', false),
      tool: text(payload.tool, 'tool', false),
      state,
      ...(decision === 'approve' || decision === 'edit' || decision === 'reject' ? { decision } : {}),
      ...(Array.isArray(payload.scope) ? { scope: payload.scope.map(String) } : {}),
      summary: text(payload.summary, 'summary', false),
    };
    this.domain.approvals[approvalId] = approval;
    return [this.data(event, { kind: 'approval', approval })];
  }

  private onAction(event: HarnessEvent, payload: Payload): void {
    const operationId = text(payload.operation_id, 'operation_id') as string;
    const previous = this.domain.actions[operationId];
    const action: HarnessActionData = {
      operation_id: operationId,
      action_id: text(payload.action_id, 'action_id', false),
      tool: text(payload.tool, 'tool', false) ?? previous?.tool,
      state: oneOf<ActionState>(payload.state, 'state', ['pending', 'awaiting_approval', 'dispatching', 'running', 'succeeded', 'failed', 'denied', 'unknown']),
      summary: text(payload.summary, 'summary', false) ?? previous?.summary,
      ...(payload.receipt === undefined ? {} : { receipt: payload.receipt }),
    };
    this.domain.actions[operationId] = action;
  }

  private onBudget(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    const budget = budgetFromPayload(payload);
    this.domain.budget = budget;
    return [this.data(event, { kind: 'budget', budget })];
  }

  private onLease(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    const lease: HarnessLeaseData = {
      workspace_id: text(payload.workspace_id, 'workspace_id', false) ?? '',
      state: oneOf<LeaseState>(payload.state, 'state', ['active', 'released', 'expired', 'quarantined']),
      fencing_token: number(payload.fencing_token, 'fencing_token', 0),
      kind: text(payload.kind, 'kind', false),
      operation_id: text(payload.operation_id, 'operation_id', false),
    };
    this.domain.leases[lease.workspace_id] = lease;
    return [this.data(event, { kind: 'lease', lease })];
  }

  private onQuality(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    const quality: HarnessQualityData = {
      selection_id: text(payload.selection_id, 'selection_id') as string,
      quality_status: oneOf<QualityStatus>(payload.quality_status, 'quality_status', ['verified_snapshot', 'not_verified', 'stale', 'failed']),
      target_kind: oneOf<VerificationTarget>(payload.target_kind, 'target_kind', ['working_copy', 'apply_candidate']),
      candidate_manifest_hash: text(payload.candidate_manifest_hash, 'candidate_manifest_hash', false),
      ...(Array.isArray(payload.check_refs) ? { check_refs: payload.check_refs.map(String) } : {}),
    };
    this.domain.quality[quality.selection_id] = quality;
    return [this.data(event, { kind: 'quality', quality })];
  }

  private onFile(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    const file: HarnessFileData = {
      file_id: text(payload.file_id, 'file_id') as string,
      path: text(payload.path, 'path') as string,
      change_kind: oneOf<FileChangeKind>(payload.change_kind, 'change_kind', ['added', 'modified', 'deleted', 'binary', 'unsupported']),
      hash: text(payload.hash, 'hash', false),
      ...(payload.size === undefined || payload.size === null ? {} : { size: number(payload.size, 'size') }),
    };
    this.domain.files[file.file_id] = file;
    return [this.data(event, { kind: 'file', file })];
  }

  private onVerification(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    const verification: HarnessVerificationData = {
      target_kind: oneOf<VerificationTarget>(payload.target_kind, 'target_kind', ['working_copy', 'apply_candidate']),
      outcome: oneOf<VerificationOutcome>(payload.outcome, 'outcome', ['passed', 'failed', 'skipped', 'not_configured', 'stopped', 'timed_out']),
      selection_id: text(payload.selection_id, 'selection_id', false),
      candidate_manifest_hash: text(payload.candidate_manifest_hash, 'candidate_manifest_hash', false),
      ...(Array.isArray(payload.check_refs) ? { check_refs: payload.check_refs.map(String) } : {}),
    };
    this.domain.verifications.push(verification);
    return [this.data(event, { kind: 'verification', verification })];
  }

  private onRepair(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    const repair: HarnessRepairData = {
      repair_index: number(payload.repair_index, 'repair_index', this.domain.repairs.length + 1),
      reason: text(payload.reason, 'reason', false),
    };
    this.domain.repairs.push(repair);
    return [this.data(event, { kind: 'repair', repair })];
  }

  private onTaskState(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    const state = oneOf<TaskState>(payload.state, 'state', [
      'draft',
      'queued',
      'planning',
      'awaiting_plan',
      'executing',
      'awaiting_action',
      'verifying',
      'repairing',
      'awaiting_decision',
      'paused_limit',
      'stopping',
      'paused',
      'recovery_required',
      'closed',
      'failed',
      'cancelled',
    ]);
    this.taskState = state;
    this.domain.taskState = state;
    const task: HarnessTaskStateData = {
      state,
      ...(payload.revision===undefined?{}:{revision:number(payload.revision,'revision')}),
      reason: text(payload.reason, 'reason', false),
      outcome: text(payload.outcome, 'outcome', false),
    };
    return [this.data(event, { kind: 'task-state', task })];
  }

  private onApplyFile(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    const file: HarnessApplyFileData = {
      file_id: text(payload.file_id, 'file_id') as string,
      state: text(payload.state, 'state') as string,
      operation_id: text(payload.operation_id, 'operation_id') as string,
    };
    this.domain.applyFiles[file.file_id] = file;
    return [this.data(event, { kind: 'apply-file', file })];
  }

  private onRecovery(event: HarnessEvent, payload: Payload): UIMessageChunk[] {
    const recovery: HarnessRecoveryData = {
      operation_id: text(payload.operation_id, 'operation_id', false),
      reason: text(payload.reason, 'reason') as string,
      reconcile_required: payload.reconcile_required !== false,
    };
    this.domain.recovery = recovery;
    return [this.data(event, { kind: 'recovery', recovery })];
  }

  // ── helpers ───────────────────────────────────────────────────────────────

  private addMessage(id: string, role: CanonicalMessage['role']): MessageState {
    const message: MessageState = { id, role, parts: [], finished: false };
    this.messagesState.push(message);
    return message;
  }

  private findMessage(id: string): MessageState | undefined {
    return this.messagesState.find((message) => message.id === id);
  }

  private metadata(segmentFinished: boolean): HarnessMessageMetadata {
    return {
      task_id: this.taskId,
      last_event_seq: this.cursor,
      task_state: this.taskState,
      segment_finished: segmentFinished,
      task_closed: this.taskClosed,
    };
  }

  private data(event: HarnessEvent, part: { kind: string } & Record<string, unknown>): UIMessageChunk {
    const data = {
      task_id: this.taskId,
      sequence: event.sequence,
      event_id: event.event_id,
      run_id: event.run_id,
      occurred_at: event.occurred_at,
      ...part,
    } as HarnessDataPart;
    return { type: 'data-harness', id: event.event_id, data, transient: false };
  }
}

// A named alias keeps imports in `transport.ts` and tests readable.
export type EventTypeName = EventType;
