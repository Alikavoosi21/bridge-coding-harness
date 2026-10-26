'use client';

import {
  CheckCircleIcon,
  FilePlusIcon,
  FileTextIcon,
  HammerIcon,
  ShieldWarningIcon,
  TerminalWindowIcon,
  WrenchIcon,
} from '@phosphor-icons/react';
import Link from 'next/link';

import { PathText } from '@/components/ui/primitives';
import { toolLabel } from '@/lib/backend';
import { useUi } from '@/lib/store';
import { cn, fa } from '@/lib/utils';

import type { ActivityItem } from './domain';
import { elapsed } from './status';
import { Tool,ToolHeader,ToolContent,ToolOutput } from '@/components/ai-elements/tool';

function timeOf(seconds: number): string {
  return new Date(seconds * 1000).toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit' });
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function textField(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

function numberField(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** The command's own receipt. Missing pieces stay missing; nothing is guessed. */
function receiptOf(item: ActivityItem) {
  const data = record(item.receipt);
  if (data === null) return null;
  const stdout = textField(data.stdout) ?? textField(data.output);
  const stderr = textField(data.stderr);
  const exitCode = numberField(data.exit_code) ?? numberField(data.exitCode);
  const cwd = textField(data.cwd);
  if (stdout === null && stderr === null && exitCode === null && cwd === null) return null;
  return { stdout, stderr, exitCode, cwd, truncated:data.truncated===true, stopped:data.stopped===true, timedOut:data.timed_out===true };
}

function iconFor(item: ActivityItem) {
  if (item.kind === 'file') return <FileTextIcon className="text-info size-4 shrink-0" />;
  if (item.kind === 'approval') return <ShieldWarningIcon className="text-warning size-4 shrink-0" />;
  if (item.kind === 'verification') return <CheckCircleIcon className="text-success size-4 shrink-0" />;
  if (item.kind === 'repair') return <WrenchIcon className="text-warning size-4 shrink-0" />;
  if (item.tool === 'execute') return <TerminalWindowIcon className="text-primary size-4 shrink-0" />;
  if (item.tool === 'write_file' || item.tool === 'edit_file') return <FilePlusIcon className="text-info size-4 shrink-0" />;
  return <HammerIcon className="text-muted-foreground size-4 shrink-0" />;
}

function stateTone(state?: string): string {
  if (state === 'succeeded' || state === 'passed' || state === 'added' || state === 'completed') return 'text-success';
  if (state === 'failed' || state === 'denied' || state === 'deleted') return 'text-danger';
  if (state === 'running' || state === 'dispatching' || state === 'pending' || state === 'repairing') return 'text-primary';
  if (state === 'awaiting_approval' || state === 'required' || state === 'modified') return 'text-warning';
  return 'text-muted-foreground';
}

function stateLabel(state?: string): string | null {
  const labels: Record<string, string> = {
    pending: 'در انتظار',
    awaiting_approval: 'منتظر تأیید',
    dispatching: 'در حال ارسال',
    running: 'در حال اجرا',
    succeeded: 'انجام شد',
    failed: 'ناموفق',
    denied: 'رد شد',
    required: 'منتظر تصمیم',
    decided: 'تصمیم گرفته شد',
    added: 'افزوده شد',
    modified: 'تغییر کرد',
    deleted: 'حذف شد',
    binary: 'دودویی',
    unsupported: 'پشتیبانی‌نشده',
    passed: 'قبول',
    skipped: 'رد شد',
    not_configured: 'تنظیم نشده',
    stopped: 'متوقف',
    timed_out: 'زمان تمام شد',
  };
  return state ? (labels[state] ?? state) : null;
}

function ActivityRow({ item,taskId }: { item: ActivityItem;taskId?:string }) {
  const setOpenFile = useUi((s) => s.setOpenFile);
  const receipt = receiptOf(item);
  const duration = elapsed(item.startedAt ?? null, item.endedAt ?? null);
  const state = stateLabel(item.state);
  const isFile = item.kind === 'file' && item.path;

  return (
    <li className="px-3.5 py-3">
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5">{iconFor(item)}</span>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="min-w-0 truncate text-sm font-medium" dir="auto">
              {item.kind === 'action' && item.tool ? (toolLabel[item.tool] ?? item.tool) : item.title}
            </span>
            {item.kind === 'action' && item.title !== (item.tool ? toolLabel[item.tool] : undefined) && (
              <span className="text-muted-foreground min-w-0 truncate text-xs" dir="auto">{item.title}</span>
            )}
          </div>

          {isFile ? (
            <Link
              href={taskId?'/tasks?task='+encodeURIComponent(taskId)+'&view=changes&file='+encodeURIComponent((item.path??'').replace(/^\/workspace\//,'').replace(/^\//,'')):'/files'}
              className="text-start"
              onClick={() => {
                if (!item.path) return;
                setOpenFile(item.path);
              }}
            >
              <PathText path={item.path ?? ''} className="text-muted-foreground mt-1 max-w-full text-xs" />
            </Link>
          ) : item.detail ? (
            <div className="text-muted-foreground mt-0.5 text-xs leading-6" dir="auto">{item.detail}</div>
          ) : null}

          <div className="text-faint mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
            <span className="ltr-nums">{timeOf(item.at)}</span>
            {duration && (
              <>
                <span>·</span>
                <span>{duration}</span>
              </>
            )}
            {receipt?.cwd && (
              <>
                <span>·</span>
                <PathText path={receipt.cwd} className="max-w-56" />
              </>
            )}
            {receipt?.exitCode != null && (
              <>
                <span>·</span>
                <span className="ltr-nums">exit {receipt.exitCode.toLocaleString('fa-IR')}</span>
              </>
            )}
            {state && (
              <>
                <span>·</span>
                <span className={cn('font-medium', stateTone(item.state))}>{state}</span>
              </>
            )}
            {receipt?.stopped && <span>فرمان متوقف شد</span>}
            {receipt?.timedOut && <span>مهلت فرمان تمام شد</span>}
          </div>

          {(receipt?.stdout || receipt?.stderr) && (
            <Tool className="mt-2">
              <ToolHeader title="خروجی فرمان" state={item.state==='failed'?'output-error':item.state==='denied'?'output-denied':'output-available'}/>
              <ToolContent>
              {receipt.truncated && <p className="text-warning mt-1 text-[11px]">خروجی کوتاه شده است؛ متن کامل در این نما موجود نیست.</p>}
              <ToolOutput output={receipt.stdout} errorText={receipt.stderr}/>
              </ToolContent>
            </Tool>
          )}

          {item.kind === 'file' && item.path && (
            <Link
              href={taskId?'/tasks?task='+encodeURIComponent(taskId)+'&view=changes&file='+encodeURIComponent(item.path.replace(/^\/workspace\//,'').replace(/^\//,'')):'/files'}
              onClick={() => setOpenFile(item.path ?? null)}
              className="text-primary mt-1 inline-block text-[11px]"
            >
              بازبینی تغییر فایل
            </Link>
          )}
        </div>
      </div>
    </li>
  );
}

/** The full timeline tab: what was read, changed or run, in order, with real times. */
export function ActivityPanel({ activity,taskId }: { activity: ActivityItem[];taskId?:string }) {
  if (activity.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-6 py-16">
        <div className="text-center">
          <TerminalWindowIcon className="text-faint mx-auto size-8" />
          <p className="mt-2 text-sm font-medium">هنوز فعالیتی ثبت نشده است.</p>
          <p className="text-muted-foreground mt-1 text-xs leading-6">
            خواندن فایل، تغییر و فرمان‌ها با زمان و نتیجهٔ واقعی اینجا می‌آید.
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="mx-auto w-full max-w-[880px] px-6 py-5">
      <ol className="divide-border bg-surface divide-y overflow-hidden rounded-lg border">
        {activity.map((item) => (
          <ActivityRow key={item.id} item={item} taskId={taskId} />
        ))}
      </ol>
    </div>
  );
}

/**
 * A compact answer above the conversation: the last few real actions. It is a
 * summary of the same timeline, never a second progress bar and never a guess.
 */
export function ActivitySummary({ activity, onOpenAll }: { activity: ActivityItem[]; onOpenAll: () => void }) {
  if (activity.length === 0) return null;
  const recent = activity.slice(-3);
  return (
    <div className="bg-surface/60 rounded-lg border">
      <div className="flex items-center justify-between gap-3 border-b px-3.5 py-2">
        <span className="text-muted-foreground flex items-center gap-1.5 text-xs font-medium">
          <TerminalWindowIcon className="size-3.5" />
          فعالیت‌های اخیر
        </span>
        <button type="button" onClick={onOpenAll} className="text-primary text-[11px] hover:underline">
          همهٔ {fa(activity.length)} مورد
        </button>
      </div>
      <ul className="divide-border divide-y">
        {recent.map((item) => (
          <li key={item.id} className="flex items-center gap-2 px-3.5 py-1.5 text-xs">
            {iconFor(item)}
            <span className="min-w-0 flex-1 truncate" dir="auto">
              {item.kind === 'action' && item.tool ? (toolLabel[item.tool] ?? item.tool) : item.title}
            </span>
            <span className={cn('shrink-0 text-[11px]', stateTone(item.state))}>{stateLabel(item.state) ?? timeOf(item.at)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
