'use client';

import {
  ArrowClockwiseIcon,
  ArrowDownIcon,
  ArrowUpIcon,
  CheckCircleIcon,
  CircleDashedIcon,
  CircleNotchIcon,
  PencilSimpleIcon,
  PlayIcon,
  PlusIcon,
  TrashIcon,
  XIcon,
} from '@phosphor-icons/react';
import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Badge, PathText, Textarea } from '@/components/ui/primitives';
import type { HarnessPlanData } from '@/lib/harness/projection';
import type { TaskState } from '@/lib/harness/schema';
import { cn, fa } from '@/lib/utils';

import type { PlanEdit } from './use-task-chat';

type EditStep = {
  key: string;
  id?: string | null;
  title: string;
  detail?: string | null;
  status?: 'pending' | 'in_progress' | 'completed';
};

let newStep = 0;

function stepsFrom(plan: HarnessPlanData): EditStep[] {
  return plan.steps.map((step, index) => ({
    key: step.id || `step-${index}`,
    id: step.id,
    title: step.title,
    detail: step.detail ?? null,
    status: step.status === 'completed' || step.status === 'in_progress' ? step.status : 'pending',
  }));
}

function editOf(steps: EditStep[], scope: string, checks: string): PlanEdit {
  return {
    steps: steps.map((step) => ({
      id: step.id ?? null,
      title: step.title.trim(),
      ...(step.status ? { status: step.status } : {}),
      ...(step.detail ? { detail: step.detail } : {}),
    })),
    scope: scope
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
    checks: checks
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
  };
}

function sameEdit(a: PlanEdit, b: PlanEdit): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function originalEdit(plan: HarnessPlanData): PlanEdit {
  return {
    steps: plan.steps.map((step) => ({
      id: step.id ?? null,
      title: step.title,
      ...(step.status ? { status: step.status as EditStep['status'] } : {}),
      ...(step.detail ? { detail: step.detail } : {}),
    })),
    scope: plan.scope,
    checks: plan.checks,
  };
}

function StepState({ status }: { status?: string }) {
  if (status === 'completed') return <CheckCircleIcon weight="fill" className="text-success size-4 shrink-0" />;
  if (status === 'in_progress') return <CircleNotchIcon className="text-primary size-4 shrink-0 animate-spin" />;
  return <CircleDashedIcon className="text-muted-foreground/50 size-4 shrink-0" />;
}

function Chips({ values, mono = false }: { values: string[]; mono?: boolean }) {
  if (values.length === 0) return <span className="text-faint text-xs">مشخص نشده</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((value) =>
        mono ? (
          <code key={value} dir="ltr" className="bg-raised text-muted-foreground rounded px-1.5 py-0.5 font-mono text-[11px]">
            {value}
          </code>
        ) : (
          <span key={value} className="bg-raised text-muted-foreground flex max-w-full items-center rounded px-1.5 py-1 text-[11px]">
            <PathText path={value} className="max-w-64" />
          </span>
        ),
      )}
    </div>
  );
}

export type PlanPanelProps = {
  plan: HarnessPlanData | null;
  status: TaskState | null;
  goal?: string | null;
  approved: boolean;
  stale: boolean;
  busy: 'save' | 'approve' | 'reject' | 'continue' | null;
  onSave: (edit: PlanEdit) => Promise<HarnessPlanData | null>;
  onApprove: (edit?: PlanEdit) => Promise<boolean>;
  onReject: () => Promise<void>;
  onRequestRevision: (instruction: string) => Promise<boolean>;
  onContinue: () => Promise<void>;
  onReview: () => Promise<void>;
  className?: string;
};

/**
 * The plan is product state, not model prose.
 *
 * Editing is local until saved. Approval always means "this exact revision",
 * and an approve click saves a dirty edit first, then approves the revision the
 * save returned. A revision that moved under the editor locks the approve
 * button and offers a re-read; it never approves what the user did not see.
 */
