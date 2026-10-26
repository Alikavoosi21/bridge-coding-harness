'use client';

import { useEffect,useMemo,useState } from 'react';
import { Button } from '@/components/ui/button';
import { Alert,AlertDescription } from '@/components/ui/shadcn/alert';
import { StateMotion } from '@/components/shared/state-motion';
import { Tool,ToolHeader,ToolContent,ToolOutput } from '@/components/ai-elements/tool';
import { createBrowserClient } from '@/lib/harness/browser';
import type { CheckEvidence,TaskChecks,HarnessTaskSnapshot } from '@/lib/harness/client';
import { RepairDecision } from './repair-decision';

const labels:Record<string,string>={passed:'موفق',failed:'ناموفق',skipped:'اجرا نشده',not_configured:'تنظیم نشده',stopped:'متوقف',timed_out:'پایان مهلت',stale:'نیاز به بررسی مجدد'};
const qualityLabels:Record<TaskChecks['quality']['quality_status'],string>={verified_snapshot:'بررسی‌های الزامی این نسخه موفق بودند',failed:'بررسی‌های الزامی ناموفق‌اند',stale:'نسخه تغییر کرده؛ دوباره بررسی کنید',not_verified:'این نسخه هنوز تأیید نشده است'};
const failureLabels={assertion:'شکست آزمون',installation:'خطای نصب وابستگی',network:'خطای اتصال شبکه',runtime:'خطای محیط اجرا'};

