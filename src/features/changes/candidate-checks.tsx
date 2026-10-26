'use client';

import { useEffect,useRef,useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';
import { Dialog,DialogContent } from '@/components/ui/overlays';
import { api } from '@/lib/api';

type Selection={id:string;quality_status:string;check_refs:string[];candidate_manifest_hash:string;required_commands:{id:string;command:string}[];install?:{command:string}|null;network_permission?:{id:string;expiry:number}|null};
type Props={taskId:string;selectionId:string;disabled:boolean;onBusy:(value:boolean)=>void;onRunning:()=>void;onSettled:()=>void};
const labels:Record<string,string>={verified_snapshot:'بررسی‌های این نسخه موفق بودند',failed:'بررسی این نسخه ناموفق بود',stale:'شواهد بررسی قدیمی است',not_verified:'این نسخه بررسی موفق معتبر ندارد'};

export function CandidateChecks({taskId,selectionId,disabled,onBusy,onRunning,onSettled}:Props){
  const [selection,setSelection]=useState<Selection|null>(null);
  const [confirm,setConfirm]=useState(false);
  const [install,setInstall]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  const key=useRef<string|null>(null);
  const current=useRef(true);
  const base=`/tasks/${encodeURIComponent(taskId)}/apply-previews/${encodeURIComponent(selectionId)}`;
  useEffect(()=>{current.current=true;setLoading(true);api.get<Selection>(base).then(value=>{if(current.current)setSelection(value)}).catch(()=>{if(current.current)setError('پیش‌نمایش معتبر در دسترس نیست؛ انتخاب را دوباره بسازید.')}).finally(()=>{if(current.current)setLoading(false)});return()=>{current.current=false}},[base]);
  async function requestConsent(){
    setLoading(true);setError('');try{const fresh=await api.get<Selection>(base);setSelection(fresh);setInstall(false);key.current=null;setConfirm(true)}catch{setSelection(null);setError('ورودی‌ها تغییر کرده‌اند یا اتصال برقرار نیست؛ پیش‌نمایش را دوباره بسازید.')}finally{setLoading(false)}
  }
  async function run(){
    if(!selection||busy)return;setBusy(true);onBusy(true);onRunning();setConfirm(false);setError('');
    try{
      key.current??=crypto.randomUUID();
      await api.post(base+'/checks',{idempotency_key:key.current,confirm:true,approved_commands:selection.required_commands.map(row=>row.command),...(install?{approved_install:selection.install?.command,network_grant:selection.network_permission?.id}:{})});
      // A historical POST receipt alone is not proof of CURRENT quality.
      const fresh=await api.get<Selection>(base);if(current.current)setSelection(fresh);
    }catch{if(current.current){setSelection(null);setError('بررسی تأیید نشد. ممکن است محیط آماده نباشد، ورودی تغییر کرده باشد یا نتیجه نیازمند بازیابی باشد؛ نتیجهٔ موفق فرض نمی‌شود.')}}
    finally{if(current.current){setBusy(false);onBusy(false);onSettled()}}
  }
  const verified=!loading&&!error&&selection?.quality_status==='verified_snapshot';
  return <div className="flex shrink-0 flex-col gap-2 border-b bg-panel p-3 text-xs" aria-label="بررسی فایل‌های منتخب">
    <div className="flex flex-wrap items-center gap-3"><Badge tone={verified?'success':'warning'}>{busy?'در حال بررسی انتخاب':loading?'در حال اعتبارسنجی انتخاب':error?'کیفیت تأیید نشد':labels[selection?.quality_status??'not_verified']??'کیفیت نامشخص'}</Badge><span className="min-w-0 flex-1 truncate text-muted-foreground" dir="ltr">{selection?.candidate_manifest_hash.slice(0,16)}</span><Button size="xs" variant="outline" disabled={disabled||busy||loading||!selection?.required_commands.length} onClick={()=>void requestConsent()}>بررسی همین انتخاب</Button></div>
    <p className="text-muted-foreground">نتیجه فقط برای نسخهٔ ثبت‌شدهٔ این انتخاب است؛ فایل اصلی هنوز تغییر نکرده و اعمال جداگانه تأیید می‌خواهد.</p>
    {selection&&!selection.required_commands.length&&<p className="text-warning">بررسی الزامی در پروفایل پروژه تنظیم نشده است.</p>}
    {error&&<p role="alert" className="text-danger">{error}</p>}
    <Dialog open={confirm} onOpenChange={setConfirm}><DialogContent title="اجرای بررسی روی فایل‌های منتخب" description="بررسی‌ها در Docker بدون شبکه روی کپی موقت اجرا می‌شوند؛ نصب اختیاری با رضایت جدا و شبکهٔ موقت است. پروژهٔ اصلی mount نمی‌شود.">
      <ol className="flex max-h-60 flex-col gap-2 overflow-auto px-6">{selection?.required_commands.map(row=><li key={row.id}><code dir="ltr" className="block overflow-auto rounded border bg-surface p-3 font-mono text-xs">{row.command}</code></li>)}</ol>
      {selection?.install&&<div className="space-y-2 px-6 text-xs"><label className="flex gap-2"><input type="checkbox" checked={install} disabled={!selection.network_permission || selection.network_permission.expiry<=Date.now()/1000} onChange={event=>setInstall(event.target.checked)}/>پیش از بررسی، این فرمان نصب را روی کپی موقت اجرا کن:</label><code dir="ltr" className="block break-all rounded border p-2">{selection.install.command}</code><p className="text-muted-foreground">نصب نیازمند مجوز موقت شبکه از «مجوزهای کار» است؛ وابستگی‌ها پس از بررسی پاک می‌شوند و پروژهٔ اصلی تغییر نمی‌کند.</p></div>}
      <p className="px-6 text-xs text-muted-foreground">بررسی‌ها بدون شبکه حداکثر ۹۰ ثانیه اجرا می‌شوند. نصب اختیاری فقط همین فرمان را با مجوز جداگانه، حداکثر پنج دقیقه اجرا می‌کند.</p>
      <div className="flex gap-2 p-6"><Button disabled={busy||disabled} onClick={()=>void run()}>تأیید و اجرای همین فرمان‌ها</Button><Button variant="outline" onClick={()=>setConfirm(false)}>انصراف</Button></div>
    </DialogContent></Dialog>
  </div>;
}
