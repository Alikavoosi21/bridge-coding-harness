'use client';
import Link from 'next/link';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { PageBody, PageHeader } from '@/features/shell/page';
import { Button } from '@/components/ui/button';
import { Badge, Input } from '@/components/ui/primitives';
import { useTaskList } from './use-task-list';
import { taskStateLabel, taskStateTone } from './status';
import { TaskArtifacts } from './task-artifacts';

export function TaskList() {
  const list=useTaskList({limit:100});
  const [query,setQuery]=useState('');
  const router=useRouter();
  const items=list.items.filter(t => `${t.title ?? ''} ${t.prompt ?? ''}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="flex min-h-0 flex-1 flex-col"><PageHeader title="کارها" actions={<Button asChild size="sm"><Link href="/">کار جدید</Link></Button>} /><PageBody>
    <Input value={query} onChange={e=>setQuery(e.target.value)} placeholder="جست‌وجوی کارهای همین پروژه…" aria-label="جست‌وجوی کارها" />
    {list.loading ? <p className="text-muted-foreground py-8">در حال خواندن کارها…</p> : list.error ? <div role="alert" className="py-8"><p className="text-danger">خواندن کارها ممکن نشد.</p><Button onClick={()=>void list.refresh()}>تلاش دوباره</Button></div> : !items.length ? <p className="text-muted-foreground py-8">{query?'کاری با این عبارت پیدا نشد.':'هنوز کاری شروع نشده است.'}</p> : <ul className="border-border mt-4 divide-y rounded-lg border">{items.map(task=><li key={task.id}><button className="hover:bg-hover flex w-full items-center gap-4 px-4 py-4 text-start" onClick={()=>router.push(`/tasks?task=${encodeURIComponent(task.id)}`)}><span dir="auto" className="min-w-0 flex-1 truncate">{task.title || task.prompt || 'کار بدون عنوان'}</span><Badge tone={taskStateTone[task.status]}>{taskStateLabel[task.status]}</Badge></button><TaskArtifacts taskId={task.id}/></li>)}</ul>}
    {list.items.length===100 && <p className="text-faint mt-3 text-xs">صد کار اخیر نمایش داده می‌شود.</p>}
  </PageBody></div>;
}
