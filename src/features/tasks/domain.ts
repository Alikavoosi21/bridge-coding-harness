/**
 * One reducer for the canonical domain data and the activity timeline.
 *
 * The journal is the source of truth. Live `data-harness` parts and a reloaded
 * journal both go through these two functions, so the inspector cannot drift
 * from what the durable store says. Nothing here reads model text as state.
 */

import type {
  HarnessActionData,
  HarnessApprovalData,
  HarnessBudgetData,
  HarnessDataPart,
  HarnessDomainState,
  HarnessEvent,
  HarnessFileData,
  HarnessPlanData,
  HarnessQualityData,
  HarnessRepairData,
  HarnessVerificationData,
} from '@/lib/harness/projection';
import { HarnessEventProjector } from '@/lib/harness/projection';
import type { TaskState } from '@/lib/harness/schema';

export function emptyDomain(): HarnessDomainState {
  return {
    taskState: null,
    plan: null,
    budget: null,
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
}

/** Apply one typed data part to a fresh domain object (React sees a new value). */
export function applyData(domain: HarnessDomainState, data: HarnessDataPart): HarnessDomainState {
  switch (data.kind) {
    case 'plan':
      return { ...domain, plan: data.plan };
    case 'approval':
      return { ...domain, approvals: { ...domain.approvals, [data.approval.approval_id]: data.approval } };
    case 'action':
      return { ...domain, actions: { ...domain.actions, [data.action.operation_id]: data.action } };
    case 'budget':
      return { ...domain, budget: data.budget };
    case 'lease':
      return { ...domain, leases: { ...domain.leases, [data.lease.workspace_id]: data.lease } };
    case 'quality':
      return { ...domain, quality: { ...domain.quality, [data.quality.selection_id]: data.quality } };
    case 'file':
      return { ...domain, files: { ...domain.files, [data.file.file_id]: data.file } };
    case 'verification':
      return { ...domain, verifications: [...domain.verifications, data.verification] };
    case 'repair':
      return { ...domain, repairs: [...domain.repairs, data.repair] };
    case 'task-state':
      return { ...domain, taskState: data.task.state };
    case 'apply-file':
      return { ...domain, applyFiles: { ...domain.applyFiles, [data.file.file_id]: data.file } };
    case 'recovery':
      return { ...domain, recovery: data.recovery };
    default:
      return domain;
  }
}

// ── activity timeline ───────────────────────────────────────────────────────

export type ActivityKind = 'action' | 'file' | 'approval' | 'verification' | 'repair';

export type ActivityItem = {
  id: string;
  kind: ActivityKind;
  sequence: number;
  at: number;
  tool?: string | null;
  title: string;
  detail?: string | null;
  state?: string;
  output?: string | null;
  path?: string | null;
  changeKind?: string | null;
  operationId?: string | null;
  startedAt?: number | null;
  endedAt?: number | null;
  /** The tool's own receipt, when the event carried one. Never invented. */
  receipt?: unknown;
};

function actionTitle(action: HarnessActionData): string {
  return action.summary?.trim() || action.tool || 'اقدام';
}

function upsertAction(items: ActivityItem[], data: Extract<HarnessDataPart, { kind: 'action' }>): ActivityItem[] {
  const action = data.action;
  const id = `action:${action.operation_id}`;
  const existing = items.find((item) => item.id === id);
  if (existing === undefined) {
    return [
      ...items,
      {
        id,
        kind: 'action',
        sequence: data.sequence,
        at: data.occurred_at,
        tool: action.tool,
        title: actionTitle(action),
        detail: action.summary ?? null,
        state: action.state,
        output: action.state === 'failed' ? action.summary ?? null : null,
        operationId: action.operation_id,
        startedAt: data.occurred_at,
        endedAt: action.state === 'running' || action.state === 'pending' || action.state === 'dispatching' ? null : data.occurred_at,
        receipt: action.receipt,
      },
    ];
  }
  return items.map((item) =>
    item.id === id
      ? {
          ...item,
          sequence: Math.max(item.sequence, data.sequence),
          at: item.at,
          tool: action.tool ?? item.tool,
          title: actionTitle(action),
          detail: action.summary ?? item.detail,
          state: action.state,
          output: action.state === 'failed' ? action.summary ?? item.output : item.output,
          endedAt:
            action.state === 'running' || action.state === 'pending' || action.state === 'dispatching'
              ? null
              : data.occurred_at,
          receipt: action.receipt ?? item.receipt,
        }
      : item,
  );
}

function upsertFile(items: ActivityItem[], data: Extract<HarnessDataPart, { kind: 'file' }>): ActivityItem[] {
  const file = data.file;
  const id = `file:${file.file_id}`;
  const existing = items.find((item) => item.id === id);
  const next: ActivityItem = {
    id,
    kind: 'file',
    sequence: data.sequence,
    at: existing?.at ?? data.occurred_at,
    title: file.path,
    path: file.path,
    changeKind: file.change_kind,
    state: file.change_kind,
  };
  return existing === undefined ? [...items, next] : items.map((item) => (item.id === id ? { ...next, at: item.at } : item));
}

function upsertApproval(items: ActivityItem[], data: Extract<HarnessDataPart, { kind: 'approval' }>): ActivityItem[] {
  const approval = data.approval;
  const id = `approval:${approval.approval_id}`;
  const payload: ActivityItem = {
    id,
    kind: 'approval',
    sequence: data.sequence,
    at: data.occurred_at,
    tool: approval.tool,
    title: approval.summary?.trim() || approval.tool || 'درخواست تأیید',
    detail: approval.scope?.join('، ') ?? null,
    state: approval.state,
    operationId: approval.approval_id,
  };
  const existing = items.find((item) => item.id === id);
  return existing === undefined
    ? [...items, payload]
    : items.map((item) => (item.id === id ? { ...payload, at: item.at, sequence: Math.max(item.sequence, data.sequence) } : item));
}

/** Add or update one timeline row from a canonical data part. */
export function applyActivity(items: ActivityItem[], data: HarnessDataPart): ActivityItem[] {
  switch (data.kind) {
    case 'action':
      return upsertAction(items, data);
    case 'file':
      return upsertFile(items, data);
    case 'approval':
      return upsertApproval(items, data);
    case 'verification':
      return [
        ...items,
        {
          id: `verification:${data.event_id}`,
          kind: 'verification',
          sequence: data.sequence,
          at: data.occurred_at,
          title:
            data.verification.outcome === 'passed'
              ? 'بررسیها قبول شد'
              : data.verification.outcome === 'failed'
                ? 'بررسیها رد شد'
                : 'نتیجهٔ بررسی',
          state: data.verification.outcome,
          detail: data.verification.check_refs?.join('، ') ?? null,
        },
      ];
    case 'repair':
      return [
        ...items,
        {
          id: `repair:${data.event_id}`,
          kind: 'repair',
          sequence: data.sequence,
          at: data.occurred_at,
          title: 'دور اصلاح',
          detail: data.repair.reason,
          state: 'repairing',
        },
      ];
    default:
      return items;
  }
}

// ── reload ──────────────────────────────────────────────────────────────────

export type HydratedDomain = {
  domain: HarnessDomainState;
  activity: ActivityItem[];
};

/**
 * Rebuild the inspector from the whole journal.
 *
 * Text events are applied too, because the projector's cursor has to advance
 * through them, but this projector starts with no messages so the transcript is
 * unaffected. Only `data-harness` chunks are collected.
 */
export function domainFromJournal(
  taskId: string,
  status: TaskState | null,
  events: HarnessEvent[],
  snapshot: { plan?: HarnessPlanData | null; budget?: HarnessBudgetData | null } = {},
): HydratedDomain {
  const projector = new HarnessEventProjector({ taskId, cursor: 0, status });
  let activity: ActivityItem[] = [];

  for (const event of events) {
    for (const chunk of projector.apply(event)) {
      if (chunk.type === 'data-harness') {
        activity = applyActivity(activity, chunk.data as HarnessDataPart);
      }
    }
  }

  const domain = { ...projector.snapshot().domain };
  if (snapshot.plan && (domain.plan === null || (snapshot.plan.revision ?? 0) >= (domain.plan.revision ?? 0))) {
    domain.plan = snapshot.plan;
  }
  if (snapshot.budget) domain.budget = snapshot.budget;

  return { domain, activity: [...activity].sort((a, b) => a.sequence - b.sequence) };
}

/** Group repeated actions so the timeline does not turn into one line per token. */
export function groupActivity(items: ActivityItem[]): ActivityItem[] {
  return [...items].sort((a, b) => a.sequence - b.sequence);
}

export type { HarnessActionData, HarnessApprovalData, HarnessFileData, HarnessQualityData, HarnessRepairData, HarnessVerificationData };
