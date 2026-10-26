'use client';

import { useRef,useState } from 'react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Dialog,DialogContent } from '@/components/ui/overlays';

type Preview={id:string;quality_status:string;candidate_manifest_hash:string;check_refs:string[];destination:{name:string;root:string};files:{path:string;kind:string}[]};
const labels:Record<string,string>={added:'ایجاد',modified:'ویرایش',deleted:'حذف'};

export function ApplyDialog({taskId,selectionId,disabled,onBusy}:{taskId:string;selectionId:string;disabled:boolean;onBusy:(value:boolean)=>void}){
  const [preview,setPreview]=useState<Preview|null>(null);
  const [open,setOpen]=useState(false);
  const [ack,setAck]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const request=useRef<{idempotency_key:string;confirm:true;quality_ack:boolean}|null>(null);
  const base=`/tasks/${encodeURIComponent(taskId)}/apply-previews/${encodeURIComponent(selectionId)}`;
  async function inspect(){
    setBusy(true);setError('');try{setPreview(await api.get<Preview>(base));setOpen(true);if(!request.current)setAck(false)}catch{setError('انتخاب معتبر نیست یا اصل تغییر کرده است؛ پیش‌نمایش تازه بسازید.')}finally{setBusy(false)}
  }
  async function apply(){
    if(!preview||busy)return;setBusy(true);onBusy(true);setError('');
    try{
      request.current??={idempotency_key:crypto.randomUUID(),confirm:true,quality_ack:ack};
      const result=await api.post<{id:string}>(base+'/apply',request.current);
      window.location.href=`/tasks?task=${encodeURIComponent(taskId)}&view=result&operation=${encodeURIComponent(result.id)}`;
    }catch{setError('اعمال تأیید نشد. درخواست را با همان شناسه می‌توان بازخوانی کرد؛ اصل را پیش از تصمیم تازه بررسی کنید.');setBusy(false);onBusy(false)}
  }
  const verified=preview?.quality_status==='verified_snapshot';
  return <><Button size="xs" disabled={disabled||busy} onClick={()=>void inspect()}>اعمال انتخاب روی اصل</Button>{error&&!open&&<p role="alert" className="text-danger text-xs">{error}</p>}
    <Dialog open={open} onOpenChange={value=>{if(!busy)setOpen(value)}}><DialogContent title={`اعمال ${preview?.files.length??0} فایل روی پروژهٔ اصلی`} description="این اقدام فایل‌های مقصد را تغییر می‌دهد. نسخهٔ قبل برای بازگردانی محدود حفظ می‌شود؛ تغییر تازهٔ کاربر بازنویسی نمی‌شود.">
      <div className="flex min-h-0 flex-col gap-3 overflow-auto px-6 text-xs">
        <p>{preview?.destination.name}</p><code dir="ltr" className="block overflow-auto rounded border p-2">{preview?.destination.root}</code>
        <ul className="flex max-h-48 flex-col gap-2 overflow-auto">{preview?.files.map(file=><li key={file.path} className="flex gap-3"><span className={file.kind==='deleted'?'text-danger':'text-muted-foreground'}>{labels[file.kind]??file.kind}</span><bdi>{file.path}</bdi></li>)}</ul>
        <p className={verified?'text-success':'text-warning'}>{verified?'بررسی‌های همین snapshot موفق بوده‌اند.':'این نسخه بررسی موفق معتبر ندارد؛ اعمال به معنی تأیید کیفیت نیست.'}</p>
        <code dir="ltr" className="truncate text-muted-foreground">{preview?.candidate_manifest_hash}</code>
        {!verified&&<label className="flex items-start gap-2 leading-6"><input type="checkbox" checked={ack} disabled={request.current!==null} onChange={event=>setAck(event.target.checked)}/>با آگاهی از نبود بررسی موفق معتبر، همین فایل‌ها را اعمال می‌کنم.</label>}
        {error&&<p role="alert" className="text-danger">{error}</p>}
      </div>
      <div className="flex gap-2 p-6"><Button disabled={busy||!preview||(!verified&&!ack)} onClick={()=>void apply()}>{busy?'در حال ثبت اعمال…':'تأیید و اعمال روی پروژهٔ اصلی'}</Button><Button variant="outline" disabled={busy} onClick={()=>setOpen(false)}>بازگشت به بازبینی</Button></div>
    </DialogContent></Dialog>
  </>;
}
