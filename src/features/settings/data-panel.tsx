'use client';

import { useEffect,useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input,PathText } from '@/components/ui/primitives';
import { BlockLabel,Row,RowGroup } from '@/components/ui/patterns';
import { Dialog,DialogContent } from '@/components/ui/overlays';
import { api,downloadDiagnostics } from '@/lib/api';

type Cache={id:string;task_id:string;category:string;bytes:number;files:number};
type Storage={preview_hash:string;data_directory:string;disk_free_bytes:number;cache_bytes:number;reclaimable_bytes:number;protected_tasks:number;skipped_entries:number;cache_limit_exceeded:boolean;policy:{retention_days:number;cache_limit_gb:number};items:Cache[]};
type Diagnostic={files:string[];report:Record<string,unknown>;preview_hash:string};
type Export={id:string;path:string;bytes:number};
const size=(value:number)=>`${(value/1024**2).toLocaleString('fa-IR',{maximumFractionDigits:1})} مگابایت`;
const categories:Record<string,string>={dependencies:'وابستگی‌های قابل‌نصب مجدد',cache:'cache ابزارها',temporary_checks:'کپی موقت بررسی'};

export function DataPanel(){
  const [storage,setStorage]=useState<Storage|null>(null);
  const [days,setDays]=useState(30);const [limit,setLimit]=useState(5);
  const [selected,setSelected]=useState<string[]>([]);
  const [confirm,setConfirm]=useState(false);
  const [diagnostic,setDiagnostic]=useState<Diagnostic|null>(null);
  const [exported,setExported]=useState<Export|null>(null);
  const [busy,setBusy]=useState<string|null>(null);
  const [error,setError]=useState('');const [notice,setNotice]=useState('');
  async function refresh(){const value=await api.get<Storage>('/storage/preview');setStorage(value);setDays(value.policy.retention_days);setLimit(value.policy.cache_limit_gb);setSelected([]);return value}
  useEffect(()=>{let alive=true;void api.get<Storage>('/storage/preview').then(value=>{if(alive){setStorage(value);setDays(value.policy.retention_days);setLimit(value.policy.cache_limit_gb)}}).catch(()=>{if(alive)setError('خواندن وضعیت داده‌ها ممکن نشد.')});return()=>{alive=false}},[]);
  async function action(name:string,work:()=>Promise<void>){if(busy)return;setBusy(name);setError('');setNotice('');try{await work()}catch(error){setError(error instanceof Error?error.message:'عملیات انجام نشد.')}finally{setBusy(null)}}
  async function clean(){if(!storage)return;setConfirm(false);await action('cleanup',async()=>{const result=await api.post<{deleted:string[];failed:string[];deleted_bytes:number}>('/storage/cleanup',{confirm:true,preview_hash:storage.preview_hash,item_ids:selected});await refresh();setNotice(`${result.deleted.length.toLocaleString('fa-IR')} cache پاک شد؛ ${size(result.deleted_bytes)} آزاد شد.${result.failed.length?' برخی فایل‌ها پاک نشدند؛ پیش‌نمایش تازه را بررسی کنید.':''}`)})}
  async function exportReport(){if(!diagnostic)return;await action('export',async()=>{setExported(await api.post<Export>('/diagnostics/exports',{confirm:true,preview_hash:diagnostic.preview_hash}));setDiagnostic(null);setNotice('بسته فقط روی همین دستگاه ساخته شد؛ چیزی ارسال نشد.')})}
  const picked=storage?.items.filter(item=>selected.includes(item.id))??[];
  const validPolicy=Number.isInteger(days)&&days>=1&&days<=3650&&Number.isInteger(limit)&&limit>=1&&limit<=50;
  return <div className="space-y-4" aria-label="داده‌ها و عیب‌یابی">
    <BlockLabel>داده‌های محلی محصول</BlockLabel>
    {error&&<p role="alert" className="rounded-lg border border-danger p-3 text-xs text-danger">{error}</p>}
    {notice&&<p role="status" className="rounded-lg border border-primary p-3 text-xs">{notice}</p>}
    {!storage?<p role="status" className="text-xs">در حال خواندن وضعیت ذخیره‌سازی…</p>:<>
      <RowGroup><Row label="پوشهٔ دادهٔ محصول" description={<PathText path={storage.data_directory}/>}><span className="text-xs text-muted-foreground">با پوشهٔ پروژه فرق دارد</span></Row><Row label="فضای آزاد دیسک" description={size(storage.disk_free_bytes)}/><Row label="cache کارهای بستهٔ قابل‌بررسی" description={size(storage.cache_bytes)}/><Row label="قابل آزادسازی پس از تأیید" description={size(storage.reclaimable_bytes)}/></RowGroup>
      <p className="text-xs leading-6 text-muted-foreground">تاریخچه، فایل‌های اصلی و کاری، نسخهٔ اولیه، مهارت‌های ثابت و داده‌های بازیابی پاک نمی‌شوند. {storage.protected_tasks.toLocaleString('fa-IR')} کار محافظت‌شده است. {storage.skipped_entries>0&&`${storage.skipped_entries.toLocaleString('fa-IR')} مورد به‌دلیل محدودیت یا لینک بررسی نشد.`} اندازهٔ cache شامل داده‌های محافظت‌شده نیست.</p>
      <BlockLabel>سیاست پیشنهادی پاک‌سازی</BlockLabel>
      <div className="flex flex-wrap items-end gap-3"><label className="space-y-2 text-xs"><span className="block">حداقل سن cache (روز)</span><Input type="number" min={1} max={3650} value={days} onChange={event=>setDays(Number(event.target.value))} className="w-32"/></label><label className="space-y-2 text-xs"><span className="block">حد پیشنهادی cache (گیگابایت)</span><Input type="number" min={1} max={50} value={limit} onChange={event=>setLimit(Number(event.target.value))} className="w-40"/></label><Button size="sm" variant="outline" disabled={!!busy||!validPolicy} onClick={()=>void action('policy',async()=>{await api.put('/storage/policy',{retention_days:days,cache_limit_gb:limit});await refresh();setNotice('سیاست ذخیره شد؛ پاک‌سازی خودکار اجرا نمی‌شود.')})}>ذخیرهٔ سیاست</Button></div>
      {storage.cache_limit_exceeded&&<p role="status" className="text-xs text-warning">حجم cache قابل‌بررسی از حد پیشنهادی بیشتر است؛ هیچ داده‌ای خودکار حذف نشده است.</p>}
      <div className="flex flex-wrap items-center gap-3"><Button size="sm" variant="outline" disabled={!!busy} onClick={()=>void action('refresh',async()=>{await refresh()})}>تازه‌سازی پیش‌نمایش پاک‌سازی</Button><Button size="sm" variant="outline" disabled={!!busy||!selected.length} onClick={()=>setConfirm(true)}>بازبینی پاک‌سازی انتخاب‌ها</Button></div>
      {!storage.items.length?<p className="text-xs text-muted-foreground">cache قدیمیِ مجاز برای پاک‌سازی وجود ندارد.</p>:<ul className="max-h-64 space-y-2 overflow-auto rounded-lg border p-3">{storage.items.map(item=><li key={item.id}><label className="flex items-start gap-3 text-xs leading-6"><input type="checkbox" checked={selected.includes(item.id)} disabled={!!busy} onChange={event=>setSelected(current=>event.target.checked?[...current,item.id]:current.filter(id=>id!==item.id))}/><span>{categories[item.category]??'cache'} · {size(item.bytes)} · {item.files.toLocaleString('fa-IR')} فایل<code dir="ltr" className="block break-all text-[10px] text-muted-foreground">{item.task_id}</code></span></label></li>)}</ul>}
    </>}
    <BlockLabel>بستهٔ عیب‌یابی محلی</BlockLabel>
    <p className="text-xs leading-6 text-muted-foreground">فقط نسخه‌ها، وضعیت کلی محیط و شمارش‌های فنی. کد، گفتگو، کلید، آدرس سرویس مدل، log خام و مسیر خصوصی وارد بسته نمی‌شوند. ارسال یا upload وجود ندارد.</p>
    <Button size="sm" variant="outline" disabled={!!busy} onClick={()=>void action('preview',async()=>{setDiagnostic(await api.get<Diagnostic>('/diagnostics/preview'))})}>پیش‌نمایش بستهٔ عیب‌یابی</Button>
    {exported&&<section aria-label="بستهٔ ساخته‌شده" className="space-y-3 rounded-lg border bg-panel p-3 text-xs"><p>بستهٔ محلی آماده است · {size(exported.bytes)}</p><PathText path={exported.path}/><Button size="sm" variant="outline" disabled={!!busy} onClick={()=>void action('download',async()=>{const blob=await downloadDiagnostics(exported.id);const url=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download=exported.id+'.zip';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000)})}>دریافت ZIP محلی</Button></section>}
    <Dialog open={confirm} onOpenChange={setConfirm}><DialogContent title="تأیید پاک‌سازی cache" description="فقط انتخاب‌های همین پیش‌نمایش حذف می‌شوند؛ حذف برگشت‌پذیر نیست. تاریخچه و فایل‌های پروژه حفظ می‌شوند."><p className="text-sm">{picked.length.toLocaleString('fa-IR')} مورد · {size(picked.reduce((sum,item)=>sum+item.bytes,0))}</p><Button disabled={!!busy} onClick={()=>void clean()}>تأیید و پاک‌سازی همین cacheها</Button><Button variant="outline" onClick={()=>setConfirm(false)}>انصراف</Button></DialogContent></Dialog>
    <Dialog open={diagnostic!==null} onOpenChange={open=>{if(!open)setDiagnostic(null)}}><DialogContent title="بازبینی بستهٔ عیب‌یابی" description="محتوای واقعی گزارش پیش از ساخت ZIP؛ فقط روی همین دستگاه ذخیره می‌شود."><ul className="text-xs" dir="ltr">{diagnostic?.files.map(file=><li key={file}>{file}</li>)}</ul><pre dir="ltr" className="max-h-64 overflow-auto rounded border bg-background p-3 font-mono text-[11px]">{JSON.stringify(diagnostic?.report,null,2)}</pre><Button disabled={!!busy} onClick={()=>void exportReport()}>تأیید و ساخت ZIP محلی</Button><Button variant="outline" onClick={()=>setDiagnostic(null)}>انصراف</Button></DialogContent></Dialog>
  </div>;
}
