'use client';

import { useRef,useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Dialog,DialogContent } from '@/components/ui/overlays';

type Pin={skill_id:string;name:string;hash:string};
type Preview={current:Pin[];desired:Pin[];legacy_entries:string[];pins_hash:string;task_revision:number;working_revision:number;working_manifest_hash:string};

export function RepinDialog({taskId,disabled,onBusy,onChanged}:{taskId:string;disabled:boolean;onBusy:(value:boolean)=>void;onChanged:()=>Promise<void>}){
  const [preview,setPreview]=useState<Preview|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [operation,setOperation]=useState<string|null>(null);
  const request=useRef<Record<string,unknown>|null>(null);
  const planning=useRef<Record<string,unknown>|null>(null);
  const base=`/tasks/${encodeURIComponent(taskId)}`;
  async function inspect(){setBusy(true);setError('');try{const task=await api.get<{status:string}>(base);if(['queued','planning','executing','verifying','repairing','stopping','closed','failed','cancelled','recovery_required'].includes(task.status))throw new Error('not idle');setPreview(await api.get<Preview>(base+'/skill-repin-preview'));request.current=null}catch{setError('کار باید snapshot معتبر و وضعیت متوقف داشته باشد؛ ابتدا آن را باز و در صورت نیاز متوقف کنید.')}finally{setBusy(false)}}
  async function repin(){if(!preview)return;setBusy(true);onBusy(true);setError('');try{request.current??={idempotency_key:crypto.randomUUID(),confirm:true,expected_revision:preview.task_revision,expected_working_revision:preview.working_revision,expected_working_hash:preview.working_manifest_hash,expected_pins_hash:preview.pins_hash};const result=await api.post<{operation_id:string}>(base+'/skill-repins',request.current);setOperation(result.operation_id);setPreview(null);await onChanged()}catch{setError('بازپین تأیید نشد؛ نسخه‌ها تغییر کرده‌اند یا بازیابی لازم است. کار خودکار ادامه پیدا نمی‌کند.')}finally{setBusy(false);onBusy(false)}}
  async function propose(){if(!operation)return;setBusy(true);onBusy(true);setError('');try{if(!planning.current){const task=await api.get<{revision:number}>(base);planning.current={idempotency_key:'skill-replan:'+operation,expected_revision:task.revision,instruction:'مهارت‌های این کار صریحاً به نسخه‌های بازبینی‌شدهٔ جدید pin شده‌اند. Skill مرتبط را دوباره بخوان، برنامهٔ تازه پیشنهاد بده و تا تأیید من هیچ تغییری اجرا نکن.'}}await api.post(base+'/plan-proposals',planning.current);window.location.href='/tasks?task='+encodeURIComponent(taskId)}catch{setError('درخواست برنامه تأیید نشد؛ اجرای کد آغاز نشده است. می‌توانید همین درخواست را دوباره بررسی کنید.')}finally{setBusy(false);onBusy(false)}}
  return <div className="mt-3 flex flex-col gap-3 text-xs">
    {!operation?<Button size="sm" variant="outline" className="self-start" disabled={disabled||busy} onClick={()=>void inspect()}>به‌روزرسانی مهارت‌های گفتگو</Button>:<div role="status" className="flex flex-wrap items-center gap-3 rounded border border-warning p-3"><span className="flex-1">نسخه‌های جدید ثبت شدند؛ تأیید برنامهٔ قبلی لغو شده است. برنامهٔ تازه و تأیید جدید لازم است.</span><Button size="sm" disabled={busy} onClick={()=>void propose()}>درخواست برنامهٔ تازه</Button><Button asChild size="sm" variant="outline"><Link href={'/tasks?task='+encodeURIComponent(taskId)}>بازکردن کار</Link></Button></div>}
    {error&&<p role="alert" className="text-danger">{error}</p>}
    <Dialog open={preview!==null} onOpenChange={value=>{if(!value&&!busy)setPreview(null)}}><DialogContent title="تغییر نسخهٔ مهارت‌های همین کار" description="نسخهٔ قبلی archive می‌شود؛ تأیید برنامه و مجوزهای قبلی لغو می‌شوند. هیچ اختیار شبکه یا نوشتن تازه‌ای صادر نمی‌شود."><div className="flex min-h-0 flex-col gap-3 overflow-auto px-6 text-xs">{!!preview?.legacy_entries.length&&<p className="text-warning" role="status">محتوای قدیمی بدون pin: {preview.legacy_entries.join("، ")}. این محتوا بدون اجرا در بایگانی نگه داشته می‌شود و تنها نسخه‌های بازبینی‌شدهٔ مقصد بارگذاری می‌شوند.</p>}<div className="grid gap-3 sm:grid-cols-2"><section><h3 className="mb-2 font-semibold">نسخه‌های فعلی</h3><ul className="flex flex-col gap-2">{preview?.current.map(pin=><li key={pin.skill_id}><bdi>{pin.name}</bdi><code dir="ltr" className="block text-muted-foreground">{pin.hash.slice(0,16)}</code></li>)}</ul></section><section><h3 className="mb-2 font-semibold">نسخه‌های مقصدِ بازبینی‌شده</h3><ul className="flex flex-col gap-2">{preview?.desired.map(pin=><li key={pin.skill_id}><bdi>{pin.name}</bdi><code dir="ltr" className="block text-muted-foreground">{pin.hash.slice(0,16)}</code></li>)}</ul>{preview?.desired.length===0&&<p>هیچ Skill فعالی pin نمی‌شود.</p>}</section></div><p className="text-warning">پس از این تصمیم، برنامه باید با نسخه‌های تازه بازنویسی و دوباره تأیید شود؛ اجرای خودکار آغاز نمی‌شود.</p>{error&&<p role="alert" className="text-danger">{error}</p>}</div><div className="flex gap-2 p-6"><Button disabled={busy} onClick={()=>void repin()}>استفاده از مهارت‌های تازه و بازبینی برنامه</Button><Button variant="outline" disabled={busy} onClick={()=>setPreview(null)}>انصراف</Button></div></DialogContent></Dialog>
  </div>;
}
