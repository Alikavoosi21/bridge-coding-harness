'use client';

import { useEffect, useRef, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { EditorView } from '@codemirror/view';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';
import { Dialog, DialogContent } from '@/components/ui/overlays';
import { api, ApiError } from '@/lib/api';
import type { TaskState } from '@/lib/harness/schema';
import { SideDiff } from './side-diff';
import { CandidateChecks } from './candidate-checks';
import { ApplyDialog } from './apply-dialog';
import { ConflictVersions } from './conflict';
import { OutputActions } from '@/features/tasks/output-actions';

type Change = { file_id:string; path:string; kind:string; conflict:boolean; working_hash:string|null };
type Report = { items:Change[]; working_revision:number; working_manifest_hash:string };
type Diff = { supported:boolean; reason?:string; before?:string; after?:string; current?:string|null; current_supported?:boolean; conflict?:boolean; diff?:string; truncated?:boolean };
type Opened = { path:string; hash:string; working_revision:number; working_manifest_hash:string; supported:boolean; content:string|null };
type Preview = { id:string; quality_status:string; file_ids:string[] };
const label:Record<string,string>={added:'افزوده',modified:'ویرایش',deleted:'حذف',binary:'دودویی',unsupported:'پشتیبانی‌نشده'};
type TaskInfo={status:TaskState;read_only:boolean};
const running=new Set<TaskState>(['planning','executing','verifying','repairing','stopping','queued']);
function failure(reason:unknown){
  if(reason instanceof ApiError){
    const messages:Record<string,string>={runtime_unavailable:'محیط نوشتن یا پروفایل بررسی آماده نیست؛ تنظیمات آمادگی را بررسی کنید.',workspace_busy:'کار یا فایل هنوز در اختیار یک عملیات دیگر است. پس از توقف دوباره بررسی کنید.',selection_stale:'نسخهٔ فایل‌ها تغییر کرده است؛ بازبینی را تازه کنید. متن ویرایش‌شدهٔ شما حفظ شده است.',recovery_required:'نتیجهٔ یک عملیات نامعلوم است؛ پیش از ادامه بازیابی لازم است.',idempotency_conflict:'این درخواست قبلاً با محتوای دیگری ثبت شده است.'};
    return messages[reason.code]??reason.message;
  }
  return reason instanceof Error?reason.message:'عملیات انجام نشد؛ دوباره بررسی کنید.';
}
const theme=EditorView.theme({ '&':{backgroundColor:'var(--surface)',color:'var(--foreground)',height:'100%'}, '.cm-scroller':{fontFamily:'var(--font-mono), monospace',overflow:'auto'}, '.cm-gutters':{backgroundColor:'transparent',color:'var(--muted-foreground)',border:'none'}, '&.cm-focused':{outline:'2px solid var(--primary)'} });

export function ChangesReview({taskId,initialPath,showOutputs=true}:{taskId:string;initialPath?:string|null;showOutputs?:boolean}) {
  const [report,setReport]=useState<Report|null>(null);
  const [path,setPath]=useState<string|null>(null);
  const [diff,setDiff]=useState<Diff|null>(null);
  const [opened,setOpened]=useState<Opened|null>(null);
  const [text,setText]=useState('');
  const [editing,setEditing]=useState(false);
  const [selected,setSelected]=useState<string[]>([]);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [wrap,setWrap]=useState(false);
  const [columns,setColumns]=useState(false);
  const [preview,setPreview]=useState<Preview|null>(null);
  const [leave,setLeave]=useState<null|(()=>void)>(null);
  const [task,setTask]=useState<TaskInfo|null>(null);
  const [taskError,setTaskError]=useState(false);
  const generation=useRef(0);
  const saveKey=useRef<string|null>(null);
  const stopKey=useRef<string|null>(null);
  const initialSelection=useRef(false);
  const dirty=editing && opened!==null && text!==opened.content;
  const base=`/tasks/${encodeURIComponent(taskId)}`;
  const draftKey=(file:string)=>`working-edit:${taskId}:${file}`;
  const active=task!==null&&running.has(task.status);
  const canEdit=task!==null&&!task.read_only&&!active&&!taskError&&task.status!=='recovery_required';
  useEffect(()=>{
    if(!report||initialSelection.current)return;
    initialSelection.current=true;
    if(report.items.length===1){
      const item=report.items[0];
      void open(item.path);
      if(!item.conflict&&!['binary','unsupported'].includes(item.kind))setSelected([item.file_id]);
    }
  },[report]);
  function removeDraft(){if(path)sessionStorage.removeItem(draftKey(path))}
  async function refresh() {
    const result=await api.get<Report>(base+'/changes');
    setReport(result);setSelected(current=>current.filter(id=>result.items.some(row=>row.file_id===id)));
    return result;
  }
  useEffect(()=>{let current=true;api.get<Report>(base+'/changes').then(value=>{if(current)setReport(value)}).catch(reason=>{if(current)setError(String(reason))});return()=>{current=false;generation.current++}},[base]);
  useEffect(()=>{
    let alive=true;let timer:ReturnType<typeof setTimeout>|undefined;
    async function read(){let again=true;try{const value=await api.get<TaskInfo>(base);if(!alive)return;setTask(value);setTaskError(false);again=running.has(value.status)}catch{if(alive)setTaskError(true)}finally{if(alive&&again)timer=setTimeout(()=>void read(),1500)}}
    void read();return()=>{alive=false;clearTimeout(timer)};
  },[base,task?.status]);
  useEffect(()=>{if(initialPath)void open(initialPath)},[initialPath]);
  useEffect(()=>{if(!dirty)return;const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)},[dirty]);
  useEffect(()=>{if(!dirty)return;const intercept=(event:MouseEvent)=>{const anchor=(event.target as Element).closest?.('a[href]');if(anchor instanceof HTMLAnchorElement && anchor.origin===window.location.origin && !event.ctrlKey && !event.metaKey){event.preventDefault();event.stopPropagation();setLeave(()=>()=>{window.location.href=anchor.href})}};document.addEventListener('click',intercept,true);return()=>document.removeEventListener('click',intercept,true)},[dirty]);
  function guard(action:()=>void){if(dirty)setLeave(()=>action);else action()}
  async function open(next:string) {
    const version=++generation.current;
    setPath(next);setEditing(false);setOpened(null);setDiff(null);setError('');
    try {const result=await api.get<Diff>(base+'/changes/file?path='+encodeURIComponent(next));if(version===generation.current)setDiff(result)}catch(reason){if(version===generation.current)setError(String(reason))}
  }
  async function edit() {
    if(!path)return;setBusy(true);setError('');
    try {const state=await api.get<TaskInfo>(base);setTask(state);if(state.read_only||running.has(state.status)||state.status==='recovery_required')throw new Error('ویرایش فقط پس از توقف تأییدشده و در کار دارای دسترسی نوشتن ممکن است.');const current=await api.get<Opened>(base+'/working-file?path='+encodeURIComponent(path));if(!current.supported)throw new Error('این فایل قابل ویرایش متنی نیست.');setOpened(current);let recovered:string|null=null;try{recovered=sessionStorage.getItem(draftKey(path))}catch{}setText(recovered??current.content??'');if(recovered!==null)setError('متن ذخیره‌نشدهٔ قبلی بازیابی شد؛ پیش از ذخیره با نسخهٔ جاری مقایسه کنید.');setEditing(true);saveKey.current=null}catch(reason){setError(failure(reason))}finally{setBusy(false)}
  }
  async function stop(){setBusy(true);setError('');try{stopKey.current??=crypto.randomUUID();const result=await api.post<{task:TaskInfo}>(base+'/stop',{idempotency_key:stopKey.current});setTask(result.task)}catch(reason){setError(failure(reason))}finally{setBusy(false)}}
  async function save():Promise<boolean> {
    if(!opened || !dirty)return true;
    setBusy(true);setError('');
    try {
      saveKey.current??=crypto.randomUUID();
      await api.put(base+'/working-file',{path:opened.path,content:text,expected_working_revision:opened.working_revision,expected_manifest_hash:opened.working_manifest_hash,expected_file_hash:opened.hash,idempotency_key:saveKey.current});
      removeDraft();setPreview(null);setEditing(false);setOpened(null);await refresh();await open(opened.path);return true;
    }catch(reason){setError(failure(reason)+' — متن شما حفظ شده است؛ پیش از تلاش تازه نسخهٔ جاری را بررسی کنید.');return false}finally{setBusy(false)}
  }
  async function capture(){if(!report)return;setBusy(true);setError('');try{setPreview(await api.post<Preview>(base+'/apply-previews',{file_ids:selected,expected_working_revision:report.working_revision,expected_manifest_hash:report.working_manifest_hash,idempotency_key:crypto.randomUUID()}))}catch(reason){setError(failure(reason))}finally{setBusy(false)}}
  return <section className="flex min-h-0 min-w-0 flex-1 flex-col" aria-label="بازبینی تغییرها">
    {showOutputs&&<OutputActions taskId={taskId} status={task?.status??null}/>}
    <header className="flex shrink-0 flex-wrap items-center gap-3 border-b p-4">
      <Button variant="outline" size="sm" onClick={()=>guard(()=>{window.location.href='/tasks?task='+encodeURIComponent(taskId)})}>بازگشت به گفتگو</Button>
      <h1 className="flex-1 text-sm font-semibold">بازبینی تغییرها {report?`(${report.items.length})`:''}</h1>
      <Button size="sm" variant="outline" disabled={busy} onClick={()=>guard(()=>{setBusy(true);setPreview(null);setSelected([]);void refresh().then(()=>{if(path)return open(path)}).catch(reason=>setError(failure(reason))).finally(()=>setBusy(false))})}>بازخوانی تغییرها</Button>
      <Badge tone="warning">کیفیت انتخاب هنوز تأیید نشده</Badge>
      <Button size="sm" disabled={busy||!canEdit||selected.length===0||dirty} onClick={()=>void capture()}>پیش‌نمایش {selected.length} فایل منتخب</Button>
    </header>
    <p className="shrink-0 border-b px-4 py-2 text-xs text-muted-foreground">نسخهٔ کاری ایجنت؛ فایل اصلی هنوز تغییر نکرده. پیش‌نمایش، فایل‌ها را روی اصل اعمال نمی‌کند.</p>
    {(active||task?.read_only||taskError)&&<div role="status" className="flex shrink-0 items-center gap-3 border-b p-3 text-xs text-warning"><span className="flex-1">{taskError?'وضعیت اجرای کار در دسترس نیست؛ ویرایش موقتاً بسته است.':task?.read_only?'این کار فقط‌خواندنی است؛ ویرایش فعال نیست.':task?.status==='stopping'?'در انتظار تأیید توقف محیط؛ ویرایش هنوز بسته است.':'برای ویرایش ابتدا اجرای کار را متوقف کنید.'}</span>{active&&task?.status!=='stopping'&&<Button size="xs" variant="outline" onClick={()=>void stop()}>توقف برای ویرایش</Button>}</div>}
    {error&&<p role="alert" className="shrink-0 bg-danger-soft p-3 text-xs text-danger">{error}</p>}
    {preview&&<><CandidateChecks key={preview.id} taskId={taskId} selectionId={preview.id} disabled={!canEdit||dirty} onBusy={setBusy} onRunning={()=>setTask(current=>current?{...current,status:'verifying'}:current)} onSettled={()=>{void api.get<TaskInfo>(base).then(setTask).catch(()=>setTaskError(true))}}/><div className="shrink-0 border-b p-3"><ApplyDialog key={preview.id} taskId={taskId} selectionId={preview.id} disabled={busy||!canEdit||dirty} onBusy={setBusy}/></div></>}
    <div className="flex min-h-0 flex-1 flex-col md:flex-row">
      <nav aria-label="فایل‌های تغییرکرده" className="flex max-h-44 shrink-0 flex-col gap-1 overflow-auto border-b p-2 md:max-h-none md:w-60 md:border-b-0 md:border-e">
        {!report?<p role="status" className="p-3 text-xs">در حال خواندن تغییرها…</p>:report.items.length===0?<p className="p-3 text-xs text-muted-foreground">تغییری برای بازبینی وجود ندارد.</p>:report.items.map(row=><div key={row.file_id} className="flex items-center gap-2 rounded p-2">
          <input type="checkbox" aria-label={`انتخاب ${row.path} برای پیش‌نمایش`} checked={selected.includes(row.file_id)} disabled={busy||row.conflict||['binary','unsupported'].includes(row.kind)} onChange={event=>{setPreview(null);setSelected(current=>event.target.checked?[...current,row.file_id]:current.filter(id=>id!==row.file_id))}}/>
          <button type="button" aria-current={path===row.path?'true':undefined} className="min-w-0 flex-1 text-start text-xs focus-visible:outline-2 focus-visible:outline-primary" onClick={()=>guard(()=>void open(row.path))}><bdi className="block truncate">{row.path}</bdi><span className="text-muted-foreground">{label[row.kind]??row.kind}{row.conflict?' · تعارض با اصل':''}</span></button>
        </div>)}
      </nav>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {path?<><div className="flex shrink-0 flex-wrap items-center gap-2 border-b p-2 text-xs"><bdi className="min-w-0 flex-1 truncate">{path}</bdi><label><input type="checkbox" checked={wrap} onChange={event=>setWrap(event.target.checked)}/> شکستن خطوط</label><label><input type="checkbox" checked={columns} onChange={event=>setColumns(event.target.checked)}/> دوستونه</label>{editing?<><Badge tone="warning">{dirty?'ذخیره نشده':'ویرایش نسخهٔ کاری'}</Badge><Button size="xs" disabled={!dirty||busy||!canEdit} onClick={()=>void save()}>ذخیره</Button><Button size="xs" variant="outline" disabled={busy} onClick={()=>guard(()=>setEditing(false))}>لغو</Button></>:<Button size="xs" variant="outline" disabled={busy||!canEdit||!diff?.supported||report?.items.find(row=>row.path===path)?.kind==='deleted'} onClick={()=>void edit()}>ویرایش نسخهٔ کاری</Button>}</div>
          <div dir="ltr" className="min-h-0 flex-1 overflow-auto" aria-label={editing?'ویرایشگر نسخهٔ کاری':'تفاوت فایل'}>
            {editing?<CodeMirror theme="dark" value={text} height="100%" readOnly={busy} extensions={[theme,...(wrap?[EditorView.lineWrapping]:[])]} onChange={value=>{setText(value);saveKey.current=null;if(path)try{sessionStorage.setItem(draftKey(path),value)}catch{setError('ذخیرهٔ موقت مرورگر ممکن نیست؛ پیش از خروج متن را کپی کنید.')}}} aria-label="متن نسخهٔ کاری"/>:!diff?<p className="p-4 text-xs">در حال خواندن تفاوت…</p>:!diff.supported?<p dir="rtl" className="p-4 text-sm">نمایش متنی در دسترس نیست: {diff.reason}</p>:diff.conflict?<ConflictVersions before={diff.before??""} current={diff.current} after={diff.after??""} currentSupported={diff.current_supported??false} wrap={wrap}/>:columns?<SideDiff before={diff.before??""} after={diff.after??""} wrap={wrap}/>:<pre className="p-3 text-xs" style={{whiteSpace:wrap?'pre-wrap':'pre'}}>{diff.diff||'بدون اختلاف متنی'}{diff.truncated?'\n… خروجی محدود شده است':''}</pre>}
          </div></>:<p className="p-6 text-sm text-muted-foreground">برای مشاهدهٔ تفاوت، نام فایل را انتخاب کنید. انتخاب checkbox فقط برای پیش‌نمایش اعمال است.</p>}
      </div>
    </div>
    <Dialog open={leave!==null} onOpenChange={value=>{if(!value)setLeave(null)}}><DialogContent title="متن ذخیره‌نشده دارید" description="پیش از ترک ویرایشگر دربارهٔ متن تصمیم بگیرید."><div className="flex flex-wrap gap-2 p-4"><Button disabled={busy} onClick={async()=>{if(await save()){const action=leave;setLeave(null);action?.()}}}>ذخیره و ادامه</Button><Button variant="outline" disabled={busy} onClick={()=>{removeDraft();const action=leave;setLeave(null);setEditing(false);action?.()}}>کنارگذاشتن</Button><Button variant="outline" onClick={()=>setLeave(null)}>ماندن</Button></div></DialogContent></Dialog>
  </section>;
}
