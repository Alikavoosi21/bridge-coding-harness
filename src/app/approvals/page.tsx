'use client';

import { CheckIcon } from '@phosphor-icons/react';
import Link from 'next/link';

import { PageBody, PageHeader } from '@/features/shell/page';
import { Button } from '@/components/ui/button';
import { EmptyNote } from '@/components/ui/patterns';
import { useTaskList } from '@/features/tasks/use-task-list';

/** Every action that is paused for a human, across all tasks, in one queue. */
export default function ApprovalsPage() {
  const waiting=useTaskList({limit:200,status:'awaiting_action'});

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="صندوق تأیید" meta={`${waiting.items.length.toLocaleString('fa-IR')} کار منتظر تصمیم`} />
      <PageBody className="max-w-[880px] space-y-6">
        {waiting.error ? <div role="alert" className="text-danger">خواندن درخواست‌ها ممکن نشد.<Button variant="outline" onClick={()=>void waiting.refresh()}>تلاش دوباره</Button></div> : waiting.loading ? <p className="text-muted-foreground">در حال خواندن درخواست‌ها…</p> : waiting.items.length === 0 ? (
          <div className="flex min-h-[55vh] items-center justify-center">
            <EmptyNote icon={<CheckIcon />} title="چیزی منتظر تأیید نیست">
              درخواست‌های همین پروژه اینجا نمایش داده می‌شوند.
            </EmptyNote>
          </div>
        ) : (
          waiting.items.map((run) => (
            <section key={run.id} className="bg-surface rounded-lg border p-4">
              <div className="mb-2 flex items-center justify-between gap-3">
                <h2 className="min-w-0 truncate text-base font-semibold" dir="auto">{run.title || 'کار بدون عنوان'}</h2>
                <Button asChild size="sm"><Link href={`/tasks?task=${encodeURIComponent(run.id)}`}>بازبینی درخواست‌ها</Link></Button>
              </div>
              <p className="text-muted-foreground text-xs">فرمان، اثر و مدت مجوز را در گفتگو بازبینی کنید.</p>
            </section>
          ))
        )}
      </PageBody>
    </div>
  );
}
