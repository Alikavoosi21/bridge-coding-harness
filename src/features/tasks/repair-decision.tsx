'use client';

import { useMemo,useRef,useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/primitives';
import { Alert,AlertDescription } from '@/components/ui/shadcn/alert';
import { Dialog,DialogContent } from '@/components/ui/overlays';
import { createBrowserClient } from '@/lib/harness/browser';
import type { HarnessTaskSnapshot,RepairBudgetData } from '@/lib/harness/client';

export function RepairDecision({taskId,revision,budget,onTask,onReview}:{taskId:string;revision:number;budget:RepairBudgetData;onTask:(task:HarnessTaskSnapshot)=>void;onReview:()=>void}){
  const client=useMemo(()=>createBrowserClient(),[]);
  const [busy,setBusy]=useState(false),[error,setError]=useState<string|null>(null);
  const [editOpen,setEditOpen]=useState(false),[endOpen,setEndOpen]=useState(false),[text,setText]=useState('');
  const lock=useRef(false),extensionAccepted=useRef(false);
  const keys=useRef({extend:crypto.randomUUID(),continue:crypto.randomUUID(),end:crypto.randomUUID()});
  const correction=useRef<{text:string;revision:number;key:string}|null>(null);
  const ending=useRef<{revision:number}|null>(null);
  const extension=useRef<{revision:number}|null>(null);
  const run=async(work:()=>Promise<void>)=>{
    if(lock.current)return;lock.current=true;setBusy(true);setError(null);
    try{await work()}catch(error){setError(error instanceof Error?error.message:'ثبت تصمیم ممکن نشد؛ بازخوانی و دوباره بررسی کنید.')}
    finally{lock.current=false;setBusy(false)}
  };
  const again=()=>run(async()=>{
    if(!extensionAccepted.current&&budget.total_attempts>=budget.allowed){
      extension.current??={revision:budget.revision};
      await client.extendRepair(taskId,keys.current.extend,extension.current.revision);
      extensionAccepted.current=true;
    }
    const result=await client.continueTask(taskId,{idempotency_key:keys.current.continue});
    onTask(result.task);
  });
  const edit=()=>run(async()=>{
    const instruction=text.trim();if(!instruction)return;
    if(correction.current?.text!==instruction)correction.current={text:instruction,revision,key:crypto.randomUUID()};
    const intent=correction.current;
    const result=await client.proposePlan(taskId,{instruction:intent.text,expected_revision:intent.revision,idempotency_key:intent.key});
    setEditOpen(false);onTask(result.task);
  });
  const end=()=>run(async()=>{
    ending.current??={revision};
    const result=await client.endUnverified(taskId,keys.current.end,ending.current.revision);
    setEndOpen(false);onTask(result.task);
  });
  const exhausted=budget.total_attempts>=budget.allowed;
  return <section aria-label="تصمیم پس از بررسی کیفیت" className="flex flex-col gap-3 rounded-lg border border-warning/40 bg-warning-soft p-4">
    <h3 className="text-sm font-semibold">{exhausted?`${budget.total_attempts.toLocaleString('fa-IR')} بار اصلاح انجام شد؛ چگونه ادامه دهیم؟`:'بررسی کیفیت به تصمیم شما نیاز دارد'}</h3>
    <p className="text-xs leading-6">{exhausted?'یک تلاش دیگر، فقط یک واحد به سهمیه اضافه می‌کند؛ مصرف قبلی و حدود اجرای task حفظ می‌شوند.':'سهمیهٔ موجود مصرف‌نشده حفظ شده است؛ ادامه، بررسی و اجرای همان برنامهٔ تأییدشده را پی می‌گیرد.'} پایان کار فایل‌ها را روی پروژهٔ اصلی اعمال نمی‌کند.</p>
    {error&&<Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
    <div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy} onClick={()=>void again()}>{exhausted?'یک تلاش دیگر':'ادامه با سهمیهٔ موجود'}</Button><Button size="sm" variant="outline" disabled={busy} onClick={()=>setEditOpen(true)}>ویرایش درخواست</Button><Button size="sm" variant="outline" disabled={busy} onClick={onReview}>بازبینی خروجی فعلی</Button><Button size="sm" variant="danger" disabled={busy} onClick={()=>setEndOpen(true)}>پایان کار</Button></div>
    <Dialog open={editOpen} onOpenChange={setEditOpen}><DialogContent title="ویرایش درخواست" description="برنامه دوباره در حالت فقط‌خواندن تهیه می‌شود و اجرای آن به تأیید تازه نیاز دارد."><Textarea aria-label="اصلاح درخواست کار" value={text} onChange={event=>setText(event.target.value)} rows={5}/><Button disabled={busy||!text.trim()} onClick={()=>void edit()}>ثبت و بازنگری برنامه</Button></DialogContent></Dialog>
    <Dialog open={endOpen} onOpenChange={setEndOpen}><DialogContent title="پایان بدون تأیید کیفیت" description="نسخهٔ کاری برای بازبینی می‌ماند. این تصمیم موفقیت بررسی‌ها یا اجازهٔ اعمال فایل‌ها نیست."><Button variant="danger" disabled={busy} onClick={()=>void end()}>پایان بدون تأیید کیفیت</Button></DialogContent></Dialog>
  </section>;
}
