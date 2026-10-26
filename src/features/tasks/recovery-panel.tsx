'use client';
import { useEffect,useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { RestoreRecovery } from './restore-recovery';
import { ManualRecovery } from './manual-recovery';

type Recovery={revision:number;processes_stopped:boolean;working_available:boolean;working_hash:string|null;working_revision:number|null;skill_hash:string|null;snapshot_identity_valid:boolean;baseline_hash:string|null;actions:{operation_id:string;invocation_key:string;state:string}[];apply_operations:{id:string;state:string}[]};
export function RecoveryPanel({taskId,onRecovered}:{taskId:string;onRecovered:()=>void}){
  const [state,setState]=useState<Recovery|null>(null);
  const [busy,setBusy]=useState(false);
  const [consent,setConsent]=useState(false);
  const [error,setError]=useState('');
  const base=`/tasks/${encodeURIComponent(taskId)}/recovery`;
  useEffect(()=>{let disposed=false;void api.get<Recovery>(base).then(value=>{if(!disposed)setState(value)}).catch(()=>{if(!disposed)setError('خواندن وضعیت بازیابی ممکن نشد.')});return()=>{disposed=true}},[base]);
  async function stop(){setBusy(true);setError('');try{setState(await api.post<Recovery>(base+'/stop-orphans',{confirm:true}));setConsent(false)}catch{setError('توقف اجرای قبلی تأیید نشد. اگر فرمان کانتینری داشته، Docker باید در دسترس باشد؛ چیزی دوباره اجرا نشد.')}finally{setBusy(false)}}
  async function keep(){if(!state)return;setBusy(true);setError('');try{await api.post(base+'/keep-current',{confirm:true,expected_revision:state.revision,expected_working_hash:state.working_hash});onRecovered()}catch{setError('نسخه تغییر کرده یا بازیابی اختصاصی عملیات لازم است؛ فایل‌ها دست‌نخورده‌اند.');setState(await api.get<Recovery>(base).catch(()=>null));setConsent(false)}finally{setBusy(false)}}
  async function rollback(operationId:string){if(!state)return;setBusy(true);setError('');try{await api.post(base+'/skill-repins/'+encodeURIComponent(operationId)+'/rollback',{confirm:true,expected_working_revision:state.working_revision,expected_working_hash:state.working_hash,expected_skill_hash:state.skill_hash});onRecovered()}catch{setError('بازگردانی مهارت تأیید نشد؛ نسخهٔ بایگانی یا فایل‌های فعلی نیازمند بررسی است.')}finally{setBusy(false)}}
  async function migrate(){if(!state)return;setBusy(true);setError('');try{await api.post(base+'/migrate-snapshot',{confirm:true,expected_working_hash:state.working_hash,expected_baseline_hash:state.baseline_hash});onRecovered()}catch{setError('مهاجرت snapshot تأیید نشد؛ فایل‌ها یا نسخهٔ اولیه نیازمند بررسی‌اند.')}finally{setBusy(false)}}
  const specialized=state?.actions.some(action=>/^(restore|skill-repin|manual-edit):/.test(action.invocation_key));
  return <section aria-label="بازیابی کار" className="mx-4 my-2 max-h-[45dvh] shrink-0 space-y-3 overflow-y-auto rounded-xl border border-warning bg-warning-soft p-4 text-xs leading-6">
    <h2 className="font-semibold">این کار به بازیابی نیاز دارد</h2>
    <p>اجرای قبلی خودکار تکرار نمی‌شود. ابتدا پایان فرایند قبلی را تأیید کنید، سپس فایل‌های فعلی را بازبینی کنید. نتیجهٔ نامعلوم، موفقیت محسوب نمی‌شود.</p>
    {!state?<p role="status">وضعیت بازیابی هنوز دریافت نشده است.</p>:<>
      <p role="status">{state.processes_stopped?'فرایندهای ثبت‌شده متوقف‌اند؛ کیفیت فایل‌ها هنوز تأیید نشده است.':'پایان فرایندهای قبلی تأیید نشده است.'}</p>
      {!state.processes_stopped&&<Button variant="outline" size="sm" disabled={busy} onClick={()=>void stop()}>بررسی و توقف فرایندهای قبلی</Button>}
      {state.working_available?<Link className="text-primary underline" href={'/tasks?task='+encodeURIComponent(taskId)+'&view=changes'}>بازبینی نسخهٔ کاری فعلی</Link>:<p className="text-warning">نسخهٔ کاری موجود نیست؛ از روی پروژهٔ فعلی بازسازی نمی‌شود.</p>}
      {state.apply_operations.map(operation=><p key={operation.id}><Link className="text-primary underline" href={'/tasks?task='+encodeURIComponent(taskId)+'&view=result&operation='+encodeURIComponent(operation.id)}>بازکردن نتیجه و بازیابی اعمال روی اصل</Link></p>)}
      {state.processes_stopped&&state.working_hash&&state.actions.filter(action=>action.invocation_key.startsWith('skill-repin:')).map(action=><div key={action.operation_id} className="space-y-2"><p>بازگردانی، نسخهٔ قبلی مهارت‌ها را از بایگانی معتبر برمی‌گرداند؛ نسخهٔ کنارگذاشته‌شده حفظ می‌شود و برنامه باید دوباره تأیید شود.</p><Button size="sm" variant="outline" disabled={busy} onClick={()=>void rollback(action.operation_id)}>بازگرداندن مهارت‌ها به نسخهٔ بایگانی‌شده</Button></div>)}
      {state.processes_stopped&&state.actions.filter(action=>action.invocation_key.startsWith('restore:')).map(action=><RestoreRecovery key={action.operation_id} taskId={taskId} operationId={action.operation_id} onRecovered={onRecovered}/>)}
      {!state.snapshot_identity_valid&&state.processes_stopped&&state.working_hash&&state.baseline_hash&&!state.actions.length&&!state.apply_operations.length&&<div className="space-y-2"><p>هویت snapshot قدیمی موجود نیست. مهاجرت فقط فهرست نسخهٔ اولیهٔ موجود را بازسازی می‌کند؛ فایل‌های کاری و اصل تغییر نمی‌کنند و کیفیت تأییدشده‌ای ایجاد نمی‌شود.</p><label className="flex gap-2"><input type="checkbox" checked={consent} onChange={event=>setConsent(event.target.checked)}/>نسخه‌های موجود حفظ و به‌عنوان دادهٔ قدیمیِ تأییدنشده ثبت شوند.</label><Button size="sm" variant="outline" disabled={!consent||busy} onClick={()=>void migrate()}>مهاجرت هویت snapshot با حفظ فایل‌ها</Button></div>}
      {state.processes_stopped&&state.actions.filter(action=>action.invocation_key.startsWith('manual-edit:')).map(action=><ManualRecovery key={action.operation_id} taskId={taskId} operationId={action.operation_id} onRecovered={onRecovered}/>)}
      {specialized&&<p>این عملیات journal اختصاصی فایل دارد؛ پذیرش عمومی نمی‌تواند آن را حذف یا موفق اعلام کند.</p>}
      {!specialized&&!state.apply_operations.length&&state.processes_stopped&&state.working_hash&&state.snapshot_identity_valid&&<><label className="flex gap-2"><input type="checkbox" checked={consent} onChange={event=>setConsent(event.target.checked)} disabled={busy}/>فایل‌های فعلی را بررسی کردم؛ آن‌ها حفظ شوند و برای ادامه، برنامه و تأیید تازه لازم باشد.</label><Button size="sm" variant="outline" disabled={!consent||busy} onClick={()=>void keep()}>حفظ نسخهٔ فعلی بدون تأیید کیفیت</Button></>}
    </>}
    {error&&<p role="alert" className="text-danger">{error}</p>}
  </section>;
}
