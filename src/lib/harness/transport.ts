/**
 * The custom AI SDK transport for the local task API.
 *
 * There is exactly one transport, not `DefaultChatTransport` plus a second
 * LangGraph UI transport. `sendMessages` sends the *product* command (create a
 * task or steer it) and then reads the durable journal. It never calls a model
 * itself, never touches a provider key, and never runs a tool.
 *
 * Reconnecting is a read: it starts at the cursor and replays events from the
 * journal. It does not create a task, re-send a command or rerun a tool.
 * Cancelling the consumer closes the local reader only; stopping the runtime is
 * a separate product action (`HarnessClient.stopTask`), so a tab that closes or
 * a React unmount cannot silently kill a task.
 */

import type { ChatTransport, UIMessageChunk } from 'ai';

import type { HarnessClient } from './client';
import type {
  HarnessChatMessage,
  HarnessDomainState,
  HarnessEvent,
  HarnessMessageMetadata,
  HarnessPlanData,
  HarnessSnapshot,
} from './projection';
import { HarnessEventProjector } from './projection';
import type { HarnessTaskSnapshot, SendMessageInput, StartTaskInput, StartTaskResult } from './client';
import type { TaskState } from './schema';

const TASK_ID = /^task_[A-Za-z0-9]+$/;

/** States in which the journal may still grow without a new user message. */
const ACTIVE_STATES: ReadonlySet<TaskState> = new Set<TaskState>([
  'stopping',
  'queued',
  'planning',
  'executing',
  'verifying',
  'repairing',
]);

export function isTaskId(value: string | null | undefined): value is string {
  return typeof value === 'string' && TASK_ID.test(value);
}

export type HarnessAccessMode = 'ask' | 'grant' | 'auto';

/**
 * Choices that shape the next command. They are deliberately mutable: the
 * composer owns the references and the create form owns the mode, while the AI
 * SDK calls one long-lived transport.
 */
export type HarnessTaskControls = {
  mode?: HarnessAccessMode;
  readOnly?: boolean;
  modelId?: string;
  workspaceId?: string;
  references?: string[];
};

/** The slice of `HarnessClient` the transport needs; a fake is easy in tests. */
export type HarnessTransportClient = Pick<
  HarnessClient,
  'startTask' | 'sendMessage' | 'proposePlan' | 'continueTask' | 'streamEvents' | 'task'
> & {
  stopTask?: HarnessClient['stopTask'];
};

export type HarnessTransportOptions = {
  client: HarnessTransportClient;
  /** Existing task this chat belongs to. A new task is created when omitted. */
  taskId?: string;
  /** Where the UI last stopped reading. Without it, an existing task uses its snapshot cursor. */
  cursor?: number;
  /** A reloaded snapshot; required to continue a partially streamed message without duplicates. */
  snapshot?: HarnessSnapshot;
  /** Injectable for deterministic idempotency keys in tests. */
  idFactory?: () => string;
  controls?: HarnessTaskControls;
  /** Called after `POST /tasks` so the page can route to the new task. */
  onTaskCreated?: (task: HarnessTaskSnapshot) => void;
  onMessageAccepted?: (messageId: string) => void;
};

export type HarnessTransportErrorCode =
  | 'closed'
  | 'missing_user_message'
  | 'no_task'
  | 'invalid_message'
  | 'plan_failed';

export class HarnessTransportError extends Error {
  constructor(
    readonly code: HarnessTransportErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'HarnessTransportError';
  }
}

function isAbortError(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { name?: unknown }).name === 'AbortError';
}

function isActiveState(state: TaskState | null | undefined): boolean {
  return state != null && ACTIVE_STATES.has(state);
}

/** Map a task response to the hydration snapshot the projector understands. */
export function snapshotFromTask(task: HarnessTaskSnapshot): HarnessSnapshot {
  return {
    task_id: task.id,
    last_event_seq: task.last_event_seq ?? 0,
    status: task.status,
    messages: task.messages,
    plan: task.plan ?? null,
    budget: task.budget ?? null,
  };
}

function lastUserMessage(messages: HarnessChatMessage[]): HarnessChatMessage | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === 'user') return messages[index];
  }
  return undefined;
}

