'use client';
import { useState } from 'react';
import { ShieldCheckIcon,PencilSimpleIcon,ArrowClockwiseIcon } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { Badge,Textarea } from '@/components/ui/primitives';
import { Dialog,DialogContent } from '@/components/ui/overlays';
import type { HarnessApproval } from '@/lib/harness/client';
import type { TaskControls } from './use-task-controls';
import type { HarnessBudgetData } from '@/lib/harness/projection';
import { Confirmation,ConfirmationActions,ConfirmationAction } from '@/components/ai-elements/confirmation';

function Review({approval,controls,mode,waiting}:{approval:HarnessApproval;controls:TaskControls;mode?:string;waiting:boolean}) {
  const [grant,setGrant]=useState(false);
  const [editing,setEditing]=useState(false);
  const [detail,setDetail]=useState(false);
  const [text,setText]=useState('');
  const [invalid,setInvalid]=useState<string|null>(null);
  const [reason,setReason]=useState('');
  const request=approval.request;
  if(!request)return <p className="text-muted-foreground text-xs">این درخواست قدیمی به بازبینی تازه نیاز دارد.</p>;
  const command=typeof request.args.command==='string'?request.args.command:null;
  const reasons:Record<string,string>={network:'این ابزار دسترسی شبکه می‌خواهد؛ اتصال سرویس مدل، مجوز این ابزار نیست.',skill_script:'اجرای script مهارت هم به تأیید همین فرمان و نسخهٔ ثابت نیاز دارد؛ فعال بودن Skill مجوز اجرا نیست.',installation:'نصب وابستگی به تأیید جداگانه نیاز دارد؛ حتی در حالت خودکار.',check_change:'این اقدام فایل آزمون یا معیار بررسی را تغییر می‌دهد؛ هر بار تأیید صریح لازم است.',check_inputs_changed:'فایل‌های معیار بررسی تغییر کرده‌اند؛ نتیجه با معیار قبلی یکسان نیست. اجرای این نسخه به تأیید تازه نیاز دارد.',first_verifier:'این فرمانِ بررسی کیفیت برای نخستین بار در این تنظیمات اجرا می‌شود.',task_consent:'برای این اقدام، مجوز مشخص و معتبر همین کار لازم است.'};
  const repeatable=!['network','installation','check_change','skill_script'].includes(request.review?.reason??'');
  const effects:Record<string,string>={command:'فرمان می‌تواند در نسخهٔ کاری فایل ایجاد، ویرایش یا حذف کند؛ اثر دقیق به کد فرمان بستگی دارد.',file_write:'این ابزار نسخهٔ کاری فایل یا مسیر زیر را تغییر می‌دهد.',read:'این ابزار دادهٔ مسیر زیر را می‌خواند.',connector:'اثر این ابزار را از نام و آرگومان‌های کامل آن بازبینی کنید.'};
  const busy=controls.busy!==null || !waiting;
  const openEdit=()=>{setText(command??JSON.stringify(request.args,null,2));setInvalid(null);setEditing(true)};
  const save=async()=>{
    try {
      const args=command!==null?{...request.args,command:text}:JSON.parse(text) as Record<string,unknown>;
      if(!args || Array.isArray(args) || typeof args!=='object')throw new Error('آرگومان‌ها باید یک شیء JSON باشند.');
      if(await controls.edit(approval,args))setEditing(false);
    }catch(error){setInvalid(error instanceof Error?error.message:'متن ویرایش معتبر نیست.')}
  };
  return <Confirmation approval={{id:approval.id}} state="approval-requested" aria-label="درخواست تأیید اقدام" className="rounded-xl p-3 text-xs">
    <header className="flex items-center gap-2"><ShieldCheckIcon className="text-warning size-4"/><h2 className="flex-1 font-semibold">این اقدام به تأیید شما نیاز دارد</h2><Badge tone="warning">نسخهٔ {approval.revision.toLocaleString('fa-IR')}</Badge></header>
    <p className="text-muted-foreground mt-1 leading-5">{reasons[request.review?.reason??'task_consent']??reasons.task_consent}</p>
    <p className="leading-5">{effects[request.review?.effect??(command?'command':'connector')]??effects.connector} اصل پروژه با این مجوز تغییر نمی‌کند.</p>
    {request.review?.path&&<code dir="ltr" className="block break-all font-mono">{request.review.path}</code>}
    <pre dir="ltr" className="bg-background mt-2 max-h-24 overflow-auto rounded-lg border p-2 font-mono text-xs leading-5 whitespace-pre-wrap break-all">{command??`${request.tool}\n${JSON.stringify(request.args,null,2)}`}</pre>
    <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-2"><span>پوشه:</span><code dir="ltr">{request.cwd}</code><span>·</span><code dir="ltr">{request.tool}</code><button type="button" className="text-primary ms-auto hover:underline" onClick={()=>setDetail(true)}>جزئیات مجوز</button></div>
    {mode==='grant' && repeatable && <label className="mt-2 flex items-start gap-2 leading-5"><input type="checkbox" checked={grant} onChange={event=>setGrant(event.target.checked)} disabled={busy} className="mt-1 accent-[var(--primary)]"/>تکرار همین فرمان با همین تنظیمات تا پایان این کار مجاز باشد</label>}
    {!repeatable&&<p className="text-warning mt-2 leading-5">این اقدام هر بار تأیید جدا می‌خواهد؛ مجوز تکرار برای آن صادر نمی‌شود.</p>}
    <ConfirmationActions className="mt-2">
      <ConfirmationAction disabled={busy} onClick={()=>void controls.decide(approval,'approve',grant)}>تأیید و اجرا</ConfirmationAction>
      <ConfirmationAction variant="outline" disabled={busy} onClick={openEdit}><PencilSimpleIcon/>ویرایش اقدام</ConfirmationAction>
      <ConfirmationAction variant="outline" disabled={busy} onClick={()=>void controls.decide(approval,'reject',false,reason)}>رد درخواست</ConfirmationAction>
      <input aria-label="دلیل رد درخواست" value={reason} onChange={event=>setReason(event.target.value)} placeholder="دلیل رد (اختیاری)" maxLength={1000} className="border-input bg-background min-w-32 flex-1 rounded-lg border px-2 py-2 outline-none focus-visible:border-ring"/>
    </ConfirmationActions>
    <Dialog open={editing} onOpenChange={setEditing}><DialogContent title="ویرایش اقدام" description="ذخیره، درخواست تازه‌ای برای تأیید می‌سازد؛ چیزی اجرا نمی‌شود." className="max-w-xl">
      <Textarea aria-label="ویرایش فرمان یا آرگومان‌ها" dir="ltr" value={text} onChange={event=>setText(event.target.value)} rows={7} autoFocus className="font-mono text-xs"/>
      {invalid&&<p role="alert" className="text-danger text-xs">{invalid}</p>}
      <Button type="button" disabled={busy} onClick={()=>void save()}>ذخیره و بازبینی تازه</Button>
    </DialogContent></Dialog>
    <Dialog open={detail} onOpenChange={setDetail}><DialogContent title="جزئیات مجوز" description="مجوز به همین کار، نسخهٔ برنامه و تنظیمات اقدام محدود است.">
      <dl className="space-y-2 text-xs"><dt>مدت</dt><dd>این اقدام؛ با انتخاب تکرار، حداکثر تا پایان همین کار</dd><dt>شبکهٔ sandbox</dt><dd>{request.review?.sandbox_network?'این فرمان با مجوز موقت شبکه بازبینی شده است؛ انقضا یا لغو مجوز، تأیید را نامعتبر می‌کند.':'غیرفعال؛ اتصال سرویس مدل مجوز شبکهٔ sandbox نیست.'}</dd><dt>نسخهٔ برنامه</dt><dd>{request.plan_revision}</dd><dt>شناسهٔ عملیات</dt><dd dir="ltr" className="break-all font-mono">{approval.action_id}</dd><dt>Fingerprint</dt><dd dir="ltr" className="break-all font-mono">{approval.action_hash}</dd></dl>
    </DialogContent></Dialog>
  </Confirmation>;
}

