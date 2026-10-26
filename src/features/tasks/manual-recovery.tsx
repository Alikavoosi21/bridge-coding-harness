'use client';
import { useEffect,useRef,useState } from 'react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
type Detail={path:string;before:string;requested:string;current:{content:string|null;hash:string;working_revision:number;working_manifest_hash:string}};
export function ManualRecovery({taskId,operationId,onRecovered}:{taskId:string;operationId:string;onRecovered:()=>void}){
  const [detail,setDetail]=useState<Detail|null>(null);
  const [consent,setConsent]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const key=useRef(crypto.randomUUID());
  const base=`/tasks/${encodeURIComponent(taskId)}/manual-edits/${encodeURIComponent(operationId)}`;
  useEffect(()=>{let alive=true;void api.get<Detail>(base).then(value=>{if(alive)setDetail(value)}).catch(()=>{if(alive)setError('نسخه‌های ویرایش قابل‌خواندن نیستند؛ چیزی بازنویسی نشده است.')});return()=>{alive=false}},[base]);
  async function keep(){if(!detail)return;setBusy(true);try{await api.post(base+'/reconciliations',{accept_current:true,idempotency_key:key.current,expected_working_revision:detail.current.working_revision,expected_manifest_hash:detail.current.working_manifest_hash,expected_file_hash:detail.current.hash});onRecovered()}catch{setError('فایل تغییر کرده است یا بازیابی تأیید نشد؛ نسخه‌ها را دوباره باز کنید.')}finally{setBusy(false)}}
  return <section aria-label="بازیابی ویرایش دستی" className="space-y-3 rounded border p-3"><h3 className="font-semibold">ویرایش دستی نیمه‌تمام · <bdi>{detail?.path}</bdi></h3>{detail&&<><div className="grid gap-2 lg:grid-cols-3">{[['قبل',detail.before],['درخواست ویرایش',detail.requested],['نسخهٔ فعلی',detail.current.content??'فایل متنی قابل‌خواندن نیست']] .map(([label,text])=><div key={label} className="min-w-0"><p>{label}</p><pre dir="ltr" className="max-h-32 overflow-auto rounded border bg-background p-2 font-mono text-[11px]">{text}</pre></div>)}</div><label className="flex gap-2"><input type="checkbox" checked={consent} onChange={event=>setConsent(event.target.checked)}/>همین نسخهٔ فعلی حفظ شود؛ درخواست قبلی دوباره اجرا نشود.</label><Button size="sm" variant="outline" disabled={!consent||busy||detail.current.content===null} onClick={()=>void keep()}>پذیرش نسخهٔ فعلی ویرایش دستی</Button></>}{error&&<p role="alert" className="text-danger">{error}</p>}</section>;
}
