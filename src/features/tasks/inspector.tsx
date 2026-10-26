'use client';

import { FilePlusIcon, FileTextIcon, FileXIcon, GaugeIcon } from '@phosphor-icons/react';
import { useRouter } from 'next/navigation';

import { PanelCard } from '@/components/ui/patterns';
import { PathText } from '@/components/ui/primitives';
import { cn, fa } from '@/lib/utils';

import { PlanPanel } from './plan-panel';
import type { TaskChat } from './use-task-chat';

const changeLabel: Record<string, string> = {
  added: 'افزوده شد',
  modified: 'تغییر کرد',
  deleted: 'حذف شد',
  binary: 'دودویی',
  unsupported: 'پشتیبانی‌نشده',
};

const changeTone: Record<string, string> = {
  added: 'text-success',
  modified: 'text-warning',
  deleted: 'text-danger',
  binary: 'text-muted-foreground',
  unsupported: 'text-muted-foreground',
};

function ChangedFiles({ chat }: { chat: TaskChat }) {
  const router = useRouter();
  const files = Object.values(chat.domain.files).sort((a, b) => a.path.localeCompare(b.path));

  return (
    <PanelCard
      title="فایل‌های تغییرکرده"
      count={files.length}
      defaultExpanded={files.length > 0}
      contentClassName="border-t p-1.5"
    >
      {files.length === 0 ? (
        <p className="text-muted-foreground px-2 py-3 text-xs leading-6">
          فایل‌هایی که این کار می‌سازد، عوض می‌کند یا حذف می‌کند اینجا با نوع تغییر می‌آید.
        </p>
      ) : (
        files.map((file) => (
          <button
            key={file.file_id}
            type="button"
            onClick={() => {
              if(chat.taskId)router.push('/tasks?task='+encodeURIComponent(chat.taskId)+'&view=changes&file='+encodeURIComponent(file.path.replace(/^\/workspace\//,'').replace(/^\//,'')));
            }}
            className="hover:bg-hover flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start"
          >
            {file.change_kind === 'deleted' ? (
              <FileXIcon className="text-danger size-4 shrink-0" />
            ) : file.change_kind === 'added' ? (
              <FilePlusIcon className="text-success size-4 shrink-0" />
            ) : (
              <FileTextIcon className="text-info size-4 shrink-0" />
            )}
            <PathText path={file.path} className="min-w-0 flex-1 text-xs" />
            <span className={cn('shrink-0 text-[10px]', changeTone[file.change_kind])}>
              {changeLabel[file.change_kind] ?? file.change_kind}
            </span>
          </button>
        ))
      )}
    </PanelCard>
  );
}

function Budget({ chat }: { chat: TaskChat }) {
  const budget = chat.domain.budget;
  if (budget === null) return null;
  const seconds = (ms: number) => `${fa(Math.round(ms / 1000))} ثانیه`;
  const rows: [string, string][] = [
    ['زمان فعال', `${seconds(budget.active_ms)} از ${seconds(budget.max_active_ms)}`],
    ['فراخوانی مدل', `${fa(budget.model_calls)} از ${fa(budget.max_model_calls)}`],
    ['فراخوانی ابزار', `${fa(budget.tool_calls)} از ${fa(budget.max_tool_calls)}`],
    ['نسخهٔ بودجه', fa(budget.revision)],
  ];
  return (
    <PanelCard
      title="مصرف"
      indicator={<GaugeIcon className="text-muted-foreground size-3.5" />}
      defaultExpanded={false}
      contentClassName="border-t px-3.5 py-3"
    >
      <dl className="space-y-1.5 text-xs">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="ltr-nums shrink-0 font-medium">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="text-faint mt-2 text-[10px] leading-5">فقط اعداد واقعی ثبت‌شده؛ هیچ درصد یا تخمینی ساخته نمی‌شود.</p>
    </PanelCard>
  );
}

/** The plan alone, for the narrow layout where the inspector becomes a tab. */
export function PlanOnly({ chat }: { chat: TaskChat }) {
  return (
    <PlanPanel
      className="w-full"
      plan={chat.plan}
      status={chat.status}
      goal={null}
      approved={chat.approved}
      stale={chat.planStale}
      busy={chat.planBusy}
      onSave={chat.savePlan}
      onApprove={chat.approveAndContinue}
      onReject={chat.rejectPlan}
      onRequestRevision={chat.requestRevision}
      onContinue={chat.continueExecution}
      onReview={chat.reviewLatestPlan}
    />
  );
}

/**
 * The left inspector of P04/P05: the plan, then the files this task changed,
 * then the budget when the journal has one. On a narrow screen the parent turns
 * the plan tab into a page of the centre column.
 */
export function Inspector({ chat, className }: { chat: TaskChat; className?: string }) {
  return (
    <div className={cn('bg-panel flex h-full min-h-0 flex-col gap-2 overflow-hidden p-2.5', className)}>
      <PlanPanel
        className="min-h-0 flex-1"
        plan={chat.plan}
        status={chat.status}
        goal={chat.snapshot?.prompt ?? null}
        approved={chat.approved}
        stale={chat.planStale}
        busy={chat.planBusy}
        onSave={chat.savePlan}
        onApprove={chat.approveAndContinue}
        onReject={chat.rejectPlan}
        onRequestRevision={chat.requestRevision}
        onContinue={chat.continueExecution}
        onReview={chat.reviewLatestPlan}
      />
      <ChangedFiles chat={chat} />
      <Budget chat={chat} />
    </div>
  );
}
