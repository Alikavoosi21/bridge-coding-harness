'use client';

import { useEffect,useState } from 'react';
import { api } from '@/lib/api';
import { useBackend } from '@/lib/backend';
import { useUi } from '@/lib/store';
import { Button } from '@/components/ui/button';
import { Badge,Input } from '@/components/ui/primitives';
import { Dialog,DialogContent } from '@/components/ui/overlays';
import { RepinDialog } from './repin-dialog';
import { QuickSkills } from './quick-skills';

type Source={id:string;name?:string;description?:string;source:string;scope:string;valid:boolean;error?:string;enabled:boolean;trust:string;changed:boolean;current_hash:string|null;accepted_hash:string;body?:string;files?:string[]};
type Pin={skill_id:string;name:string;hash:string;valid:boolean};
const scopeName=(scope:string)=>scope==='bundled'?'همراه محصول':scope==='personal'?'شخصی':'پروژه';

export function SkillRegistryPanel(){
  const workspaceId=useBackend(state=>state.settings?.workspace.id);
  const activeTask=useUi(state=>state.activeThread);
  const [items,setItems]=useState<Source[]|null>(null);
  const [pins,setPins]=useState<Pin[]>([]);
  const [pinTask,setPinTask]=useState<string|null>(null);
  const [source,setSource]=useState('');
  const [scope,setScope]=useState<'personal'|'project'>('project');
  const [preview,setPreview]=useState<Source|null>(null);
  const [remove,setRemove]=useState<Source|null>(null);
  const [trust,setTrust]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  useEffect(()=>setPinTask(null),[activeTask,workspaceId]);
  const listUrl='/skill-sources'+(workspaceId?'?workspace_id='+encodeURIComponent(workspaceId):'');
  async function load(){const response=await api.get<{items:Source[]}>(listUrl);setItems(response.items)}
  useEffect(()=>{let alive=true;setItems(null);api.get<{items:Source[]}>(listUrl).then(value=>{if(alive)setItems(value.items)}).catch(()=>{if(alive)setError('فهرست منابع در دسترس نیست؛ دوباره بازخوانی کنید.')});return()=>{alive=false}},[listUrl]);
  useEffect(()=>{let alive=true;setPins([]);if(activeTask?.startsWith('task_')&&workspaceId)void api.get<{workspace_id:string}>(`/tasks/${encodeURIComponent(activeTask)}`).then(async task=>{if(task.workspace_id!==workspaceId)return;const value=await api.get<{items:Pin[]}>(`/tasks/${encodeURIComponent(activeTask)}/skill-pins`);if(alive){setPins(value.items);setPinTask(activeTask)}}).catch(()=>{});return()=>{alive=false}},[activeTask,workspaceId,items]);
  async function action(operation:()=>Promise<unknown>,message=''){
    setBusy(true);setError('');try{await operation();await load();setNotice(message)}catch{setError('عملیات انجام نشد؛ اعتبار منبع و hash تازه را بازبینی کنید.')}finally{setBusy(false)}
  }
  async function inspect(item:Source){setBusy(true);setError('');setTrust(false);try{setPreview(await api.get<Source>('/skill-sources/'+item.id))}catch{setError('پیش‌نمایش منبع در دسترس نیست.')}finally{setBusy(false)}}
  return <div className="flex flex-col gap-4">
    <QuickSkills onChanged={()=>void load()}/>
    <details><summary className="cursor-pointer text-xs text-muted-foreground">تنظیمات پیشرفتهٔ مهارت‌ها</summary>
    <section className="flex flex-col gap-3 rounded-lg border bg-panel p-4">
      <div className="flex flex-wrap items-center gap-3"><h2 className="flex-1 text-sm font-semibold">منابع مهارت‌ها</h2><Button size="sm" variant="outline" disabled={busy||!workspaceId} onClick={()=>void action(()=>api.post('/skill-sources/discovery',{workspace_id:workspaceId}),'منابع پروژه کشف شدند؛ منابع تازه تا بازبینی فعال نمی‌شوند.')}>کشف مهارت‌های پروژه</Button><Button size="sm" variant="outline" disabled={busy} onClick={()=>void action(async()=>{})}>بازخوانی منابع</Button></div>
      <p className="text-xs leading-6 text-muted-foreground">فقط نام و توضیح ابتدا وارد context می‌شود؛ متن کامل هنگام نیاز خوانده می‌شود. فعال‌سازی Skill اجازهٔ شبکه یا اجرای script صادر نمی‌کند.</p>
      <label className="flex flex-col gap-2 text-xs">مسیر پوشهٔ دارای SKILL.md<Input dir="ltr" value={source} onChange={event=>setSource(event.target.value)} placeholder="C:\\skills\\check-code"/></label>
      <div className="flex flex-wrap items-center gap-3"><label className="text-xs">محدوده <select className="rounded border bg-surface p-2" value={scope} onChange={event=>setScope(event.target.value as 'personal'|'project')}><option value="project" disabled={!workspaceId}>پروژهٔ فعلی</option><option value="personal">شخصی</option></select></label><Button size="sm" disabled={busy||!source.trim()||(scope==='project'&&!workspaceId)} onClick={()=>void action(async()=>{await api.post('/skill-sources',{source:source.trim(),scope,workspace_id:scope==='project'?workspaceId:null});setSource('')},'منبع ثبت شد؛ تا بازبینی و تأیید فعال نیست.')}>ثبت منبع غیرفعال</Button></div>
    </section>
    {error&&<p role="alert" className="rounded border border-danger p-3 text-xs text-danger">{error}</p>}
    {notice&&<p role="status" className="text-xs text-muted-foreground">{notice}</p>}
    {items===null?<p role="status" className="text-xs">در حال خواندن metadata…</p>:items.length===0?<p className="p-4 text-xs text-muted-foreground">منبعی ثبت نشده است؛ مهارت‌های پروژه را کشف یا مسیر شخصی را اضافه کنید.</p>:<ul className="flex flex-col divide-y rounded-lg border">{items.map(item=><li key={item.id} className="flex flex-col gap-2 p-4"><div className="flex flex-wrap items-center gap-2"><h3 className="min-w-0 flex-1 text-sm" dir="auto">{item.name??'منبع نامعتبر'}</h3><Badge tone="outline">{scopeName(item.scope)}</Badge>{(!item.valid||item.changed)&&<Badge tone={!item.valid?'danger':'warning'}>{!item.valid?'نامعتبر':'منبع تغییر کرده'}</Badge>}<Badge tone={item.enabled?'primary':'neutral'}>{item.enabled?'فعال':'غیرفعال'}</Badge><span className="text-xs text-muted-foreground">{item.trust==='reviewed'?'بازبینی‌شده':'نیازمند اعتماد صریح'}</span></div><p className="text-xs text-muted-foreground" dir="auto">{item.description??item.error}</p><code dir="ltr" className="overflow-auto text-xs text-muted-foreground">{item.source}</code><code dir="ltr" title={item.accepted_hash} className="text-xs text-muted-foreground">{item.accepted_hash.slice(0,16)||'بدون hash معتبر'}</code><div className="flex flex-wrap gap-2"><Button size="xs" variant="outline" disabled={busy} onClick={()=>void inspect(item)}>بازبینی {item.name??'منبع'}</Button>{item.enabled&&<Button size="xs" variant="outline" disabled={busy} onClick={()=>void action(()=>api.post('/skill-sources/'+item.id+'/disable'),'برای کارهای بعدی غیرفعال شد؛ pin کار جاری تغییر نکرد.')}>غیرفعال‌سازی</Button>}<Button size="xs" variant="outline" disabled={busy} onClick={()=>setRemove(item)}>حذف ثبت منبع</Button></div></li>)}</ul>}
    <section className="rounded-lg border bg-panel p-4"><h2 className="mb-2 text-sm font-semibold">نسخه‌های ثابت کار جاری</h2><p className="text-xs leading-6 text-muted-foreground">تغییر، فعال‌سازی یا حذف منبع روی کارهای بعدی اثر دارد. متن کار جاری بی‌صدا reload نمی‌شود.</p>{pins.length===0?<p className="mt-2 text-xs">pin ثبت‌شده‌ای برای کار جاری در دسترس نیست.</p>:<ul className="mt-3 flex flex-col gap-2">{pins.map(pin=><li key={pin.skill_id} className="flex flex-wrap gap-3 text-xs"><bdi>{pin.name}</bdi><code dir="ltr">{pin.hash.slice(0,16)}</code><span className={pin.valid?'text-muted-foreground':'text-danger'}>{pin.valid?'نسخهٔ ثابت معتبر':'نیازمند بازیابی'}</span></li>)}</ul>}{pinTask&&<RepinDialog key={pinTask} taskId={pinTask} disabled={busy} onBusy={setBusy} onChanged={load}/>}</section>
    <Dialog open={preview!==null} onOpenChange={value=>{if(!value&&!busy)setPreview(null)}}><DialogContent title="بازبینی و اعتماد به منبع مهارت" description="این محتوا دستورالعمل است؛ هیچ مجوز اجرای مستقلی ایجاد نمی‌کند."><div className="flex min-h-0 flex-col gap-3 overflow-auto px-6 text-xs"><code dir="ltr" className="overflow-auto">{preview?.source}</code>{error&&<p role="alert" className="text-danger">{error}</p>}<p>محدوده: {preview?scopeName(preview.scope):''}</p><code dir="ltr" className="break-all">{preview?.current_hash}</code>{!preview?.valid&&<p role="alert" className="text-danger">{preview?.error}</p>}<pre className="max-h-52 overflow-auto whitespace-pre-wrap rounded border bg-surface p-3" dir="auto">{preview?.body}</pre><ul className="flex flex-col gap-1">{preview?.files?.map(file=><li key={file}><code dir="ltr" className="block">{file}</code></li>)}</ul><p className="text-muted-foreground">{preview?.files?.length??0} فایل؛ scriptها برای اجرا همچنان به policy و محیط ایزوله نیاز دارند.</p><label className="flex items-start gap-2 leading-6"><input type="checkbox" checked={trust} onChange={event=>setTrust(event.target.checked)}/>منبع و محدوده را بازبینی کردم و به همین hash اعتماد دارم.</label></div><div className="flex gap-2 p-6"><Button disabled={busy||!trust||!preview?.valid||!preview.current_hash} onClick={()=>{if(preview)void action(async()=>{await api.post('/skill-sources/'+preview.id+'/enable',{expected_hash:preview.current_hash,confirm:true});setPreview(null)},'نسخهٔ بازبینی‌شده برای کارهای بعدی فعال شد؛ pin جاری حفظ شد.')}}>فعال‌کردن نسخهٔ بازبینی‌شده</Button><Button variant="outline" disabled={busy} onClick={()=>setPreview(null)}>انصراف</Button></div></DialogContent></Dialog>
    <Dialog open={remove!==null} onOpenChange={value=>{if(!value&&!busy)setRemove(null)}}><DialogContent title="حذف ثبت منبع" description="فقط ثبت فعال کنار گذاشته می‌شود؛ پوشهٔ اصلی، copyها و pinهای قبلی پاک نمی‌شوند."><div className="flex gap-2 p-6"><Button disabled={busy} onClick={()=>{if(remove)void action(async()=>{await api.del('/skill-sources/'+remove.id);setRemove(null)},'ثبت منبع کنار گذاشته شد؛ فایل اصلی حفظ شد.')}}>تأیید حذف ثبت</Button><Button variant="outline" onClick={()=>setRemove(null)}>انصراف</Button></div></DialogContent></Dialog>
  </details></div>;
}
