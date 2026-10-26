'use client';

import { useChat } from '@ai-sdk/react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { createBrowserClient } from '@/lib/harness/browser';
import {
  HarnessRequestError,
  type HarnessMessage,
  type HarnessTaskSnapshot,
  type PlanStepInput,
} from '@/lib/harness/client';
import type {
  CanonicalMessage,
  HarnessChatMessage,
  HarnessDataPart,
  HarnessDomainState,
  HarnessEvent,
  HarnessMessageMetadata,
  HarnessPlanData,
} from '@/lib/harness/projection';
import { HarnessEventProjector, isTerminalTaskState } from '@/lib/harness/projection';
import type { TaskState } from '@/lib/harness/schema';
import { HarnessChatTransport } from '@/lib/harness/transport';

import { applyActivity, applyData, domainFromJournal, emptyDomain, type ActivityItem } from './domain';
import { isActiveTaskState } from './status';

export type PlanEdit = {
  steps: PlanStepInput[];
  scope: string[];
  checks: string[];
};

type Phase = 'empty' | 'loading' | 'ready' | 'error';
type Connection = 'idle' | 'live' | 'reconnecting' | 'offline';

function payloadOf(event: HarnessEvent): Record<string, unknown> {
  return (event.payload ?? {}) as Record<string, unknown>;
}

/** The absolute start time of every assistant message in the journal. */
function messageStarts(events: HarnessEvent[]): Map<string, number> {
  const starts = new Map<string, number>();
  for (const event of events) {
    if (event.type !== 'message_started') continue;
    const id = payloadOf(event).message_id;
    if (typeof id === 'string' && !starts.has(id)) starts.set(id, event.occurred_at);
  }
  return starts;
}

/** Rebuild assistant text from the journal with a throwaway projector. */
function replayAssistant(taskId: string, status: TaskState | null, events: HarnessEvent[]): HarnessChatMessage[] {
  const projector = new HarnessEventProjector({ taskId, cursor: 0, status });
  for (const event of events) projector.apply(event);
  return projector.messages();
}

function canonical(messages: HarnessChatMessage[]): CanonicalMessage[] {
  return messages.map((message) => {
    let textIndex = 0;
    return {
      id: message.id,
      role: message.role,
      parts: message.parts.flatMap((part) => {
        if (part.type !== 'text') return [];
        const id = `${message.id}:${textIndex === 0 ? 'text' : textIndex}`;
        textIndex += 1;
        return [{ id, text: part.text, state: part.state }];
      }),
      ...(message.metadata?.references ? { references: [...message.metadata.references] } : {}),
      ...(message.metadata?.delivered_at === undefined ? {} : { delivered_at: message.metadata.delivered_at }),
    };
  });
}

function userMessage(message: HarnessMessage): HarnessChatMessage {
  const parts = message.parts
    .filter((part) => part.text.length > 0)
    .map((part) => ({ type: 'text' as const, text: part.text, state: 'done' as const }));
  return {
    id: message.id,
    role: 'user',
    parts,
    metadata: {
      task_id: message.task_id ?? '',
      last_event_seq: 0,
      task_state: null,
      segment_finished: true,
      task_closed: false,
      ...(message.references && message.references.length > 0 ? { references: [...message.references] } : {}),
      ...(message.delivered_at === undefined ? {} : { delivered_at: message.delivered_at }),
    },
  };
}

/**
 * Merge durable user messages with journal-rebuilt assistant messages.
 *
 * They live in different places on purpose: text the user typed is a product
 * message, text the model produced is an event. Sorting by the time each one
 * started keeps a reload identical to what was on screen.
 */
function mergeTranscript(
  taskId: string,
  snapshot: HarnessTaskSnapshot,
  events: HarnessEvent[],
  assistant: HarnessChatMessage[],
): HarnessChatMessage[] {
  const starts = messageStarts(events);
  const users = (snapshot.messages ?? [])
    .filter((message) => message.role === 'user')
    .map((message) => ({ at: message.created_at ?? 0, order: message.offset ?? 0, kind: 0, message: userMessage(message) }));
  const agents = assistant.map((message, index) => ({
    at: starts.get(message.id) ?? Number.MAX_SAFE_INTEGER,
    order: index,
    kind: 1,
    message,
  }));
  return [...users, ...agents]
    .sort((a, b) => a.at - b.at || a.kind - b.kind || a.order - b.order)
    .map((entry) => entry.message);
}

