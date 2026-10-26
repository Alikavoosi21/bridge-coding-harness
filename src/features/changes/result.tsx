'use client';

import { useEffect,useRef,useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';
import { Dialog,DialogContent } from '@/components/ui/overlays';
import { OutputActions } from '@/features/tasks/output-actions';

type FileRow={path:string;state:string;comparison:string;observed_hash:string|null;restorable?:boolean};
type Result={id:string;state:string;files:FileRow[];restore_operations?:RestoreResult[];candidate_quality:{quality_status:string};original_quality_status:string;original_matches_candidate:boolean;original_manifest_hash:string;working_revision:number;working_manifest_hash:string};
type RestorePreview={original_manifest_hash:string;files:FileRow[]};
type RestoreResult={state:string;files:{path:string;state:string}[]};
const states:Record<string,string>={applied:'اعمال شد',prepared:'آمادهٔ اجرا؛ هنوز قطعی نیست',applying:'نتیجه در انتظار بررسی',partial:'اعمال ناقص',unknown:'نتیجه نامعلوم',pending:'اجرا نشده',writing:'نوشتن نامعلوم',conflict:'تعارض',reconciled:'نسخهٔ فعلی پذیرفته شد',restored:'بازگردانده شد',not_applied:'اعمال نشده',kept_current:'نسخهٔ فعلی حفظ شد'};
const quality:Record<string,string>={verified_snapshot:'بررسی‌های snapshot موفق بودند',failed:'بررسی‌ها ناموفق‌اند',stale:'شواهد بررسی قدیمی‌اند',not_verified:'بررسی موفق معتبر ندارد'};

export function ApplyResult({taskId,operationId}:{taskId:string;operationId:string}){
  const [result,setResult]=useState<Result|null>(null);
  const [preview,setPreview]=useState<RestorePreview|null>(null);
  const [selected,setSelected]=useState<string[]>([]);
  const [dialog,setDialog]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [restored,setRestored]=useState<RestoreResult|null>(null);
  const request=useRef<Record<string,unknown>|null>(null);
  const reconcileKey=useRef<string|null>(null);
  const generation=useRef(0);
  const base=`/tasks/${encodeURIComponent(taskId)}/apply-operations/${encodeURIComponent(operationId)}`;
  async function refresh(){const version=++generation.current;const data=await api.get<Result>(base);if(version===generation.current)setResult(data);return data}
  useEffect(()=>{void refresh().catch(()=>setError('نتیجه در دسترس نیست؛ بازخوانی، عملیات را اجرا نمی‌کند.'));return()=>{generation.current++}},[base]);
  async function prepareRestore(){setBusy(true);setError('');try{await refresh();setPreview(await api.get<RestorePreview>(base+'/restore-preview'));setSelected([]);request.current=null;setDialog(true)}catch{setError('پیش‌نمایش بازگردانی آماده نشد؛ فایل‌ها را دوباره بررسی کنید.')}finally{setBusy(false)}}
  async function restore(){
    if(!preview||!result||!selected.length)return;setBusy(true);setError('');
    try{request.current??={idempotency_key:crypto.randomUUID(),confirm:true,paths:selected,expected_original_hash:preview.original_manifest_hash,expected_working_revision:result.working_revision,expected_working_hash:result.working_manifest_hash};const receipt=await api.post<RestoreResult>(base+'/restores',request.current);setRestored(receipt);setDialog(false);await refresh()}catch{setError('بازگردانی تأیید نشد؛ تعارض یا نتیجهٔ نامعلوم را بررسی کنید. هیچ تکرار خودکاری انجام نمی‌شود.')}finally{setBusy(false)}
  }
  async function keepCurrent(){if(!result)return;setBusy(true);setError('');try{reconcileKey.current??=crypto.randomUUID();await api.post(base+'/reconciliations',{idempotency_key:reconcileKey.current,accept_current:true,expected_original_hash:result.original_manifest_hash,expected_working_revision:result.working_revision,expected_working_hash:result.working_manifest_hash});await refresh()}catch{setError('پذیرش نسخهٔ فعلی ممکن نشد؛ ابتدا وضعیت و hash تازه را بازخوانی کنید.')}finally{setBusy(false)}}
  const unresolved=result&&['unknown','partial','prepared','applying'].includes(result.state);
  return <section className="flex min-h-0 flex-1 flex-col" aria-label="نتیجهٔ اعمال">
    <OutputActions taskId={taskId} status="closed"/>
    <header className="flex shrink-0 flex-wrap items-center gap-3 border-b p-4"><Button asChild size="sm" variant="outline"><Link href={'/tasks?task='+encodeURIComponent(taskId)+'&view=changes'}>بازگشت به بازبینی</Link></Button><h1 className="flex-1 text-sm font-semibold">نتیجهٔ اعمال روی پروژهٔ اصلی</h1><Button size="sm" variant="outline" disabled={busy} onClick={()=>{setError('');void refresh().catch(()=>setError('بازخوانی نتیجه ممکن نشد.'))}}>بازخوانی وضعیت</Button></header>
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4 lg:p-6">
      {error&&<p role="alert" className="rounded border border-danger p-3 text-xs text-danger">{error}</p>}
      {!result?<p role="status">در حال خواندن نتیجهٔ ثبت‌شده…</p>:<>
        <div className="grid gap-3 lg:grid-cols-3">
          <section className="rounded-lg border bg-panel p-4"><h2 className="mb-2 text-xs text-muted-foreground">چه تغییر کرد؟</h2><p className="text-sm">{result.files.length} فایل در این عملیات</p><p className="mt-2 text-xs text-muted-foreground">نسخهٔ کاری ایجنت حفظ شده است.</p><code dir="ltr" className="mt-2 block truncate text-xs">{result.working_manifest_hash.slice(0,16)}</code></section>
          <section className="rounded-lg border bg-panel p-4"><h2 className="mb-2 text-xs text-muted-foreground">چه بررسی شد؟</h2><Badge tone={result.candidate_quality.quality_status==='verified_snapshot'?'success':'warning'}>{quality[result.candidate_quality.quality_status]??'کیفیت نامشخص'}</Badge><p className="mt-2 text-xs text-muted-foreground">این شواهد متعلق به snapshot انتخابی است.</p></section>
          <section className="rounded-lg border bg-panel p-4"><h2 className="mb-2 text-xs text-muted-foreground">روی اصل اعمال شد؟</h2><Badge tone={unresolved?'warning':'neutral'}>{states[result.state]??result.state}</Badge><p className="mt-2 text-xs">اصل فعلی: {quality[result.original_quality_status]??'نامشخص'}</p><p className="mt-2 text-xs text-muted-foreground">{result.original_matches_candidate?'اصل فعلی با candidate یکسان است.':'اصل فعلی با candidate یکسان نیست؛ receipt تاریخی کیفیت تازه را تضمین نمی‌کند.'}</p></section>
        </div>
        <ul className="flex flex-col divide-y rounded-lg border">{result.files.map(file=><li key={file.path} className="flex flex-wrap items-center gap-3 p-3 text-xs"><bdi className="min-w-0 flex-1 break-all">{file.path}</bdi><span>{states[file.state]??file.state}</span><code dir="ltr" className="text-muted-foreground">{file.observed_hash?.slice(0,12)??'بدون فایل عادی'}</code><span className="text-muted-foreground">{file.comparison==='after'?'مطابق خروجی اعمال':file.comparison==='before'?'مطابق نسخهٔ قبل':'نسخهٔ فعلی متفاوت'}</span></li>)}</ul>
        {unresolved&&<section className="flex flex-col gap-3 rounded border border-warning p-4 text-xs"><p>فایل‌های pending یا نامعلوم خودکار اجرا نمی‌شوند. hashهای بالا را بررسی کنید؛ این تصمیم فقط همین نسخهٔ فعلی را نگه می‌دارد و فایلی نمی‌نویسد.</p><Button variant="outline" disabled={busy} onClick={()=>void keepCurrent()}>نسخهٔ فعلیِ مشاهده‌شده را می‌پذیرم؛ ادامهٔ اعمال نده</Button></section>}
        {!unresolved&&<Button className="self-start" variant="outline" disabled={busy} onClick={()=>void prepareRestore()}>پیش‌نمایش بازگردانی همین عملیات</Button>}
        {restored&&<section role="status" className="flex flex-col gap-2 rounded border p-4 text-xs"><h2>نتیجهٔ بازگردانی: {states[restored.state]??restored.state}</h2>{restored.files.map(file=><p key={file.path}><bdi>{file.path}</bdi> · {states[file.state]??file.state}</p>)}</section>}
        {!restored&&result.restore_operations?.map((operation,index)=><section key={index} role="status" className="flex flex-col gap-2 rounded border p-4 text-xs"><h2>نتیجهٔ بازگردانی ثبت‌شده: {states[operation.state]??operation.state}</h2>{operation.files.map(file=><p key={file.path}><bdi>{file.path}</bdi> · {states[file.state]??file.state}</p>)}</section>)}
      </>}
    </div>
    <Dialog open={dialog} onOpenChange={value=>{if(!busy)setDialog(value)}}><DialogContent title="بازگردانی فایل‌های همین عملیات" description="فقط فایل‌هایی که هنوز با خروجی apply برابرند قابل بازگردانی‌اند؛ هیچ Git reset یا بازگردانی کل پروژه‌ای انجام نمی‌شود."><ul className="flex max-h-64 flex-col gap-3 overflow-auto px-6 text-xs">{preview?.files.map(file=><li key={file.path}><label className="flex items-start gap-2"><input type="checkbox" aria-label={'بازگردانی '+file.path} checked={selected.includes(file.path)} disabled={!file.restorable||busy||request.current!==null} onChange={event=>setSelected(current=>event.target.checked?[...current,file.path]:current.filter(path=>path!==file.path))}/><bdi>{file.path}</bdi><span className="text-muted-foreground">{file.restorable?'hash مطابق است':'تغییر کرده یا قابل بازگردانی نیست'}</span></label></li>)}</ul>{error&&<p role="alert" className="px-6 text-xs text-danger">{error}</p>}<div className="flex gap-2 p-6"><Button disabled={busy||!selected.length} onClick={()=>void restore()}>تأیید بازگردانی {selected.length} فایل</Button><Button variant="outline" disabled={busy} onClick={()=>setDialog(false)}>انصراف</Button></div></DialogContent></Dialog>
  </section>;
}