export function VerificationPanel({taskId,status,revision,onTask,onReview}:{taskId:string;status:string|null;revision:number;onTask:(task:HarnessTaskSnapshot)=>void;onReview:()=>void}){
  const client=useMemo(()=>createBrowserClient(),[]);
  const [data,setData]=useState<TaskChecks|null>(null);
  const [error,setError]=useState(false);
  const [loading,setLoading]=useState(true);
  const [refresh,setRefresh]=useState(0);
  const [outputPhase,setOutputPhase]=useState<Record<string,'baseline'|'current'>>({});
  useEffect(()=>{setData(null);setError(false);setOutputPhase({})},[taskId]);
  useEffect(()=>{
    const controller=new AbortController();let busy=false;
    const read=async()=>{
      if(busy)return;busy=true;setLoading(true);
      try{const result=await client.checks(taskId,controller.signal);if(!controller.signal.aborted){setData(result);setError(false)}}
      catch{if(!controller.signal.aborted)setError(true)}finally{busy=false;if(!controller.signal.aborted)setLoading(false)}
    };
    void read();
    const timer=['executing','verifying','repairing'].includes(status??'')?setInterval(()=>void read(),3000):undefined;
    return()=>{controller.abort();clearInterval(timer)};
  },[client,taskId,status,revision,refresh]);
  const working=data?.items.filter(item=>item.target_kind==='working_copy')??[];
  const ids=[...new Set([...(data?.required??[]),...working.map(item=>item.details.check_id)])];
  const latest=(id:string,phase:'baseline'|'current')=>working.filter(item=>item.details.check_id===id&&item.details.phase===phase).at(-1);
  const stale=(row:CheckEvidence|undefined)=>row&&(data?.input_manifest_hash!==row.input_manifest_hash||data?.profile_hash!==row.profile_hash||data?.runtime_fingerprint!==row.runtime_fingerprint);
  return <section aria-label="بررسی کیفیت" className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
    <div className="flex items-center gap-3"><h2 className="flex-1 text-sm font-semibold">بررسی کیفیت نسخهٔ کاری</h2><Button size="sm" variant="outline" onClick={()=>setRefresh(value=>value+1)}>بازخوانی بررسی‌ها</Button></div>
    {error&&<Alert variant="destructive"><AlertDescription>خواندن نتیجه‌ها ممکن نشد؛ نتیجهٔ تازه‌ای تأیید نمی‌شود.</AlertDescription></Alert>}
    {!data?<p className="text-muted-foreground text-xs">در حال خواندن بررسی‌ها…</p>:<>
      <div role="status" className="flex items-center gap-3 rounded-lg border bg-surface p-3">
        {!error&&status==='repairing'?<StateMotion state="correcting" size={32}/>:!error&&!loading&&!['executing','verifying','planning'].includes(status??'')&&data.quality.quality_status==='verified_snapshot'?<StateMotion state="success" size={32}/>:null}
        <p className="text-sm">{error?'نتیجهٔ تازه در دسترس نیست؛ داده‌های زیر آخرین ثبت‌اند.':loading?'در حال بازخوانی نتیجه‌ها؛ داده‌های زیر آخرین ثبت‌اند.':qualityLabels[data.quality.quality_status]}</p>
      </div>
      {data.quality.baseline_missing&&<p className="text-warning text-xs">نتیجهٔ اولیهٔ معتبر پیش از تغییر موجود نیست؛ موفقیت بررسی فعلی جای آن را نمی‌گیرد.</p>}
      {data.quality.profile_changed&&<p className="text-warning text-xs">تنظیمات بررسی با برنامهٔ تأییدشده متفاوت است؛ برنامه را بازنگری و دوباره تأیید کنید.</p>}
      {data.quality.check_inputs_changed&&<p className="text-warning text-xs">فایل‌های معیار بررسی تغییر کرده‌اند؛ scope برنامه و مجوز اجرای این معیارها باید دوباره بازبینی شوند.</p>}
      <p className="text-muted-foreground text-xs">اصلاح انجام‌شده: {data.repair_budget.total_attempts.toLocaleString('fa-IR')} از {data.repair_budget.allowed.toLocaleString('fa-IR')} · باقی‌مانده: {Math.max(0,data.repair_budget.allowed-data.repair_budget.total_attempts).toLocaleString('fa-IR')}</p>
      <p className="text-muted-foreground text-xs leading-6">زمان فعال ثبت‌شده: {Math.ceil(data.execution_budget.active_ms/1000).toLocaleString('fa-IR')} از {Math.ceil(data.execution_budget.max_active_ms/1000).toLocaleString('fa-IR')} ثانیه · مدل: {data.execution_budget.model_calls.toLocaleString('fa-IR')} از {data.execution_budget.max_model_calls.toLocaleString('fa-IR')} · ابزار: {data.execution_budget.tool_calls.toLocaleString('fa-IR')} از {data.execution_budget.max_tool_calls.toLocaleString('fa-IR')} · هزینه: نامشخص</p>
      {status==='awaiting_decision'&&!error&&<RepairDecision key={taskId} taskId={taskId} revision={revision} budget={data.repair_budget} onTask={onTask} onReview={onReview}/>}
      {ids.length===0?<p className="text-muted-foreground rounded-lg border p-4 text-xs">بررسی کیفیت تنظیم نشده است. فرمان‌ها را در آمادگی پروژه بازبینی کنید؛ این حالت موفقیت نیست.</p>:<div className="shrink-0 overflow-x-auto rounded-lg border"><table className="w-full text-start text-xs"><thead className="bg-surface"><tr><th className="p-3 text-start">بررسی / فرمان</th><th className="p-3 text-start">پیش از تغییر</th><th className="p-3 text-start">نسخهٔ فعلی</th></tr></thead><tbody>{ids.map(id=>{
        const baseline=latest(id,'baseline'),current=latest(id,'current');
        return <tr key={id} className="border-t align-top"><td className="p-3"><p>{id}{data.required.includes(id)?' · الزامی':''}</p><code dir="ltr" className="mt-1 block whitespace-pre-wrap break-all text-muted-foreground">{current?.details.command??baseline?.details.command??'فرمان هنوز اجرا نشده'}</code></td><td className="p-3">{baseline?labels[baseline.outcome]:'ثبت نشده'}{baseline?.outcome==='failed'&&<p className="mt-1 text-warning">پیش از تغییر هم ناموفق بود</p>}</td><td className="p-3">{current?(stale(current)?labels.stale:labels[current.outcome]):'اجرا نشده'}{current&&<p className="mt-1 text-muted-foreground">{new Date(current.created_at*1000).toLocaleTimeString('fa-IR')}</p>}</td></tr>;
      })}</tbody></table></div>}
      {ids.map(id=>{
        const baseline=latest(id,'baseline'),current=latest(id,'current');
        const phase=outputPhase[id]??(current?'current':'baseline');
        const item=(phase==='baseline'?baseline:current)??current??baseline;
        return item?<Tool key={id} className="shrink-0"><ToolHeader title={`خروجی ${id}`} state={item.outcome==='passed'?'output-available':'output-error'} statusLabel={`${labels[item.outcome]}${item.details.phase==='current'&&stale(item)?' · قدیمی':''}`}/><ToolContent>
          <label className="mb-2 flex flex-wrap items-center gap-2 text-xs">نمایش نتیجه<select aria-label={`نسخهٔ خروجی ${id}`} value={item.details.phase} onChange={event=>setOutputPhase(previous=>({...previous,[id]:event.target.value as 'baseline'|'current'}))} className="bg-surface rounded border p-1 focus-visible:outline-2 focus-visible:outline-ring">{baseline&&<option value="baseline">پیش از تغییر</option>}{current&&<option value="current">نسخهٔ فعلی ثبت‌شده</option>}</select></label>
          <p className="mb-2 text-xs text-muted-foreground">ورودی بررسی: <code dir="ltr" className="inline-block font-mono" title={item.input_manifest_hash}>{item.input_manifest_hash.slice(0,12)}</code> · {new Date(item.created_at*1000).toLocaleString('fa-IR')}</p>
          {item.outcome==='failed'&&<p className="mb-2 text-xs text-danger">{item.details.failure_kind?failureLabels[item.details.failure_kind]:'نوع شکست از کد خروج به‌تنهایی مشخص نیست.'}</p>}
          {item.details.truncated&&<p className="text-warning text-xs">خروجی کوتاه شده است.</p>}<ToolOutput output={item.details.output}/>
        </ToolContent></Tool>:null;
      })}
      <p className="text-muted-foreground text-xs">این وضعیت برای نسخهٔ کاری است؛ مقصدِ فایل‌های انتخاب‌شده برای اعمال، جداگانه باید بررسی شود.</p>
    </>}
  </section>;
}
