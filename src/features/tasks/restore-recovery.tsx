'use client';
import { useEffect,useState } from 'react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
type Detail={original_manifest_hash:string;working_revision:number;working_manifest_hash:string;files:{path:string;state:string;observed_hash:string|null}[]};
export function RestoreRecovery({taskId,operationId,onRecovered}:{taskId:string;operationId:string;onRecovered:()=>void}){
  const [detail,setDetail]=useState<Detail|null>(null);
  const [consent,setConsent]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const base=`/tasks/${encodeURIComponent(taskId)}/restores/${encodeURIComponent(operationId)}/recovery`;
  useEffect(()=>{let alive=true;void api.get<Detail>(base).then(value=>{if(alive)setDetail(value)}).catch(()=>{if(alive)setError('خواندن journal بازگردانی ممکن نشد.')});return()=>{alive=false}},[base]);
  async function keep(){if(!detail)return;setBusy(true);try{await api.post(base,{confirm:true,expected_original_hash:detail.original_manifest_hash,expected_working_revision:detail.working_revision,expected_working_hash:detail.working_manifest_hash});onRecovered()}catch{setError('فایل‌ها یا عملیات تغییر کرده‌اند؛ دوباره بازبینی کنید.')}finally{setBusy(false)}}
  const labels:Record<string,string>={restored:'مطابق نسخهٔ قبل از اعمال',not_restored:'مطابق خروجی اعمال',kept_current:'نسخهٔ متفاوت کاربر',unsupported:'فایل عادی قابل‌بررسی نیست'};
  return <section aria-label="بازیابی بازگردانی" className="space-y-2 rounded border p-3"><p>نتیجهٔ بازگردانی نامعلوم است؛ فایل‌های فعلی خودکار بازنویسی نمی‌شوند.</p>{detail&&<><ul>{detail.files.map(file=><li key={file.path}><bdi>{file.path}</bdi> · {labels[file.state]??file.state}<code dir="ltr" className="block text-muted-foreground">{file.observed_hash?.slice(0,16)??'بدون فایل عادی'}</code></li>)}</ul><label className="flex gap-2"><input type="checkbox" checked={consent} onChange={event=>setConsent(event.target.checked)}/>وضعیت فایل‌به‌فایل را بررسی کردم؛ همین فایل‌های فعلی حفظ شوند.</label><Button variant="outline" size="sm" disabled={!consent||busy} onClick={()=>void keep()}>حفظ فایل‌های فعلی و بستن بازگردانی نامعلوم</Button></>}{error&&<p role="alert" className="text-danger">{error}</p>}</section>;
}
