'use client';
import { useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';

type Artifacts={working_available:boolean;baseline_available:boolean;apply_operations:{id:string;state:string;created_at:number}[];unresolved_operations:{operation_id:string;state:string}[]};
const states:Record<string,string>={prepared:'آمادهٔ اعمال',applying:'در حال اعمال',applied:'اعمال‌شده',partial:'اعمال بخشی',unknown:'نتیجهٔ نامعلوم',conflict:'تعارض',failed:'ناموفق',succeeded:'موفق'};
export function TaskArtifacts({taskId}:{taskId:string}){
  const [open,setOpen]=useState(false);
  const [data,setData]=useState<Artifacts|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  async function read(){setOpen(true);setBusy(true);setError('');try{setData(await api.get<Artifacts>(`/tasks/${encodeURIComponent(taskId)}/artifacts`))}catch{setData(null);setError('خواندن تاریخچه ممکن نشد؛ چیزی اجرا یا بازسازی نشده است.')}finally{setBusy(false)}}
  const task='/tasks?task='+encodeURIComponent(taskId);
  return <div className="px-4 pb-3 text-xs">
    <Button size="xs" variant="outline" disabled={busy} aria-expanded={open} onClick={()=>open?setOpen(false):void read()}>تاریخچه و نسخهٔ کاری</Button>
    {open&&<section aria-label="نسخه‌ها و نتایج کار" className="mt-3 space-y-3 rounded-lg border bg-panel p-3">
      {busy&&<p role="status">در حال خواندن تاریخچه…</p>}
      {error&&<p role="alert" className="text-danger">{error}</p>}
      {data&&<><p className="text-muted-foreground">{data.baseline_available?'نسخهٔ اولیه موجود است.':'نسخهٔ اولیه در دسترس نیست؛ تاریخچه، اثبات بقای فایل‌ها نیست.'}</p>
        {data.working_available?<Link className="text-primary underline" href={task+'&view=changes'}>بازکردن نسخهٔ کاری و تغییرها</Link>:<p className="text-warning">فایل‌های نسخهٔ کاری موجود نیستند؛ بازکردن گفتگو آن‌ها را دوباره نمی‌سازد.</p>}
        {data.unresolved_operations.length>0&&<p role="alert" className="text-warning">{data.unresolved_operations.length.toLocaleString('fa-IR')} عملیات نیازمند بررسی است؛ خودکار تکرار نمی‌شود.</p>}
        {!data.apply_operations.length?<p className="text-muted-foreground">عملیات اعمال روی اصل ثبت نشده است.</p>:<ul className="space-y-2">{data.apply_operations.map(operation=><li key={operation.id}><Link className="text-primary underline" href={task+'&view=result&operation='+encodeURIComponent(operation.id)}>نتیجهٔ اعمال · {states[operation.state]??operation.state} · {new Date(operation.created_at*1000).toLocaleString('fa-IR')}</Link></li>)}</ul>}
      </>}
    </section>}
  </div>;
}