function messageText(message: HarnessChatMessage | undefined): string {
  if (message === undefined) return '';
  const parts: string[] = [];
  for (const part of message.parts) {
    if (part.type === 'text') parts.push(part.text);
  }
  return parts.join('\n').trim();
}

export class HarnessChatTransport implements ChatTransport<HarnessChatMessage> {
  /**
   * Journal reads continue from the cursor. The local open response is replayed
   * first so the SDK can rebuild its text-part map after reload/disconnection.
   */
  readonly resumeStreamIsReplay = true;

  private readonly client: HarnessTransportClient;
  private readonly idFactory: () => string;
  private readonly onTaskCreated?: (task: HarnessTaskSnapshot) => void;
  private readonly onMessageAccepted?: (messageId: string) => void;
  private accepted = new Set<string>();
  private pendingMessageId: string | undefined;
  private controls: HarnessTaskControls;
  private taskId: string | undefined;
  private cursor: number;
  private revision: number | undefined;
  private projector: HarnessEventProjector | null;
  private active: AbortController | null = null;
  private closed = false;
  private lastPlan: HarnessPlanData | null = null;

  constructor(options: HarnessTransportOptions) {
    this.client = options.client;
    this.idFactory = options.idFactory ?? (() => globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2));
    this.controls = { ...options.controls };
    this.onTaskCreated = options.onTaskCreated;
    this.onMessageAccepted = options.onMessageAccepted;
    this.taskId = options.taskId ?? options.snapshot?.task_id;
    this.cursor = options.cursor ?? options.snapshot?.last_event_seq ?? 0;
    this.lastPlan = options.snapshot?.plan ?? null;
    this.projector =
      options.snapshot !== undefined
        ? HarnessEventProjector.fromSnapshot(options.snapshot)
        : options.taskId !== undefined && options.cursor !== undefined
          ? new HarnessEventProjector({ taskId: options.taskId, cursor: options.cursor })
          : null;
  }

  /** Change what the next command carries (references, mode, read-only). */
  setControls(controls: HarnessTaskControls): void {
    this.controls = { ...this.controls, ...controls };
  }

  get controlsSnapshot(): HarnessTaskControls {
    return { ...this.controls };
  }

  /** The projector's latest domain state, for the inspector. */
  currentDomain(): HarnessDomainState | null {
    return this.projector?.snapshot().domain ?? null;
  }

  /** The last task state the journal reported, or the hydrated snapshot state. */
  currentStatus(): TaskState | null {
    return this.projector?.snapshot().task_state ?? null;
  }

  get currentTaskId(): string | undefined {
    return this.taskId;
  }

  get lastEventSeq(): number {
    return this.projector?.lastEventSeq ?? this.cursor;
  }

  /**
   * Restore messages from a canonical snapshot and continue from its cursor.
   * This is local state only; it never sends a command or asks the backend to
   * replay a tool.
   */
  hydrate(snapshot: HarnessSnapshot): HarnessChatMessage[] {
    this.projector = HarnessEventProjector.fromSnapshot(snapshot);
    this.taskId = snapshot.task_id;
    this.cursor = snapshot.last_event_seq;
    this.lastPlan = snapshot.plan ?? null;
    return this.projector.messages();
  }

  async sendMessages(options: {
    trigger: 'submit-message' | 'regenerate-message';
    chatId: string;
    messageId: string | undefined;
    messages: HarnessChatMessage[];
    abortSignal: AbortSignal | undefined;
  }): Promise<ReadableStream<UIMessageChunk>> {
    this.assertOpen();

    if (options.trigger === 'submit-message') {
      const user = lastUserMessage(options.messages);
      const prompt = messageText(user);
      if (prompt === '') {
        throw new HarnessTransportError('missing_user_message', 'A task needs a text prompt.');
      }
      this.pendingMessageId = user?.id;
      const key = this.idempotencyKey(options.chatId, user);
      const references = this.controls.references ?? [];

      if (user?.id && this.accepted.has(user.id)) {
        this.onMessageAccepted?.(user.id);
      } else if (this.taskId === undefined) {
        const started: StartTaskResult = await this.client.startTask({
          prompt,
          ...(this.controls.mode === undefined ? {} : { mode: this.controls.mode }),
          ...(this.controls.readOnly === undefined ? {} : { read_only: this.controls.readOnly }),
          ...(this.controls.modelId === undefined ? {} : { model_id: this.controls.modelId }),
          ...(this.controls.workspaceId === undefined ? {} : { workspace_id: this.controls.workspaceId }),
          ...(references.length === 0 ? {} : { references }),
          ...(key === undefined ? {} : { idempotency_key: key }),
        });
        this.taskId = started.task.id;
        this.cursor = 0;
        this.revision = started.task.revision;
        this.lastPlan = started.task.plan ?? null;
        this.projector = new HarnessEventProjector({ taskId: this.taskId, cursor: 0, status: started.task.status });
        this.onTaskCreated?.(started.task);
        this.acceptMessage();

        // Creation is pure. A planning pass is a separate, explicit product
        // action; the user already asked for it by sending the first message.
        await this.propose(this.taskId, undefined, references, key);
      } else {
        await this.ensureProjector();
        await this.command(this.taskId, prompt, references, key);
      }
    }

    // Regeneration is a replay, not a second model call. The command went out
    // once; a retry reuses its idempotency key at the API layer.
    if (this.taskId === undefined && isTaskId(options.chatId)) this.taskId = options.chatId;
    if (this.taskId === undefined) {
      throw new HarnessTransportError('no_task', 'Reconnect needs a task id; no command was sent.');
    }
    await this.ensureProjector();
    return this.openStream(this.taskId, options.abortSignal);
  }

  /**
   * Route one submit to the product action that matches the task state:
   *
   * - a waiting plan gets a correction pass, stored before the pass starts;
   * - an active task gets durable steering for the next model turn;
   * - a paused task with the same approved revision gets the message, then an
   *   explicit continuation. Approval and execution stay separate calls.
   */
  private async command(taskId: string, text: string, references: string[], key: string | undefined): Promise<void> {
    const snapshot = this.projector?.snapshot();
    const state = snapshot?.task_state ?? null;
    const plan = snapshot?.domain.plan ?? this.lastPlan;
    const suffix = key === undefined ? undefined : (part: string) => `${key}:${part}`;

    if (state === 'awaiting_plan' || state === 'closed') {
      await this.propose(taskId, text, references, suffix?.(`plan`));
      return;
    }

    if ((state === 'queued' || state === 'draft') && plan === null) {
      await this.propose(taskId, text, references, suffix?.(`plan`));
      return;
    }

    const input: SendMessageInput = {
      text,
      ...(references.length === 0 ? {} : { references }),
      ...(key === undefined ? {} : { idempotency_key: key }),
    };
    await this.client.sendMessage(taskId, input);
    this.acceptMessage();

    const approved = plan !== null && plan.revision !== null && plan.approved_revision === plan.revision;
    if (state === 'paused' && approved) {
      await this.client.continueTask(taskId, {
        expected_plan_revision: plan.revision ?? undefined,
        ...(suffix === undefined ? {} : { idempotency_key: suffix('continue') }),
      });
    }
  }

  private async propose(taskId: string, instruction: string | undefined, references: string[], key: string | undefined): Promise<void> {
    try {
      const proposed = await this.client.proposePlan(taskId, {
        ...(instruction === undefined ? {} : { instruction }),
        ...(references.length === 0 ? {} : { references }),
        ...(key === undefined ? {} : { idempotency_key: key }),
      });
      if (instruction && proposed.message) this.acceptMessage();
      this.revision = proposed.task.revision;
      this.lastPlan = proposed.plan ?? this.lastPlan;
    } catch (error) {
      // The task exists; the page shows the refusal and offers a retry.
      if (error instanceof Error) throw error;
      throw new HarnessTransportError('plan_failed', 'The planning pass could not start.');
    }
  }

  /**
   * Resume from the cursor. This performs reads only: `GET /tasks/{id}` for the
   * baseline and `GET /tasks/{id}/events` for the journal. It returns `null`
   * when there is nothing to resume, which is the SDK's contract for "no active
   * stream".
   */
  async reconnectToStream(options: { chatId: string; abortSignal?: AbortSignal }): Promise<ReadableStream<UIMessageChunk> | null> {
    if (this.closed) return null;
    if (this.taskId === undefined && isTaskId(options.chatId)) this.taskId = options.chatId;
    if (this.taskId === undefined) return null;

    await this.ensureProjector();
    const snapshot = await this.client.task(this.taskId);
    this.revision = snapshot.revision;
    this.lastPlan = snapshot.plan ?? this.lastPlan;
    const atEnd = snapshot.last_event_seq <= this.lastEventSeq;
    if (atEnd && !isActiveState(snapshot.status)) return null;
    return this.openStream(this.taskId, options.abortSignal);
  }

  /**
   * Release this transport. It aborts local reads and never stops the runtime:
   * the Stop button calls `HarnessClient.stopTask` explicitly, with its own
   * receipt, so a closed window cannot be confused with a stopped task.
   */
  attach(): void { this.closed = false; }

  close(): void {
    this.closed = true;
    this.active?.abort();
    this.active = null;
  }

  // ── internals ─────────────────────────────────────────────────────────────

  private acceptMessage(): void {
    if (!this.pendingMessageId) return;
    this.accepted.add(this.pendingMessageId);
    this.onMessageAccepted?.(this.pendingMessageId);
  }

  private assertOpen(): void {
    if (this.closed) throw new HarnessTransportError('closed', 'This transport was closed.');
  }

  /**
   * An existing task needs a baseline cursor before it is touched. Prefer the
   * caller's hydrated snapshot; otherwise read the task and start at its
   * `last_event_seq`, so old text is never re-emitted into a fresh chat.
   */
  private async ensureProjector(): Promise<void> {
    if (this.projector !== null || this.taskId === undefined) return;
    const snapshot = await this.client.task(this.taskId);
    this.revision = snapshot.revision;
    this.hydrate(snapshotFromTask(snapshot));
  }

  private idempotencyKey(chatId: string, user: HarnessChatMessage | undefined): string {
    const messageId = user?.id ?? this.idFactory();
    return `chat:${chatId}:${messageId}`;
  }

  private openStream(taskId: string, abortSignal: AbortSignal | undefined): ReadableStream<UIMessageChunk> {
    const projector = this.projector ?? new HarnessEventProjector({ taskId, cursor: this.cursor });
    this.projector = projector;
    this.taskId = taskId;

    this.active?.abort();
    const controller = new AbortController();
    const forwardAbort = () => controller.abort();
    if (abortSignal !== undefined) {
      if (abortSignal.aborted) controller.abort();
      else abortSignal.addEventListener('abort', forwardAbort, { once: true });
    }
    this.active = controller;
    let cancelled = false;
    const client = this.client;

    return new ReadableStream<UIMessageChunk>({
      start: async (stream) => {
        try {
          // Fresh SDK readers have no active text-part map, even after setMessages.
          // Replay the open response from local projection; GET still uses the cursor.
          for (const chunk of projector.replayOpenResponse()) stream.enqueue(chunk);
          for await (const event of client.streamEvents(taskId, {
            afterSeq: projector.lastEventSeq,
            signal: controller.signal,
          })) {
            if (cancelled) return;
            for (const chunk of projector.apply(event)) stream.enqueue(chunk);
            this.cursor = projector.lastEventSeq;
          }
          if (cancelled) return;
          for (const chunk of projector.endSegment()) stream.enqueue(chunk);
          this.cursor = projector.lastEventSeq;
          stream.close();
        } catch (error) {
          if (!cancelled) {
            if (isAbortError(error)) stream.close();
            else stream.error(error);
          }
        } finally {
          if (abortSignal !== undefined) abortSignal.removeEventListener('abort', forwardAbort);
          if (this.active === controller) this.active = null;
        }
      },
      cancel: () => {
        // Consumer cancelled: stop the reader, not the task.
        cancelled = true;
        this.cursor = projector.lastEventSeq;
        controller.abort();
      },
    });
  }
}

/** Re-export the metadata type so UI code does not import `projection` directly. */
export type { HarnessMessageMetadata };