export function PlanPanel({
  plan,
  status,
  goal,
  approved,
  stale,
  busy,
  onSave,
  onApprove,
  onReject,
  onRequestRevision,
  onContinue,
  onReview,
  className,
}: PlanPanelProps) {
  const [editing, setEditing] = useState(false);
  const [steps, setSteps] = useState<EditStep[]>([]);
  const [scope, setScope] = useState('');
  const [checks, setChecks] = useState('');
  const [baseRevision, setBaseRevision] = useState<number | null>(null);
  const [reviseOpen, setReviseOpen] = useState(false);
  const [instruction, setInstruction] = useState('');

  // A rebuild after a revision request is a different plan; local edits do not
  // silently join it. `revisionMoved` below is what locks the approve button.

  const currentEdit = useMemo(() => editOf(steps, scope, checks), [checks, scope, steps]);
  const original = useMemo(() => (plan === null ? null : originalEdit(plan)), [plan]);
  const dirty = editing && original !== null && !sameEdit(currentEdit, original);
  const revisionMoved = editing && plan !== null && baseRevision !== null && plan.revision !== baseRevision;
  const locked = stale || revisionMoved;
  const actionsAvailable = status === 'awaiting_plan';
  const running = status === 'planning';
  const finished = status === 'closed' || status === 'failed' || status === 'cancelled';

  const startEdit = () => {
    if (plan === null) return;
    setSteps(stepsFrom(plan));
    setScope(plan.scope.join('\n'));
    setChecks(plan.checks.join('\n'));
    setBaseRevision(plan.revision);
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setSteps([]);
    setBaseRevision(null);
  };

  const move = (index: number, delta: number) => {
    setSteps((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const copy = [...current];
      [copy[index], copy[target]] = [copy[target], copy[index]];
      return copy;
    });
  };

  const save = async () => {
    if (plan === null) return;
    const saved = await onSave(currentEdit);
    if (saved !== null) {
      setEditing(false);
      setBaseRevision(null);
      setSteps([]);
    }
  };

  const approve = async () => {
    if (locked) {
      await onReview();
      cancelEdit();
      return;
    }
    if (busy !== null) return;
    const ok = await onApprove(editing && dirty ? currentEdit : undefined);
    if (ok) {
      setEditing(false);
      setBaseRevision(null);
      setSteps([]);
    }
  };

  const submitRevision = async () => {
    if (!instruction.trim() || busy !== null) return;
    const ok = await onRequestRevision(instruction);
    if (ok) {
      setInstruction('');
      setReviseOpen(false);
      cancelEdit();
    }
  };

  const done = plan?.steps.filter((step) => step.status === 'completed').length ?? 0;
  const total = plan?.steps.length ?? 0;

  return (
    <section className={cn('bg-surface flex min-h-0 flex-col overflow-hidden rounded-lg border', className)}>
      <header className="flex shrink-0 flex-wrap items-center gap-2 border-b px-3.5 py-2.5">
        <h2 className="text-sm font-semibold">برنامهٔ کار</h2>
        {plan?.revision != null && (
          <Badge tone="outline" className="h-5 text-[10px]">
            نسخهٔ {fa(plan.revision)}
          </Badge>
        )}
        {approved && (
          <Badge tone="success" className="h-5 text-[10px]">
            تأییدشده
          </Badge>
        )}
        {locked && (
          <Badge tone="warning" className="h-5 text-[10px]">
            نیازمند بازبینی
          </Badge>
        )}
        <span className="flex-1" />
        {total > 0 && (
          <span className="text-muted-foreground flex items-center gap-1.5 text-[11px]">
            <span className="ltr-nums">{fa(done)} از {fa(total)}</span>
          </span>
        )}
      </header>

      <div className="scrollbar-minimal min-h-0 flex-1 overflow-y-auto p-3.5">
        {goal && (
          <div className="mb-3">
            <div className="text-faint mb-1 text-[11px] font-medium">هدف</div>
            <p className="text-sm leading-6 whitespace-pre-wrap" dir="auto">{goal}</p>
          </div>
        )}

        {plan === null ? (
          <div className="flex flex-col items-center gap-2 px-3 py-10 text-center">
            {running || status === 'queued' ? (
              <>
                <CircleNotchIcon className="text-primary size-5 animate-spin" />
                <p className="text-sm font-medium">در حال آماده‌سازی برنامه…</p>
                <p className="text-muted-foreground text-xs leading-6">
                  این مرحله فقط خواندن و تحلیل است؛ هنوز هیچ فایلی تغییر نمی‌کند.
                </p>
              </>
            ) : finished ? (
              <p className="text-muted-foreground text-sm">برای این کار برنامه‌ای ثبت نشده است.</p>
            ) : (
              <p className="text-muted-foreground text-sm leading-6">
                برنامه هنوز نرسیده است. اگر دیر شد، پیام کوتاهی بفرستید تا دوباره درخواست شود.
              </p>
            )}
          </div>
        ) : (
          <>
            {locked && (
              <div className="border-warning/40 bg-warning-soft mb-3 rounded-lg border px-3 py-2.5">
                <p className="text-warning text-xs font-medium">برنامه تغییر کرده؛ بازبینی کنید</p>
                <p className="text-muted-foreground mt-1 text-[11px] leading-5">
                  نسخهٔ روی صفحه دیگر جدیدترین نسخه نیست. ویرایش‌های محلی ذخیره نمی‌شوند تا نسخهٔ تازه را ببینید.
                </p>
              </div>
            )}

            <div className="mb-3 flex items-center justify-between gap-2">
              <span className="text-faint text-[11px] font-medium">گام‌ها</span>
              {actionsAvailable && !editing && (
                <Button variant="muted" size="xs" onClick={startEdit} disabled={busy !== null || locked}>
                  <PencilSimpleIcon /> ویرایش برنامه
                </Button>
              )}
            </div>

            {editing ? (
              <ol className="space-y-2">
                {steps.map((step, index) => (
                  <li key={step.key} className="bg-panel rounded-lg border p-2">
                    <div className="flex items-start gap-1.5">
                      <span className="text-faint mt-2 w-4 shrink-0 text-center text-[11px] ltr-nums">{fa(index + 1)}</span>
                      <textarea
                        aria-label={`عنوان گام ${index + 1}`}
                        value={step.title}
                        onChange={(event) =>
                          setSteps((current) => current.map((item) => (item.key === step.key ? { ...item, title: event.target.value } : item)))
                        }
                        rows={2}
                        dir="auto"
                        className="border-input bg-surface scrollbar-minimal min-h-9 w-full resize-none rounded-md border px-2 py-1.5 text-sm leading-6 outline-none focus-visible:border-ring"
                      />
                      <div className="flex shrink-0 flex-col gap-0.5">
                        <button
                          type="button"
                          aria-label="بالا"
                          className="text-muted-foreground hover:text-foreground rounded p-1 disabled:opacity-30"
                          disabled={index === 0}
                          onClick={() => move(index, -1)}
                        >
                          <ArrowUpIcon className="size-3.5" />
                        </button>
                        <button
                          type="button"
                          aria-label="پایین"
                          className="text-muted-foreground hover:text-foreground rounded p-1 disabled:opacity-30"
                          disabled={index === steps.length - 1}
                          onClick={() => move(index, 1)}
                        >
                          <ArrowDownIcon className="size-3.5" />
                        </button>
                        <button
                          type="button"
                          aria-label="حذف گام"
                          className="text-muted-foreground hover:text-danger rounded p-1"
                          onClick={() => setSteps((current) => current.filter((item) => item.key !== step.key))}
                        >
                          <TrashIcon className="size-3.5" />
                        </button>
                      </div>
                    </div>
                  </li>
                ))}
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={() => {
                    newStep += 1;
                    setSteps((current) => [...current, { key: `new-${newStep}`, title: '', status: 'pending' }]);
                  }}
                >
                  <PlusIcon /> افزودن گام
                </Button>
              </ol>
            ) : plan.steps.length === 0 ? (
              <p className="text-muted-foreground text-xs leading-6">برنامه هنوز گامی ندارد.</p>
            ) : (
              <ol className="space-y-2.5">
                {plan.steps.map((step, index) => (
                  <li key={step.id || index} className="flex gap-2.5">
                    <span className="mt-0.5 shrink-0"><StepState status={step.status} /></span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2">
                        <span className="text-faint shrink-0 text-[11px] ltr-nums">{fa(index + 1)}.</span>
                        <span className={cn('text-sm leading-6', step.status === 'pending' && 'text-muted-foreground')} dir="auto">
                          {step.title}
                        </span>
                      </div>
                      {step.detail && (
                        <p className="text-muted-foreground mt-0.5 text-[11px] leading-5" dir="auto">{step.detail}</p>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}

            {(editing||plan.scope.length>0||plan.checks.length>0)&&<div className="border-border mt-4 space-y-3 border-t pt-3">
              <div>
                <div className="text-faint mb-1 text-[11px] font-medium">محدودهٔ فایل‌ها</div>
                {editing ? (
                  <Textarea
                    value={scope}
                    aria-label="محدودهٔ فایل‌های برنامه"
                    onChange={(event) => setScope(event.target.value)}
                    rows={3}
                    placeholder="هر خط یک مسیر یا الگو"
                    className="scrollbar-minimal min-h-16 font-mono text-xs"
                  />
                ) : (
                  <Chips values={plan.scope} mono />
                )}
              </div>
              <div>
                <div className="text-faint mb-1 text-[11px] font-medium">بررسی‌های پیشنهادی</div>
                {editing ? (
                  <Textarea
                    value={checks}
                    aria-label="بررسی‌های پیشنهادی برنامه"
                    onChange={(event) => setChecks(event.target.value)}
                    rows={3}
                    placeholder="هر خط یک فرمان بررسی"
                    className="scrollbar-minimal min-h-16 font-mono text-xs"
                  />
                ) : (
                  <Chips values={plan.checks} mono />
                )}
              </div>
              <div className="text-faint flex flex-wrap items-center gap-2 text-[10px]">
                <span>
                  وضعیت ویرایش:{' '}
                  {locked ? 'برنامه تغییر کرده' : dirty ? 'تغییر ذخیره‌نشده' : editing ? 'ویرایش باز' : 'بدون تغییر'}
                </span>
                {approved && <span>· تأیید به همین نسخه بسته است</span>}
              </div>
            </div>}
          </>
        )}
      </div>

      {reviseOpen && (
        <div className="border-border shrink-0 border-t p-2.5">
          <Textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            placeholder="چه چیزی در برنامه عوض شود؟"
            rows={2}
            autoFocus
            className="mb-2 min-h-16 text-sm"
          />
          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setReviseOpen(false)}>
              انصراف
            </Button>
            <Button size="sm" onClick={() => void submitRevision()} disabled={!instruction.trim() || busy !== null}>
              {busy === 'continue' ? <CircleNotchIcon className="animate-spin" /> : null}
              ارسال برای بازنویسی
            </Button>
          </div>
        </div>
      )}

      {plan !== null && actionsAvailable && (
        <footer className="border-border shrink-0 border-t p-2.5">
          <div className="flex flex-wrap items-center gap-1.5">
            {!locked && (
              <Button
                size="sm"
                onClick={() => void (approved && !dirty ? onContinue() : approve())}
                disabled={busy !== null}
                className="flex-1"
              >
                {busy === 'approve' || busy === 'continue' ? (
                  <CircleNotchIcon className="animate-spin" />
                ) : approved ? (
                  <PlayIcon />
                ) : (
                  <CheckCircleIcon weight="fill" />
                )}
                {approved ? 'ادامهٔ اجرا' : 'تأیید برنامه و ادامه'}
              </Button>
            )}
            {locked && (
              <Button size="sm" onClick={() => void approve()} className="flex-1">
                <ArrowClockwiseIcon /> بازبینی برنامه
              </Button>
            )}
            {!locked && (
              <Button variant="outline" size="sm" onClick={() => setReviseOpen((value) => !value)} disabled={busy !== null}>
                درخواست اصلاح
              </Button>
            )}
            {editing && (
              <>
                <Button variant="soft" size="sm" onClick={() => void save()} disabled={busy !== null || !dirty}>
                  {busy === 'save' ? <CircleNotchIcon className="animate-spin" /> : null}
                  ذخیره
                </Button>
                <Button variant="ghost" size="sm" onClick={cancelEdit}>
                  <XIcon /> لغو ویرایش
                </Button>
              </>
            )}
            {!editing && !approved && !locked && (
              <Button
                variant="muted"
                size="sm"
                aria-label="رد برنامه"
                onClick={() => void onReject()}
                disabled={busy !== null}
              >
                <XIcon />
              </Button>
            )}
          </div>
          {dirty && <p className="text-faint mt-1.5 text-[10px]">تغییرهای ذخیره‌نشده پیش از تأیید ذخیره می‌شوند.</p>}
        </footer>
      )}
    </section>
  );
}
