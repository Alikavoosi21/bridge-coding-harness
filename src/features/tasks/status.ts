/**
 * One table for what a task state means to a person.
 *
 * The state is product state from the journal, never a guess made from model
 * text. A long run shows exactly one motion piece at a time; see `motionFor`.
 */

import type { TaskState } from '@/lib/harness/schema';
import type { MotionState } from '@/components/shared/state-motion';

export type TaskTone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger' | 'info';

export const taskStateLabel: Record<TaskState, string> = {
  draft: 'پیش‌نویس',
  queued: 'در صف',
  planning: 'در حال برنامه‌ریزی',
  awaiting_plan: 'منتظر تأیید برنامه',
  executing: 'در حال اجرا',
  awaiting_action: 'منتظر تأیید شما',
  verifying: 'در حال بررسی',
  repairing: 'در حال اصلاح',
  awaiting_decision: 'منتظر تصمیم',
  paused_limit: 'متوقف شد؛ سقف مصرف',
  stopping: 'در حال توقف',
  paused: 'متوقف',
  recovery_required: 'نیازمند بازیابی',
  closed: 'تمام شد',
  failed: 'خطا',
  cancelled: 'لغو شد',
};

export const taskStateTone: Record<TaskState, TaskTone> = {
  draft: 'neutral',
  queued: 'primary',
  planning: 'primary',
  awaiting_plan: 'warning',
  executing: 'primary',
  awaiting_action: 'warning',
  verifying: 'primary',
  repairing: 'primary',
  awaiting_decision: 'warning',
  paused_limit: 'warning',
  stopping: 'warning',
  paused: 'neutral',
  recovery_required: 'danger',
  closed: 'neutral',
  failed: 'danger',
  cancelled: 'neutral',
};

/** States in which the journal may still grow without a new user message. */
const ACTIVE: ReadonlySet<TaskState> = new Set<TaskState>([
  'queued',
  'planning',
  'executing',
  'verifying',
  'repairing',
  'stopping',
]);

export function isActiveTaskState(state: TaskState | null | undefined): boolean {
  return state != null && ACTIVE.has(state);
}

export function isWaitingTaskState(state: TaskState | null | undefined): boolean {
  return state === 'awaiting_plan' || state === 'awaiting_action' || state === 'awaiting_decision';
}

/** The loading/working motion for a state, or null when motion would be decoration. */
export function motionFor(state: TaskState | null | undefined, outcome?: string | null): MotionState | null {
  switch (state) {
    case 'queued':
    case 'planning':
    case 'verifying':
      return 'loading';
    case 'executing':
      return 'executing';
    case 'awaiting_action':
      return 'approval';
    case 'repairing':
      return 'correcting';
    case 'awaiting_plan':
    case 'awaiting_decision':
      return null;
    case 'closed':
      return outcome === 'checks_passed' ? 'success' : null;
    default:
      return null;
  }
}

/** A short, plain line for the status badge. `outcome` refines a finished task. */
export function stateCaption(state: TaskState | null | undefined, outcome?: string | null): string {
  if (state == null) return 'در حال خواندن وضعیت';
  if (state === 'closed') {
    if (outcome === 'user_ended_unverified') return 'بدون تأیید کیفیت پایان یافت';
    if (outcome === 'failed') return 'با خطا تمام شد';
    if (outcome === 'cancelled') return 'لغو شد';
    return 'تمام شد';
  }
  if (state === 'paused' && outcome === 'stopped_by_user') return 'متوقف شد';
  return taskStateLabel[state];
}

/** Persian seconds/minutes for the activity timeline. */
export function elapsed(start: number | null | undefined, end: number | null | undefined): string | null {
  if (start == null) return null;
  const finish = end ?? Date.now() / 1000;
  const seconds = Math.max(0, finish - start);
  if (seconds < 1) return 'کمتر از یک ثانیه';
  if (seconds < 60) return `${Math.round(seconds).toLocaleString('fa-IR')} ثانیه`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes.toLocaleString('fa-IR')} دقیقه`;
  const hours = Math.round(minutes / 60);
  return `${hours.toLocaleString('fa-IR')} ساعت`;
}
