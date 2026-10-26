'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowRightIcon, CpuIcon, EyeIcon, ShieldCheckIcon, StopIcon } from '@phosphor-icons/react';
import { Badge } from '@/components/ui/primitives';
import { Button } from '@/components/ui/button';
import { StateMotion } from '@/components/shared/state-motion';
import { useBackend } from '@/lib/backend';
import { useUi } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Conversation } from './conversation';
import { ActivityPanel, ActivitySummary } from './activity-panel';
import { PlanOnly } from './inspector';
import { PromptInput, composerTool } from './prompt-input';
import { isActiveTaskState, motionFor, stateCaption, taskStateTone } from './status';
import { useTaskChat } from './use-task-chat';
import { useTaskControls } from './use-task-controls';
import { ApprovalDock } from './approval-dock';
import { VerificationPanel } from './verification-panel';
import { SandboxNetwork } from './sandbox-network';
import { RecoveryPanel } from './recovery-panel';
import { ChangesReview } from '@/features/changes/review';
import { OutputActions } from './output-actions';
import { Dialog,DialogContent } from '@/components/ui/overlays';

export function TaskView({ taskId }: { taskId: string }) {
  const chat = useTaskChat({ taskId });
  const controls=useTaskControls(chat,taskId);
  const [permissionsOpen,setPermissionsOpen]=useState(false);
  const workspace = useBackend(s => s.workspace);
  const readiness = useBackend(s => s.readiness);
  const drafts = useUi(s => s.drafts);
  const setDraft = useUi(s => s.setDraft);
  const setActiveThread = useUi(s => s.setActiveThread);
  const draftKey = `task:${taskId}`;
  const draft = drafts[draftKey] ?? '';
  const [tab, setTab] = useState<'conversation' | 'activity' | 'plan' | 'checks' | 'changes'>('conversation');
  useEffect(() => { setActiveThread(taskId); }, [setActiveThread, taskId]);
  const active = isActiveTaskState(chat.status);
  const motion = motionFor(chat.status, chat.snapshot?.outcome);
  const mode = chat.snapshot?.mode;
  const modeName = mode === 'auto' ? 'خودکار در محیط ایزوله' : mode === 'grant' ? 'مجوز برای همین کار' : 'با تأیید';
  const disconnected = chat.connection === 'offline' || chat.connection === 'reconnecting';

  return <div className="flex min-h-0 flex-1 flex-col">
    <header className="border-border flex h-14 shrink-0 items-center gap-3 border-b px-4 lg:px-6">
      <Button asChild variant="muted" size="icon-sm"><Link href="/tasks" aria-label="فهرست کارها"><ArrowRightIcon /></Link></Button>
      {motion && <StateMotion state={motion} size={32} />}
      <h1 className="min-w-0 flex-1 truncate text-sm font-semibold" dir="auto">{chat.snapshot?.title || chat.snapshot?.prompt || 'کار'}</h1>
      <Badge tone={chat.status ? taskStateTone[chat.status] : 'neutral'}>{stateCaption(chat.status, chat.snapshot?.outcome)}</Badge>
      <Button variant="outline" size="sm" onClick={()=>setTab(tab==='changes'?'conversation':'changes')}>{tab==='changes'?'بازگشت به گفتگو':'بازبینی تغییرها'}</Button>
      {(active || chat.status==='awaiting_action' || chat.status==='awaiting_plan')&&<Button type="button" size="sm" variant="outline" disabled={controls.busy!==null || chat.status==='stopping'} onClick={()=>void controls.stop()}><StopIcon/>{chat.status==='stopping'?'در حال توقف…':'توقف'}</Button>}
    </header>
    <OutputActions taskId={taskId} status={chat.status}/>
    <div className="flex min-h-0 flex-1">
      <section className="flex min-w-0 flex-1 flex-col">
        <div role="tablist" aria-label="نمای کار" className="border-border flex shrink-0 gap-1 border-b px-4 py-2" onKeyDown={event => {
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
          const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
          const index = tabs.indexOf(document.activeElement as HTMLButtonElement);
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowLeft' ? 1 : -1) + tabs.length) % tabs.length;
          event.preventDefault(); tabs[next]?.focus(); tabs[next]?.click();
        }}>
          {([['conversation','گفتگو'],['activity','فعالیت'],['plan','برنامهٔ کار'],['checks','بررسی کیفیت']] as const).map(([id,label]) => <button key={id} role="tab" id={`tab-${id}`} tabIndex={tab===id ? 0 : -1} aria-controls={`panel-${id}`} aria-selected={tab===id} onClick={() => setTab(id)} className={cn('rounded-lg px-4 py-1.5 text-xs focus-visible:outline-2 focus-visible:outline-primary', tab===id ? 'bg-primary-soft text-primary' : 'text-muted-foreground hover:bg-hover')}>{label}</button>)}
        </div>
        {disconnected && <div role="status" className="bg-warning-soft text-warning flex shrink-0 items-center gap-3 px-4 py-2 text-xs"><span className="flex-1">ارتباط رابط قطع شده؛ وضعیت کار در حال بازیابی است. اجرای تازه‌ای شروع نمی‌شود.</span><Button size="xs" variant="outline" onClick={() => void chat.reload()}>تلاش دوباره</Button></div>}
        {chat.commandError && <p role="alert" className="bg-danger-soft text-danger shrink-0 px-4 py-2 text-xs">{chat.commandError}</p>}
        {chat.snapshot?.read_only && <div role="status" className="bg-warning-soft text-warning flex shrink-0 flex-wrap items-center gap-2 px-4 py-2 text-xs"><span className="flex-1">این گفتگو فقط‌خواندنی است؛ فایل ساخته یا ویرایش نمی‌شود.</span>{readiness?.task.can_write && !active && !['closed','failed','cancelled','recovery_required'].includes(chat.status??'') ? <Button size="xs" variant="outline" disabled={controls.busy!==null} onClick={()=>void controls.enableEditing()}>فعال‌کردن ویرایش در نسخهٔ کاری</Button> : <Button asChild size="xs" variant="outline"><Link href="/settings">بررسی دسترسی و محیط</Link></Button>}</div>}
        {chat.status==='awaiting_plan' && <p role="status" className="text-warning shrink-0 px-4 py-2 text-xs">اجرا متوقف است؛ برنامهٔ زیر را تأیید کن یا تغییرت را در گفتگو بنویس.</p>}
        {chat.status==='queued' && <p role="status" className="text-muted-foreground shrink-0 px-4 py-2 text-xs">این کار در صف است؛ وضعیت شروع از موتور دریافت می‌شود.</p>}
        <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="flex min-h-0 flex-1 flex-col">
          {tab==='changes'?<ChangesReview taskId={taskId} showOutputs={false}/>:tab==='conversation' ? <Conversation messages={chat.messages} active={active} loading={chat.phase==='loading'} summary={<ActivitySummary activity={chat.activity} onOpenAll={() => setTab('activity')} />} footer={chat.status==='awaiting_plan'?<div className="rounded-lg border p-3"><PlanOnly chat={chat}/></div>:null} /> : tab==='activity' ? <div className="min-h-0 flex-1 overflow-y-auto p-4"><ActivityPanel activity={chat.activity} taskId={taskId} /></div> : tab==='checks'?<VerificationPanel taskId={taskId} status={chat.status} revision={chat.snapshot?.revision??0} onTask={chat.acceptTask} onReview={()=>setTab('activity')}/>:<div className="min-h-0 flex-1 overflow-y-auto p-3"><PlanOnly chat={chat} /></div>}
        </div>
        {chat.status==='recovery_required'&&<RecoveryPanel taskId={taskId} onRecovered={()=>void chat.reload()}/>}
        {tab!=='changes'&&<div className="scrollbar-minimal max-h-[calc(100dvh-7rem)] shrink-0 overflow-y-auto px-4 pb-3 pt-2 lg:px-6">
          <div className="mb-2"><ApprovalDock controls={controls} mode={mode} waiting={chat.status==='awaiting_action'} budget={chat.domain.budget}/></div>
          <PromptInput taskId={taskId} value={draft} onValueChange={text => setDraft(draftKey,text)} onSend={async () => { if(await chat.send(draft) && useUi.getState().drafts[draftKey]===draft) setDraft(draftKey,''); }} references={chat.references} onReferencesChange={chat.setReferences} disabled={chat.phase!=='ready' || ['failed','cancelled','recovery_required','stopping'].includes(chat.status ?? '')} sendDisabled={chat.streaming && !active} controls={<>
            <Link href="/settings" className={composerTool}><CpuIcon /><span>{readiness?.model.name ?? 'مدل تنظیم‌شده'}</span></Link>
            <label className={composerTool}><ShieldCheckIcon/><span className="sr-only">سطح دسترسی</span><select aria-label="سطح دسترسی" value={mode??'ask'} disabled={controls.busy!==null || ['closed','failed','cancelled','recovery_required'].includes(chat.status??'')} onChange={event=>void controls.mode(event.target.value as 'ask'|'grant'|'auto')} className="bg-surface max-w-40 rounded text-xs focus-visible:outline-2 focus-visible:outline-primary"><option value="ask">با تأیید</option><option value="grant">مجوز برای همین کار</option><option value="auto">خودکار در محیط ایزوله</option></select></label>
            <button type="button" className={composerTool} onClick={()=>setPermissionsOpen(true)}>مجوزهای کار</button>
            <span className={composerTool}><EyeIcon />{chat.snapshot?.read_only ? 'فقط خواندن' : 'نسخهٔ کاری ایزوله'}</span>
            <span className="text-faint text-[11px]">{workspace?.name}</span>
          </>} hint={active ? 'پیامت را بفرست؛ بعد از اقدام جاری خوانده می‌شود.' : undefined} />
        </div>}
      </section>
    </div>
    <Dialog open={permissionsOpen} onOpenChange={setPermissionsOpen}><DialogContent title="مجوزهای همین کار" description={modeName}>
      <p className="text-muted-foreground text-sm leading-7">مجوز دائمی دستگاهی وجود ندارد. مجوز تکرار فقط برای همین کار و همین فرمان و تنظیمات است. تغییر سطح دسترسی، اقدامات منتظر را لغو می‌کند؛ اقدام در حال اجرا با «توقف» قطع می‌شود.</p>
      <SandboxNetwork key={taskId} taskId={taskId} revision={chat.snapshot?.revision??0} status={chat.status} readOnly={chat.snapshot?.read_only??true}/>
      <ul aria-label="مجوزهای تکرار" className="flex max-h-56 flex-col gap-2 overflow-y-auto text-xs">
        {controls.grants.filter(grant=>grant.capability!=='sandbox_network').length===0 ? <li className="text-muted-foreground">مجوز تکراری ثبت نشده است.</li> : controls.grants.filter(grant=>grant.capability!=='sandbox_network').map(grant=><li key={grant.id} className="rounded border p-3">
          <p>{grant.active?'فعال':grant.revoked_at?'لغوشده':'غیرفعال یا منقضی'} · {grant.expiry?new Date(grant.expiry*1000).toLocaleString('fa-IR'):'حداکثر تا پایان همین کار'}</p>
          <code dir="ltr" className="mt-2 block break-all text-muted-foreground">{grant.capability}</code>
        </li>)}
      </ul>
      <Button type="button" variant="outline" disabled={controls.busy!==null} onClick={()=>void controls.revoke()}>لغو مجوزهای تکرار این کار</Button>
    </DialogContent></Dialog>
  </div>;
}