export function ApprovalDock({controls,mode,waiting,budget}:{controls:TaskControls;mode?:string;waiting:boolean;budget?:HarnessBudgetData|null}) {
  const pending=controls.approvals.filter(row=>row.state==='pending');
  return <div className="flex flex-col gap-2">
    {waiting&&<div aria-label="بودجهٔ تصمیم" className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
      {budget?<><span>مدل: {budget.model_calls.toLocaleString('fa-IR')} مصرف؛ {Math.max(0,budget.max_model_calls-budget.model_calls).toLocaleString('fa-IR')} باقی</span><span>ابزار: {budget.tool_calls.toLocaleString('fa-IR')} مصرف؛ {Math.max(0,budget.max_tool_calls-budget.tool_calls).toLocaleString('fa-IR')} باقی</span><span>زمان فعال باقی: {Math.ceil(Math.max(0,budget.max_active_ms-budget.active_ms)/1000).toLocaleString('fa-IR')} ثانیه</span></>:<span>بودجه هنوز از موتور دریافت نشده است.</span>}
      <span>تأیید، شروع فوری را تضمین نمی‌کند؛ موتور باید محیط اجرا را در اختیار بگیرد.</span>
    </div>}
    {controls.error&&<div role="alert" className="bg-danger-soft text-danger flex items-center gap-2 rounded-lg p-2 text-xs"><span className="flex-1">{controls.error}</span><Button size="xs" variant="outline" onClick={controls.refresh}><ArrowClockwiseIcon/>بازخوانی</Button></div>}
    {pending.length>0&&<><p className="text-muted-foreground text-[11px]">{pending.length.toLocaleString('fa-IR')} درخواست منتظر تصمیم</p><Review key={pending[0].id} approval={pending[0]} controls={controls} mode={mode} waiting={waiting}/></>}
    {waiting && pending.length===0&&controls.approvals.length>0&&<Button size="sm" variant="outline" disabled={controls.busy!==null} onClick={()=>void controls.resume()}>ادامه پس از تصمیم‌های ثبت‌شده</Button>}
  </div>;
}