function planErrorText(error: unknown): string {
  if (error instanceof HarnessRequestError) {
    if (error.code === 'selection_stale') return 'برنامه تغییر کرده؛ بازبینی کنید.';
    if (error.code === 'action_not_approved') return 'برنامهٔ تأییدشده معتبر نیست؛ دوباره بازبینی کنید.';
    if (error.code === 'conflict') return 'این کار دیگر در حال اجرا نیست.';
    return error.message;
  }
  if (error instanceof Error && error.message) return error.message;
  return 'انجام این کار ممکن نشد.';
}

export type TaskChatOptions = {
  /** The open task; `undefined` is the home screen, which does not own a live chat. */
  taskId?: string;
};

/**
 * One task's live product state.
 *
 * There is one loop and one journal. This hook hydrates from the durable store,
 * follows the journal with the AI SDK transport, and turns canonical domain
 * events into the inspector. It never invents progress, never starts a run on a
 * reload, and never treats model text as permission state.
 */
export function useTaskChat({ taskId }: TaskChatOptions = {}) {
  const client = useMemo(() => createBrowserClient(), []);
  const [phase, setPhase] = useState<Phase>(taskId ? 'loading' : 'empty');
  const [connection, setConnection] = useState<Connection>('idle');
  const [snapshot, setSnapshot] = useState<HarnessTaskSnapshot | null>(null);
  const [domain, setDomain] = useState<HarnessDomainState>(() => emptyDomain());
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [references, setReferencesState] = useState<string[]>([]);
  const [steeringMessages, setSteeringMessages] = useState<HarnessChatMessage[]>([]);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [planStale, setPlanStale] = useState(false);
  const [planBusy, setPlanBusy] = useState<'save' | 'approve' | 'reject' | 'continue' | null>(null);
  const pendingSend = useRef<{ id: string; text: string; references: string[] } | null>(null);
  const receipt = useRef<((id: string) => void) | null>(null);
  const hydratedFor = useRef<string | null>(null);
  const autoProposed = useRef<string | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);
  const canonicalRevision = useRef(0);
  const acceptTask = useCallback((next: HarnessTaskSnapshot) => {
    if (!mounted.current || (next.revision ?? 0) < canonicalRevision.current) return;
    canonicalRevision.current = next.revision ?? 0;
    setSnapshot(next);
    setDomain(current => ({...current,taskState:next.status,plan:next.plan ?? current.plan}));
  }, []);

  const transport = useMemo(
    () => new HarnessChatTransport({ client, taskId, cursor: taskId ? undefined : 0, onMessageAccepted: (id) => receipt.current?.(id) }),
    [client, taskId],
  );

  const onData = useCallback((part: { type: string; data?: unknown }) => {
    if (part.type !== 'data-harness') return;
    const data = part.data as HarnessDataPart;
    if (!data || typeof data.kind !== 'string') return;
    if(data.kind==='task-state' && data.task.revision!==undefined){
      if(data.task.revision<canonicalRevision.current)return;
      canonicalRevision.current=data.task.revision;
      setSnapshot(current=>current?{...current,status:data.task.state,revision:data.task.revision,outcome:data.task.outcome??current.outcome}:current);
    }
    setDomain((current) => applyData(current, data));
    setActivity((current) => applyActivity(current, data));
  }, []);

  const onError = useCallback(() => {
    setConnection('reconnecting');
  }, []);

  const {
    messages,
    setMessages,
    sendMessage,
    resumeStream,
    status: chatStatus,
    error: chatError,
    clearError,
  } = useChat<HarnessChatMessage>({
    id: taskId ? `task:${taskId}` : 'new-task',
    transport,
    throttle: 50,
    onData,
    onError,
  });

  useEffect(() => {
    mounted.current = true;
    transport.attach();
    return () => {
      mounted.current = false;
      transport.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [transport]);

  const syncMeta = useCallback(async () => {
    if (!taskId) return null;
    const next = await client.task(taskId);
    if (!mounted.current) return null;
    setSnapshot(next);
    return next;
  }, [client, taskId]);

  /** Hydrate the transcript and the inspector from the durable store. */
  const hydrate = useCallback(async () => {
    if (!taskId) {
      setPhase('empty');
      return;
    }
    setPhase('loading');
    setCommandError(null);
    try {
      const next = await client.task(taskId);
      const journal = await client.journal(taskId);
      if (!mounted.current) return;
      const assistant = replayAssistant(taskId, next.status, journal.items);
      const merged = mergeTranscript(taskId, next, journal.items, assistant);
      transport.hydrate({
        task_id: taskId,
        last_event_seq: journal.items.at(-1)?.sequence ?? 0,
        status: next.status,
        messages: canonical(assistant),
        plan: next.plan ?? null,
        budget: next.budget ?? null,
      });
      setMessages(merged);
      setSteeringMessages([]);
      setSnapshot(next);
      canonicalRevision.current = next.revision ?? 0;
      const hydrated = domainFromJournal(taskId, next.status, journal.items, {
        plan: next.plan ?? null,
        budget: next.budget ?? null,
      });
      setDomain(hydrated.domain);
      setActivity(hydrated.activity);
      setPlanStale(false);
      setPhase('ready');
      setConnection(isActiveTaskState(next.status) ? 'live' : 'idle');
    } catch (error) {
      if (!mounted.current) return;
      setCommandError(planErrorText(error));
      setPhase('error');
      setConnection('offline');
    }
  }, [client, taskId, transport, setMessages]);

  useEffect(() => {
    if (!taskId || hydratedFor.current === taskId) return;
    hydratedFor.current = taskId;
    hydrate().catch(() => {});
  }, [taskId, hydrate]);

  const status: TaskState | null = domain.taskState ?? snapshot?.status ?? null;
  const plan: HarnessPlanData | null = domain.plan ?? snapshot?.plan ?? null;
  const approved = plan?.revision != null && plan.approved_revision === plan.revision;

  useEffect(() => {
    if (chatStatus === 'streaming') setConnection(isActiveTaskState(status) ? 'live' : 'idle');
  }, [chatStatus, status]);

  const follow = useCallback(async () => {
    try {
      await resumeStream();
    } catch {
      if (mounted.current) setConnection('reconnecting');
    }
  }, [resumeStream]);

  /**
   * A newly created task has no plan yet. P02 only creates it; this is the
   * first explicit planning pass, and it is a read-only product action.
   */
  useEffect(() => {
    if (!taskId || phase !== 'ready') return;
    if (status !== 'queued' || plan !== null) return;
    if (autoProposed.current === taskId) return;
    autoProposed.current = taskId;
    setConnection('live');
    client
      .proposePlan(taskId, { idempotency_key: `auto-plan:${taskId}` })
      .then((result) => {
        if (!mounted.current) return;
        setSnapshot(result.task);
        setDomain((current) => ({
          ...current,
          taskState: result.task.status,
          plan: result.plan ?? current.plan,
        }));
        return follow();
      })
      .catch((error) => {
        if (!mounted.current) return;
        setCommandError(planErrorText(error));
        setConnection('offline');
      });
  }, [client, follow, phase, plan, status, taskId]);

  /** Follow the journal only while the task is actually active. A reload is a read. */
  useEffect(() => {
    if (!taskId || phase !== 'ready') return;
    if (status === 'queued' && plan === null) return;
    if (isActiveTaskState(status)) {
      setConnection('live');
      follow().catch(() => {});
    } else if (isTerminalTaskState(status)) {
      setConnection('idle');
    }
  }, [follow, phase, plan, status, taskId]);

  // A dropped SSE is a reconnect, never a new run. Keep trying while the task
  // is active; the banner says the state is being restored.
  useEffect(() => {
    if (chatError == null) return;
    if (!isActiveTaskState(status)) {
      setConnection('idle');
      return;
    }
    setConnection('reconnecting');
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    reconnectTimer.current = setTimeout(() => {
      clearError();
      follow().catch(() => {});
    }, 1500);
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [chatError, clearError, follow, status]);

  const setReferences = useCallback(
    (next: string[]) => {
      const value = [...new Set(next.filter(Boolean))];
      setReferencesState(value);
      transport.setControls({ references: value });
    },
    [transport],
  );

  const addReference = useCallback(
    (path: string) => {
      setReferences([...references, path]);
    },
    [references, setReferences],
  );

  const removeReference = useCallback(
    (path: string) => {
      setReferences(references.filter((item) => item !== path));
    },
    [references, setReferences],
  );

  /**
   * Send one message through the product route that matches the current state.
   * Returns whether the durable command was accepted, so the composer clears
   * the draft only when the message exists in the store. A failed send re-reads
   * the task instead of leaving an optimistic bubble that nobody received.
   */
  const send = useCallback(
    async (text: string): Promise<boolean> => {
      const trimmed = text.trim();
      if (!trimmed) return false;
      const attached = references;
      transport.setControls({ references: attached });
      setCommandError(null);
      setConnection(isActiveTaskState(status) ? 'live' : 'idle');
      const previous = pendingSend.current;
      const attempt = previous && previous.text === trimmed && JSON.stringify(previous.references) === JSON.stringify(attached)
        ? previous : { id: crypto.randomUUID(), text: trimmed, references: [...attached] };
      pendingSend.current = attempt;
      clearError();
      // Steering is a product write alongside the existing subscriber. Starting
      // another SDK request here would interrupt the current assistant message.
      if (taskId && isActiveTaskState(status)) {
        try {
          const result = await client.sendMessage(taskId, {
            text: trimmed, references: attached,
            idempotency_key: `chat:task:${taskId}:${attempt.id}`,
          });
          const message = userMessage(result.message);
          setSteeringMessages(current => current.some(item => item.id === message.id) ? current : [...current, message]);
          pendingSend.current = null;
          setReferencesState([]);
          transport.setControls({ references: [] });
          return true;
        } catch (error) {
          setCommandError(planErrorText(error));
          return false;
        }
      }
      // SDK handles stream errors internally. Receipt is the product POST,
      // independent of stream completion; an interrupted accepted send is not retried.
      const accepted = await new Promise<boolean>((resolve) => {
        let confirmed = false;
        receipt.current = (id) => {
          if (id !== attempt.id) return;
          confirmed = true;
          resolve(true);
        };
        void sendMessage({ id: attempt.id, role: 'user', parts: [{ type: 'text', text: trimmed }], metadata: {
          task_id: taskId ?? '', last_event_seq: transport.lastEventSeq,
          task_state: status, segment_finished: true, task_closed: false,
          ...(attached.length > 0 ? { references: attached } : {}),
        } satisfies HarnessMessageMetadata }).then(() => {
          if (!confirmed) resolve(false);
        }, () => { if (!confirmed) resolve(false); });
      });
      receipt.current = null;
      if (accepted) {
        pendingSend.current = null;
        setReferencesState([]);
        transport.setControls({ references: [] });
        return true;
      }
      await hydrate().catch(() => {});
      setCommandError('پیام هنوز تأیید ذخیره ندارد؛ متن حفظ شد. دوباره تلاش کنید.');
      return false;
    },
    [clearError, client, hydrate, references, sendMessage, status, taskId, transport],
  );

  const savePlan = useCallback(
    async (edit: PlanEdit): Promise<HarnessPlanData | null> => {
      if (!taskId || plan?.revision == null) return null;
      setPlanBusy('save');
      setCommandError(null);
      try {
        const result = await client.updatePlan(taskId, {
          expected_revision: plan.revision,
          steps: edit.steps,
          scope: edit.scope,
          checks: edit.checks,
        });
        if (mounted.current) {
          setSnapshot((current) => (current ? { ...current, plan: result.plan, revision: result.task.revision } : result.task));
          setDomain((current) => ({ ...current, plan: result.plan }));
          setPlanStale(false);
        }
        return result.plan;
      } catch (error) {
        if (mounted.current) {
          setCommandError(planErrorText(error));
          if (error instanceof HarnessRequestError && error.code === 'selection_stale') {
            setPlanStale(true);
            await syncMeta().catch(() => {});
          }
        }
        return null;
      } finally {
        if (mounted.current) setPlanBusy(null);
      }
    },
    [client, plan?.revision, syncMeta, taskId],
  );

  /**
   * Save first, then approve exactly the revision that was saved, then open the
   * execution segment. The three calls are intentionally separate; a stale
   * revision never executes.
   */
  const approveAndContinue = useCallback(
    async (edit?: PlanEdit): Promise<boolean> => {
      if (!taskId || plan?.revision == null) return false;
      setCommandError(null);
      setPlanBusy('approve');
      try {
        let revision = plan.revision;
        if (edit !== undefined) {
          const saved = await savePlan(edit);
          if (saved?.revision == null) return false;
          revision = saved.revision;
          setPlanBusy('approve');
        }
        const decided = await client.decidePlan(taskId, {
          decision: 'approve',
          expected_revision: revision,
          idempotency_key: `approve:${taskId}:${revision}`,
        });
        if (mounted.current) {
          setSnapshot((current) => (current ? { ...current, plan: decided.plan, revision: decided.task.revision } : decided.task));
          setDomain((current) => ({ ...current, plan: decided.plan }));
        }
        setPlanBusy('continue');
        const continued = await client.continueTask(taskId, {
          expected_plan_revision: decided.plan.revision ?? revision,
          idempotency_key: `continue:${taskId}:${revision}`,
        });
        if (mounted.current) {
          setSnapshot(continued.task);
          setDomain((current) => ({ ...current, plan: continued.plan ?? current.plan, taskState: continued.task.status }));
        }
        await follow();
        return true;
      } catch (error) {
        if (mounted.current) {
          setCommandError(planErrorText(error));
          if (error instanceof HarnessRequestError && error.code === 'selection_stale') {
            setPlanStale(true);
            await syncMeta().catch(() => {});
          }
        }
        return false;
      } finally {
        if (mounted.current) setPlanBusy(null);
      }
    },
    [client, follow, plan?.revision, savePlan, syncMeta, taskId],
  );

  const rejectPlan = useCallback(async (): Promise<void> => {
    if (!taskId || plan?.revision == null) return;
    setPlanBusy('reject');
    setCommandError(null);
    try {
      const result = await client.decidePlan(taskId, {
        decision: 'reject',
        expected_revision: plan.revision,
        idempotency_key: `reject:${taskId}:${plan.revision}`,
      });
      if (mounted.current) {
        setSnapshot((current) => (current ? { ...current, plan: result.plan, revision: result.task.revision } : result.task));
        setDomain((current) => ({ ...current, plan: result.plan }));
      }
    } catch (error) {
      if (mounted.current) setCommandError(planErrorText(error));
    } finally {
      if (mounted.current) setPlanBusy(null);
    }
  }, [client, plan?.revision, taskId]);

  /** Re-read the newest plan after a stale-revision refusal; this is a read. */
  const reviewLatestPlan = useCallback(async () => {
    const next = await syncMeta();
    if (next?.plan) setDomain((current) => ({ ...current, plan: next.plan ?? current.plan }));
    setPlanStale(false);
    setCommandError(null);
  }, [syncMeta]);

  /** Ask for a rewrite with a durable correction message. */
  const requestRevision = useCallback(
    async (instruction: string): Promise<boolean> => {
      if (!taskId) return false;
      const trimmed = instruction.trim();
      if (!trimmed) return false;
      setPlanBusy('continue');
      setCommandError(null);
      try {
        const attached = references;
        const result = await client.proposePlan(taskId, {
          instruction: trimmed,
          ...(attached.length > 0 ? { references: attached } : {}),
          idempotency_key: `revise:${taskId}:${plan?.revision ?? 0}:${Date.now()}`,
        });
        if (mounted.current) {
          setSnapshot(result.task);
          setDomain((current) => ({ ...current, taskState: result.task.status, plan: result.plan ?? current.plan }));
          setReferencesState([]);
          transport.setControls({ references: [] });
          // The correction is a durable user message; show it now instead of
          // waiting for a reload to discover it.
          if (result.message !== null) {
            const correction = userMessage(result.message);
            setMessages((current) =>
              current.some((message) => message.id === correction.id) ? current : [...current, correction],
            );
          }
        }
        await follow();
        return true;
      } catch (error) {
        if (mounted.current) setCommandError(planErrorText(error));
        return false;
      } finally {
        if (mounted.current) setPlanBusy(null);
      }
    },
    [client, follow, plan?.revision, references, setMessages, taskId, transport],
  );

  const continueExecution = useCallback(async (): Promise<void> => {
    if (!taskId || !approved || plan?.revision == null) return;
    setPlanBusy('continue');
    setCommandError(null);
    try {
      const result = await client.continueTask(taskId, {
        expected_plan_revision: plan.revision,
        idempotency_key: `continue:${taskId}:${plan.revision}`,
      });
      if (mounted.current) {
        setSnapshot(result.task);
        setDomain((current) => ({ ...current, plan: result.plan ?? current.plan, taskState: result.task.status }));
      }
      await follow();
    } catch (error) {
      if (mounted.current) setCommandError(planErrorText(error));
    } finally {
      if (mounted.current) setPlanBusy(null);
    }
  }, [approved, client, follow, plan?.revision, taskId]);

  const streaming = chatStatus === 'submitted' || chatStatus === 'streaming';

  return {
    acceptTask,
    phase,
    connection,
    taskId,
    snapshot,
    domain,
    activity,
    messages: [...messages, ...steeringMessages.filter(item => !messages.some(message => message.id === item.id))],
    setMessages,
    status,
    plan,
    approved,
    planStale,
    planBusy,
    commandError,
    streaming,
    references,
    setReferences,
    addReference,
    removeReference,
    send,
    savePlan,
    approveAndContinue,
    rejectPlan,
    continueExecution,
    requestRevision,
    reviewLatestPlan,
    reload: hydrate,
    syncMeta,
    clearCommandError: () => setCommandError(null),
  };
}

export type TaskChat = ReturnType<typeof useTaskChat>;
