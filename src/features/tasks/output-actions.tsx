'use client';
import { useEffect,useRef,useState } from 'react';
import { PlayIcon,ArrowSquareOutIcon,StopIcon } from '@phosphor-icons/react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/primitives';
import { Dialog,DialogContent } from '@/components/ui/overlays';
import type { TaskState } from '@/lib/harness/schema';

type Output={id:string;task_id:string;kind:string;state:string;url:string|null;command:string;output:string;exit_code:number|null;path:string;expires_at:number};
type Info={html_files:string[];commands:{command:string;kind:'command'|'server';port:number}[];install:{command:string}|null;can_run:boolean;busy:boolean;working_revision:number;working_manifest_hash:string;sessions:Output[]};
const labels:Record<string,string>={starting:'در حال آماده‌سازی',installing:'در حال نصب وابستگی‌ها',running:'در حال اجرا',ready:'آمادهٔ مشاهده',finished:'اجرا تمام شد',failed:'اجرا ناموفق بود',stopping:'در حال توقف',stopped:'متوقف شد',unknown:'توقف تأیید نشد؛ دوباره بررسی کن'};
const live=new Set(['starting','installing','running','ready','stopping','unknown']);

export function OutputActions({taskId,status}:{taskId:string;status:TaskState|null}){
 const [open,setOpen]=useState(false),[info,setInfo]=useState<Info|null>(null),[session,setSession]=useState<Output|null>(null);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[command,setCommand]=useState(''),[kind,setKind]=useState<'command'|'server'>('command'),[port,setPort]=useState(3000);
 const [install,setInstall]=useState(false),[installCommand,setInstallCommand]=useState(''),[frame,setFrame]=useState(0);
 const requestKey=useRef<{signature:string;key:string}|null>(null);
 const base='/tasks/'+encodeURIComponent(taskId)+'/outputs';
 const active=['queued','planning','executing','verifying','repairing','stopping','recovery_required'].includes(status??'');
 const load=async()=>{const data=await api.get<Info>(base);setInfo(data);if(!command&&data.commands[0]){setCommand(data.commands[0].command);setKind(data.commands[0].kind);setPort(data.commands[0].port);}if(!installCommand)setInstallCommand(data.install?.command??'');return data;};
 useEffect(()=>{if(!active&&status)void load().catch(()=>{});},[taskId,status]);
 useEffect(()=>{
  if(!session||!live.has(session.state))return;
  let current=true;const timer=setInterval(()=>{void api.get<Output>(base+'/'+session.id).then(value=>{if(current)setSession(value);}).catch(e=>{if(current)setError(e instanceof Error?e.message:'وضعیت اجرا در دسترس نیست.');});},1500);
  return()=>{current=false;clearInterval(timer);};
 },[session?.id,session?.state,base]);
 const start=async(mode:'html'|'command'|'server',path='',automatic=false)=>{
  setOpen(true);setBusy(true);setError('');
  try{
   const data=await load();
   if(session&&live.has(session.state)){const stopped=await api.post<Output>(base+'/'+session.id+'/stop',{});setSession(stopped);if(stopped.state!=='stopped')throw new Error('توقف اجرای قبلی هنوز تأیید نشده؛ کمی بعد دوباره بررسی کن.');}
   const suggested=data.commands.find(item=>item.kind==='server')??data.commands[0];
   if(automatic){if(suggested?.kind==='server')mode='server';else if(data.html_files.length){mode='html';path=data.html_files[0];}else mode='command';}
   const chosenCommand=automatic?suggested?.command??'':command;
   if(mode!=='html'&&!chosenCommand)throw new Error('هنوز فایل قابل اجرا ساخته نشده؛ از ایجنت بخواه برنامه را در فایل بسازد.');
   const autoInstall=automatic&&mode!=='html'&&data.install?.command;
   const payload={kind:mode,path,command:chosenCommand,port:automatic?suggested?.port??3000:port,confirm:true,network_consent:mode==='server',install_command:autoInstall?data.install!.command:mode!=='html'&&install?installCommand:'',install_consent:!!autoInstall||(mode!=='html'&&install),expected_revision:data.working_revision,expected_hash:data.working_manifest_hash};
   const signature=JSON.stringify(payload);if(requestKey.current?.signature!==signature)requestKey.current={signature,key:crypto.randomUUID()};
   const result=await api.post<Output>(base,{...payload,key:requestKey.current.key});
   setSession(result);setFrame(n=>n+1);requestKey.current=null;
  }catch(e){setError(e instanceof Error?e.message:'اجرا ممکن نشد.');}finally{setBusy(false);}
 };

 return <><div className="flex shrink-0 flex-wrap items-center gap-2 border-b px-4 py-2 text-xs" aria-label="اجرای خروجی">
  {info?.html_files.slice(0,3).map(path=><Button key={path} size="xs" variant="outline" disabled={active||busy} onClick={()=>void start('html',path)}>پیش‌نمایش <bdi>{path}</bdi></Button>)}
  <Button size="xs" variant="outline" disabled={active||busy} onClick={()=>void start('html','',true)}><PlayIcon/>اجرا و نمایش</Button>
  <span className="text-muted-foreground">داخل اپ؛ اجرای محلی با ابزارهای همراه</span>
  {session?.url&&session.state==='ready'&&<a href={session.url} target="_blank" rel="noreferrer" className="text-primary underline">بازکردن خروجی ↗</a>}
 </div>
 <Dialog open={open} onOpenChange={setOpen}><DialogContent className="max-w-[1120px]" title="خروجی و اجرای برنامه" description="خروجی داخل اپ باز می‌شود. اجرای محلی دسترسی حساب ویندوز شما را دارد؛ وابستگی‌های لازم در کپی همین گفتگو نصب می‌شوند.">
  <div className="min-h-0 space-y-3 overflow-y-auto px-6 pb-6">
   {!!info?.html_files.length&&<div className="flex flex-wrap gap-2">{info.html_files.map(path=><Button key={path} size="xs" variant="outline" disabled={busy||active} onClick={()=>void start('html',path)}>پیش‌نمایش <bdi>{path}</bdi></Button>)}</div>}
   <details className="rounded-lg border p-3"><summary className="cursor-pointer text-sm">تنظیمات پیشرفتهٔ اجرا</summary><div className="mt-3 space-y-3">
    {!!info?.commands.length&&<label className="block text-xs">فرمان‌های پروژه<select aria-label="فرمان پیشنهادی اجرا" className="bg-surface mt-1 w-full rounded border p-2" onChange={event=>{const item=info.commands[Number(event.target.value)];if(item){setCommand(item.command);setKind(item.kind);setPort(item.port);}}}><option value="">انتخاب کن…</option>{info.commands.map((item,index)=><option key={item.command} value={index}>{item.command}</option>)}</select></label>}
    <Input dir="ltr" aria-label="فرمان اجرای خروجی" placeholder="python main.py یا npm run dev" value={command} onChange={event=>setCommand(event.target.value)}/>
    <div className="flex flex-wrap items-center gap-3 text-xs"><label>نوع اجرا <select aria-label="نوع اجرای خروجی" value={kind} onChange={event=>setKind(event.target.value as 'command'|'server')} className="bg-surface rounded border p-2"><option value="command">فرمان و خروجی ترمینال</option><option value="server">برنامهٔ وب و لینک بازکردن</option></select></label>{kind==='server'&&<label>پورت <input aria-label="پورت برنامه" type="number" min={1024} max={65535} value={port} onChange={event=>setPort(Number(event.target.value))} className="bg-surface w-24 rounded border p-2"/></label>}</div>
    {kind==='server'&&<p className="text-muted-foreground text-xs">فرمان و پورت معمولاً خودکار تشخیص داده می‌شوند. فرمان محلی با دسترسی حساب ویندوز و شبکه اجرا می‌شود؛ این محیط sandbox نیست.</p>}
    <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={install} onChange={event=>setInstall(event.target.checked)}/>پیش از اجرا، نصب وابستگی‌ها با دسترسی شبکه را فقط در کپی اجرا تأیید می‌کنم.</label>
    {install&&<Input dir="ltr" aria-label="فرمان نصب برای اجرا" value={installCommand} onChange={event=>setInstallCommand(event.target.value)} placeholder="npm ci"/>}
    <Button size="sm" disabled={busy||!info?.can_run||!command.trim()||(install&&!installCommand.trim())} onClick={()=>void start(kind)}><PlayIcon/>{busy?'در حال آماده‌سازی…':kind==='server'?'اجرا و نمایش برنامه':'اجرای فرمان'}</Button>
    {info&&!info.can_run&&<p className="text-warning text-xs">برای اجرای فرمان، گفتگو باید از حالت فقط‌خواندنی خارج و اجرای جاری تمام یا متوقف شده باشد. ابزارهای اجرا همراه اپ هستند؛ Docker لازم نیست.</p>}
   </div></details>
   {error&&<p role="alert" className="text-danger text-xs">{error}</p>}
   {session&&<section className="space-y-3 rounded-lg border p-3"><div className="flex flex-wrap items-center gap-3 text-xs"><span role="status" className="flex-1">{labels[session.state]??session.state}{session.exit_code!==null?` · exit ${session.exit_code}`:''}</span>
    {session.url&&session.state==='ready'&&<><a href={session.url} target="_blank" rel="noreferrer" className="text-primary underline">بازکردن در مرورگر ↗</a><Button size="xs" variant="outline" onClick={()=>setFrame(n=>n+1)}>بازخوانی</Button><Button size="xs" variant="outline" onClick={async()=>{if(!await window.desktop?.openPreview?.(taskId,session.id))setError('پنجرهٔ پیش‌نمایش باز نشد؛ وضعیت اجرا را بررسی کن.');}}><ArrowSquareOutIcon/>پنجرهٔ جدا</Button></>}
    {live.has(session.state)&&<Button size="xs" variant="outline" disabled={busy} onClick={async()=>{setBusy(true);try{setSession(await api.post<Output>(base+'/'+session.id+'/stop',{}));}catch(e){setError(e instanceof Error?e.message:'توقف تأیید نشد.');}finally{setBusy(false);}}}><StopIcon/>توقف خروجی</Button>}
   </div>{session.url&&session.state==='ready'&&<><a dir="ltr" className="block break-all text-xs text-primary underline" href={session.url} target="_blank" rel="noreferrer">{session.url}</a><iframe key={frame} title="پیش‌نمایش خروجی" src={session.url} sandbox="allow-scripts allow-forms allow-same-origin" referrerPolicy="no-referrer" className="h-[45vh] w-full rounded border bg-white"/></>}
   {session.output&&<pre dir="ltr" aria-label="خروجی اجرای کد" className="max-h-52 overflow-auto whitespace-pre-wrap rounded bg-black p-3 font-mono text-xs text-white">{session.output}</pre>}
   </section>}
  </div>
 </DialogContent></Dialog></>;
}
