'use client';
import { useEffect,useRef,useState } from 'react';
import { SparkleIcon,PlusIcon } from '@phosphor-icons/react';
import { api,ApiError } from '@/lib/api';
import { useBackend } from '@/lib/backend';
import { Button } from '@/components/ui/button';
import { Input,Textarea } from '@/components/ui/primitives';
import { Dialog,DialogContent } from '@/components/ui/overlays';
import { RepinDialog } from './repin-dialog';
import { availableSkills,type AvailableSkill as Skill } from './available-skills';

type Candidate={source:string;relative:string;name?:string;description?:string;valid:boolean;error?:string};
export function QuickSkills({onSelect,taskId,onChanged}:{onSelect?:(name:string)=>void;taskId?:string;onChanged?:()=>void}){
 const workspaceId=useBackend(s=>s.settings?.workspace.id);
 const [open,setOpen]=useState(false),[adding,setAdding]=useState(false),[skills,setSkills]=useState<Skill[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const [name,setName]=useState(''),[description,setDescription]=useState(''),[instructions,setInstructions]=useState(''),[confirm,setConfirm]=useState(false);
 const [imported,setImported]=useState<{id:string;hash:string}|null>(null);
 const [candidates,setCandidates]=useState<Candidate[]>([]),[filter,setFilter]=useState(''),[notice,setNotice]=useState('');
 const fileInput=useRef<HTMLInputElement>(null);
 const load=async()=>{
  setSkills(await availableSkills(taskId,workspaceId));
 };
 useEffect(()=>{if(open)void load().catch(()=>setError('فهرست مهارت‌ها در دسترس نیست.'));},[open,taskId,workspaceId]);
 const save=async()=>{setBusy(true);setError('');try{
  const result=imported?await api.post<Skill>('/skill-sources/'+imported.id+'/enable',{expected_hash:imported.hash,confirm}):await api.post<Skill>('/skills/create',{name,description,instructions,confirm});
  setAdding(false);setImported(null);setName('');setDescription('');setInstructions('');setConfirm(false);setNotice(taskId?'ذخیره شد. برای استفاده در همین گفتگو، مهارت‌های گفتگو را به‌روزرسانی کن.':'مهارت آمادهٔ استفاده است.');onChanged?.();await load();
  if(!taskId&&onSelect){onSelect(result.name);setOpen(false);}
 }catch(e){setError(e instanceof ApiError?e.message:'ذخیرهٔ مهارت ممکن نشد.');}finally{setBusy(false);}};
 const inspectCandidate=async(candidate:Candidate)=>{
  if(!candidate.valid){setError(candidate.error||'مهارت معتبر نیست.');return;}
  setBusy(true);setError('');try{
   const source=await api.post<{id:string}>('/skill-sources',{source:candidate.source,scope:'personal'});
   const detail=await api.get<{name:string;description:string;body:string;current_hash:string;valid:boolean;error?:string}>('/skill-sources/'+source.id);
   if(!detail.valid)throw new Error(detail.error||'مهارت معتبر نیست.');
   setImported({id:source.id,hash:detail.current_hash});setName(detail.name);setDescription(detail.description);setInstructions(detail.body);setConfirm(false);setAdding(true);setCandidates([]);
  }catch(e){setError(e instanceof Error?e.message:'خواندن مهارت ممکن نشد.');}finally{setBusy(false);}
 };
 const importFolder=async()=>{const folder=await window.desktop?.pickFolder?.();if(!folder)return;setBusy(true);setError('');setNotice('');try{
  const result=await api.post<{items:Candidate[];truncated:boolean}>('/skill-sources/scan',{source:folder});
  if(result.items.length===1&&result.items[0].valid){await inspectCandidate(result.items[0]);return;}
  setCandidates(result.items);setFilter('');setAdding(false);
  if(!result.items.length)setError('در این پوشه SKILL.md پیدا نشد؛ پوشهٔ یک مهارت یا مجموعهٔ آن‌ها را انتخاب کن.');
  else setNotice(`${result.items.length} مهارت پیدا شد؛ یکی را برای بازبینی انتخاب کن.${result.truncated?' اسکن محدود شد؛ برای دیدن بقیه زیرپوشه را انتخاب کن.':''}`);
 }catch(e){setError(e instanceof ApiError?e.message:'خواندن مجموعهٔ مهارت‌ها ممکن نشد.');}finally{setBusy(false);}};
 const importFile=async(file:File)=>{setBusy(true);setError('');setNotice('');try{
  if(file.size>65536)throw new Error('فایل SKILL.md باید کوچک‌تر از ۶۴ کیلوبایت باشد.');
  const result=await api.post<{name:string;description:string;body:string}>('/skills/parse',{content:await file.text()});
  setImported(null);setName(result.name);setDescription(result.description);setInstructions(result.body);setConfirm(false);setAdding(true);setCandidates([]);
  setNotice('متن فایل خوانده شد. اگر مهارت فایل‌های همراه دارد، پوشهٔ آن را وارد کن.');
 }catch(e){setError(e instanceof Error?e.message:'خواندن فایل مهارت ممکن نشد.');}finally{setBusy(false);}};
 return <><button type="button" className="text-muted-foreground hover:bg-hover flex h-8 items-center gap-1 rounded-lg px-2 text-xs" onClick={()=>setOpen(true)}><SparkleIcon className="size-4"/>مهارت</button>
 <Dialog open={open} onOpenChange={setOpen}><DialogContent title="مهارت‌ها" description={taskId?'مهارت‌های آمادهٔ همین گفتگو':'یک مهارت انتخاب کن یا مهارت خودت را اضافه کن.'}>
 <div className="space-y-3">
  <div className="flex flex-wrap gap-2"><Button size="sm" onClick={()=>{setImported(null);setCandidates([]);setName('');setDescription('');setInstructions('');setAdding(!adding);}}><PlusIcon/>افزودن مهارت</Button><Button size="sm" variant="outline" disabled={busy} onClick={()=>fileInput.current?.click()}>فایل SKILL.md</Button><Button size="sm" variant="outline" disabled={busy} onClick={()=>void importFolder()}>انتخاب پوشهٔ Skill</Button><input ref={fileInput} type="file" accept=".md" aria-label="واردکردن فایل مهارت" className="hidden" onChange={e=>{const file=e.target.files?.[0];if(file)void importFile(file);e.target.value='';}}/></div>
  {notice&&<p role="status" className="text-primary text-xs leading-6">{notice}</p>}
  {!!candidates.length&&<div className="space-y-2"><Input aria-label="جستجوی مهارت‌های مجموعه" placeholder="جستجو در مجموعه…" value={filter} onChange={e=>setFilter(e.target.value)}/><ul className="max-h-64 space-y-2 overflow-auto">{candidates.filter(item=>(item.name+' '+item.relative).toLowerCase().includes(filter.toLowerCase())).map(item=><li key={item.source}><button type="button" disabled={busy||!item.valid} className="hover:bg-hover w-full rounded-lg border p-3 text-start disabled:opacity-50" onClick={()=>void inspectCandidate(item)}><span dir="ltr" className="text-primary text-sm">{item.name||item.relative}</span><p className="text-muted-foreground mt-1 text-xs">{item.valid?item.description:item.error}</p></button></li>)}</ul></div>}
  {adding&&<div className="space-y-3 rounded-lg border p-3"><Input readOnly={!!imported} aria-label="نام مهارت" placeholder="نام انگلیسی؛ مثلاً code-review" value={name} onChange={e=>setName(e.target.value)}/><Input readOnly={!!imported} aria-label="کاربرد مهارت" placeholder="چه زمانی از این مهارت استفاده شود؟" value={description} onChange={e=>setDescription(e.target.value)}/><Textarea readOnly={!!imported} aria-label="دستور مهارت" placeholder="دستورها را بنویس یا متن مهارت را بچسبان…" rows={7} value={instructions} onChange={e=>setInstructions(e.target.value)}/><label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={confirm} onChange={e=>setConfirm(e.target.checked)} className="accent-primary"/>متن را بررسی کردم و اجازهٔ استفاده از آن را می‌دهم.</label><Button disabled={busy||!confirm||!name||!description||!instructions} onClick={()=>void save()}>ذخیره و فعال‌سازی</Button></div>}
  {error&&<p role="alert" className="text-danger text-xs">{error}</p>}
  <ul className="max-h-72 space-y-2 overflow-auto">{skills.map(skill=><li key={skill.name}><button type="button" className="hover:bg-hover w-full rounded-lg border p-3 text-start" onClick={()=>{onSelect?.(skill.name);setOpen(false);}}><span dir="ltr" className="text-primary text-sm">/{skill.name}</span><p className="text-muted-foreground mt-1 text-xs">{skill.description}</p></button></li>)}</ul>
  {taskId&&<><p className="text-muted-foreground text-xs">مهارت تازه برای این گفتگو: ابتدا نسخه‌ها را به‌روز کن.</p><RepinDialog taskId={taskId} disabled={busy} onBusy={setBusy} onChanged={load}/></>}
 </div></DialogContent></Dialog></>;
}
