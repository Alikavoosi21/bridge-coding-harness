'use client';

import { ArrowUpIcon, CircleNotchIcon, FilePlusIcon, MagnifyingGlassIcon, PaperclipIcon, XIcon } from '@phosphor-icons/react';
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/overlays';
import { Input, PathText } from '@/components/ui/primitives';
import { api, ApiError, type FileEntry } from '@/lib/api';
import { cn } from '@/lib/utils';
import { QuickSkills } from '@/features/skills/quick-skills';
import { availableSkills,type AvailableSkill } from '@/features/skills/available-skills';
import { useBackend } from '@/lib/backend';
import { skillMention,insertSkillMention } from '@/lib/harness/skill-mention';

/** A small icon button that sits in the composer toolbar. */
export const composerTool =
  'text-muted-foreground hover:bg-hover hover:text-foreground flex h-8 max-w-56 items-center gap-1.5 rounded-lg px-2 text-xs outline-none [&_svg]:size-3.5';

/**
 * Pick files from inside the open workspace.
 *
 * Only the workspace list is offered. A path from another project, or a path
 * outside the folder, is deliberately not accepted here: the backend refuses
 * it, and v1 never widens access silently. The note says what to do instead.
 */
export function ReferencePicker({
  open,
  onOpenChange,
  selected,
  onSelect,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selected: string[];
  onSelect: (path: string) => void;
}) {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [query, setQuery] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<FileEntry[]>('/files?system=false')
      .then((list) => {
        if (!cancelled) setEntries(list);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof ApiError ? caught.message : 'خواندن فایل‌های پروژه ممکن نشد.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const list = needle ? entries.filter((entry) => entry.path.toLowerCase().includes(needle)) : entries;
    return list.slice(0, 800);
  }, [entries, query]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="افزودن فایل مرجع"
        description="فقط فایل‌های داخل همین پروژه. فایل مرجع به معنی اجازهٔ تغییر نیست."
        className="max-w-[560px]"
      >
        <div className="relative mb-3">
          <MagnifyingGlassIcon className="text-muted-foreground absolute start-3 top-1/2 size-4 -translate-y-1/2" />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="جست‌وجوی مسیر…" className="ps-9" autoFocus />
        </div>
        {error ? (
          <p className="text-danger bg-danger-soft rounded-lg px-3 py-2 text-xs leading-6">{error}</p>
        ) : loading ? (
          <div className="text-muted-foreground flex items-center justify-center gap-2 py-10 text-sm">
            <CircleNotchIcon className="size-5 animate-spin" /> در حال خواندن فایل‌ها…
          </div>
        ) : visible.length === 0 ? (
          <p className="text-muted-foreground py-10 text-center text-sm">فایلی با این مسیر پیدا نشد.</p>
        ) : (
          <ul className="divide-border max-h-[46vh] divide-y overflow-y-auto rounded-lg border">
            {visible.map((entry) => {
              const already = selected.includes(entry.path);
              return (
                <li key={entry.path}>
                  <button
                    type="button"
                    disabled={already}
                    onClick={() => {
                      onSelect(entry.path);
                      onOpenChange(false);
                    }}
                    className={cn(
                      'hover:bg-hover flex w-full items-center gap-3 px-3 py-2.5 text-start',
                      already && 'cursor-default opacity-45 hover:bg-transparent',
                    )}
                  >
                    <FilePlusIcon className="text-muted-foreground size-4 shrink-0" />
                    <PathText path={entry.path} className="min-w-0 flex-1 text-sm" />
                    {already && <span className="text-faint shrink-0 text-[11px]">افزوده شد</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <p className="text-muted-foreground mt-3 text-[11px] leading-6">
          فایل بیرون پروژه خودکار به دامنهٔ دسترسی اضافه نمی‌شود؛ اول آن را داخل پوشهٔ پروژه کپی کنید.
        </p>
      </DialogContent>
    </Dialog>
  );
}

export type PromptInputProps = {
  taskId?: string;
  value: string;
  onValueChange: (value: string) => void;
  onSend: () => void | Promise<void>;
  references: string[];
  onReferencesChange: (references: string[]) => void;
  /** A real in-flight request. The box stays editable so the text is never lost. */
  busy?: boolean;
  disabled?: boolean;
  sendDisabled?: boolean;
  large?: boolean;
  autoFocus?: boolean;
  placeholder?: string;
  sendLabel?: string;
  /** Model, access mode, read-only: always visible next to the box. */
  controls?: React.ReactNode;
  notice?: React.ReactNode;
  hint?: React.ReactNode;
  className?: string;
};

/**
 * The one message box of P02, P04 and P05.
 *
 * Enter sends and Shift+Enter makes a new line; an IME composition never sends
 * by accident. References are chips above the text and are cleared by the
 * caller after a successful send. There is no Stop control here: stopping is a
 * separate product action owned by the permission work.
 */
export function PromptInput({
  taskId,
  value,
  onValueChange,
  onSend,
  references,
  onReferencesChange,
  busy = false,
  disabled = false,
  sendDisabled = false,
  large = false,
  autoFocus = false,
  placeholder = 'پیام بده…',
  sendLabel,
  controls,
  notice,
  hint,
  className,
}: PromptInputProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const uploadInput=useRef<HTMLInputElement>(null);
  const [uploadError,setUploadError]=useState('');
  const workspaceId=useBackend(s=>s.settings?.workspace.id);
  const [caret,setCaret]=useState(0),[focused,setFocused]=useState(false),[dismissed,setDismissed]=useState(false);
  const [skills,setSkills]=useState<AvailableSkill[]>([]),[skillState,setSkillState]=useState<'loading'|'ready'|'error'>('loading'),[selectedSkill,setSelectedSkill]=useState(0);
  const skillListId=useId();
  const insertedCaret=useRef<number|null>(null);
  useLayoutEffect(()=>{
    if(insertedCaret.current===null)return;
    const position=insertedCaret.current;insertedCaret.current=null;
    textarea.current?.focus();textarea.current?.setSelectionRange(position,position);setCaret(position);
  },[value]);
  const mention=focused&&!disabled&&!dismissed?skillMention(value,caret):null;
  const slashOpen=mention!==null;
  const matches=skills.filter(skill=>skill.name.includes(mention?.query??'')||(skill.description??'').toLowerCase().includes(mention?.query??''));
  useEffect(()=>{
    if(!slashOpen)return;
    let current=true;setSkillState('loading');setSkills([]);
    availableSkills(taskId,workspaceId).then(items=>{if(current){setSkills(items);setSkillState('ready');}}).catch(()=>{if(current)setSkillState('error');});
    return()=>{current=false;};
  },[slashOpen,taskId,workspaceId]);
  useEffect(()=>{setSelectedSkill(0);},[mention?.query]);
  useEffect(()=>{if(slashOpen)document.getElementById(`${skillListId}-${selectedSkill}`)?.scrollIntoView({block:'nearest'});},[slashOpen,selectedSkill,skillListId]);
  const chooseSkill=(name:string)=>{
    if(!mention)return;
    const next=insertSkillMention(value,mention,name);insertedCaret.current=next.caret;onValueChange(next.text);setDismissed(true);
  };
  const upload=async(file:File)=>{
    setUploadError('');if(file.size>2_000_000){setUploadError('حداکثر اندازهٔ پیوست ۲ مگابایت است.');return;}
    try{
      const data=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
      const result=await api.post<{path:string}>('/attachments',{name:file.name,data});
      onReferencesChange([...references,result.path]);
    }catch(e){setUploadError(e instanceof ApiError?e.message:'بارگذاری پیوست ممکن نشد.');}
  };

  const submit = async () => {
    const text = value.trim();
    if (!text || disabled || sendDisabled || sending) return;
    setSending(true);
    try {
      await onSend();
    } finally {
      setSending(false);
    }
  };

  return (
    <div className={cn('bg-surface border-input focus-within:border-ring flex flex-col gap-2.5 rounded-xl border p-3.5 transition-colors', className)}>
      {notice}
      {references.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {references.map((path) => (
            <span
              key={path}
              className="bg-raised text-muted-foreground flex max-w-full items-center gap-1 rounded-md px-2 py-1 text-[11px]"
            >
              <PaperclipIcon className="size-3 shrink-0" />
              <PathText path={path} className="max-w-52 truncate" />
              <button
                type="button"
                aria-label={`حذف مرجع ${path}`}
                className="hover:text-foreground ms-0.5 shrink-0 rounded p-0.5"
                onClick={() => onReferencesChange(references.filter((item) => item !== path))}
              >
                <XIcon className="size-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="relative">
      {slashOpen&&<div className="bg-panel mb-2 overflow-hidden rounded-lg border shadow-xl">
        <div className="border-b px-3 py-2 text-xs text-muted-foreground">مهارت‌ها · ↑ ↓ انتخاب · Enter یا Tab درج · Esc بستن</div>
        <ul id={skillListId} role="listbox" aria-label="مهارت‌های قابل فراخوانی" className="max-h-60 overflow-y-auto">
          {skillState==='ready'&&matches.map((skill,index)=><li id={`${skillListId}-${index}`} key={skill.name} role="option" aria-selected={selectedSkill===index} onMouseDown={event=>event.preventDefault()} onClick={()=>chooseSkill(skill.name)} onMouseEnter={()=>setSelectedSkill(index)} className={cn('cursor-pointer px-3 py-2 text-start',selectedSkill===index?'bg-primary-soft':'hover:bg-hover')}><span dir="ltr" className="text-sm text-primary">/{skill.name}</span><p dir="auto" className="line-clamp-2 text-xs leading-6 text-muted-foreground">{skill.description}</p></li>)}
        </ul>
        {(skillState!=='ready'||matches.length===0)&&<p role="status" className="px-3 py-3 text-xs text-muted-foreground">{skillState==='loading'?'در حال خواندن مهارت‌ها…':skillState==='error'?'خواندن مهارت‌ها ممکن نشد؛ دوباره / را تایپ کن.':skills.length?'مهارتی با این نام پیدا نشد.':taskId?'مهارتی در این گفتگو فعال نیست؛ از «مهارت» اضافه و مهارت‌های گفتگو را به‌روز کن.':'مهارت فعالی نیست؛ از دکمهٔ «مهارت» یکی اضافه کن.'}</p>}
      </div>}
      <textarea
        ref={textarea}
        aria-label="پیام به ایجنت"
        aria-autocomplete="list"
        aria-controls={slashOpen?skillListId:undefined}
        aria-expanded={slashOpen}
        aria-activedescendant={slashOpen&&skillState==='ready'&&matches[selectedSkill]?`${skillListId}-${selectedSkill}`:undefined}
        value={value}
        autoFocus={autoFocus}
        disabled={disabled}
        onChange={(event) => {onValueChange(event.target.value);setCaret(event.target.selectionStart);setDismissed(false);}}
        onSelect={event=>{setCaret(event.currentTarget.selectionStart);}}
        onFocus={event=>{setFocused(true);setCaret(event.currentTarget.selectionStart);}}
        onBlur={()=>{setFocused(false);setDismissed(false);}}
        onKeyDown={(event) => {
          // Enter during a Persian/IME composition confirms the composition, not the message.
          if (event.nativeEvent.isComposing) return;
          if(slashOpen){
            if(event.key==='Escape'){event.preventDefault();setDismissed(true);return;}
            if(event.key==='ArrowDown'||event.key==='ArrowUp'){
              event.preventDefault();if(matches.length)setSelectedSkill(index=>(index+(event.key==='ArrowDown'?1:-1)+matches.length)%matches.length);return;
            }
            if((event.key==='Enter'&&!event.shiftKey)||event.key==='Tab'){
              if(skillState==='ready'&&matches[selectedSkill]){event.preventDefault();chooseSkill(matches[selectedSkill].name);return;}
              if(event.key==='Enter'){event.preventDefault();return;}
            }
          }
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            void submit();
          }
        }}
        rows={large ? 3 : 2}
        placeholder={placeholder}
        className="scrollbar-minimal placeholder:text-muted-foreground block max-h-56 min-h-[64px] w-full resize-none bg-transparent text-[15px] leading-7 outline-none disabled:cursor-not-allowed"
      />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <QuickSkills taskId={taskId} onSelect={name=>{onValueChange(`/${name} ${value}`);textarea.current?.focus();}}/>
        <input ref={uploadInput} type="file" aria-label="بارگذاری پیوست" className="hidden" onChange={event=>{const file=event.target.files?.[0];if(file)void upload(file);event.target.value='';}}/>
        <button type="button" className={composerTool} onClick={() => uploadInput.current?.click()} disabled={disabled}>
          <PaperclipIcon />
          پیوست
          {references.length > 0 && <span className="text-faint">({references.length.toLocaleString('fa-IR')})</span>}
        </button>
        <button type="button" className={composerTool} onClick={()=>setPickerOpen(true)} disabled={disabled}>فایل پروژه</button>
        {controls}
        <div className="flex-1" />
        {sendLabel && <span className="text-faint hidden text-[11px] sm:inline">Enter برای ارسال</span>}
        <Button
          size={sendLabel ? 'default' : 'icon'}
          disabled={disabled || sendDisabled || sending || !value.trim()}
          onClick={() => void submit()}
          aria-label={sendLabel ?? 'ارسال'}
        >
          {sending ? <CircleNotchIcon className="animate-spin" /> : <ArrowUpIcon weight="bold" />}
          {sendLabel}
        </Button>
      </div>

      {uploadError&&<p role="alert" className="text-danger text-xs">{uploadError}</p>}
      {hint && <div className="text-faint text-[11px] leading-5">{hint}</div>}

      <ReferencePicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        selected={references}
        onSelect={(path) => {
          if (!references.includes(path)) onReferencesChange([...references, path]);
          textarea.current?.focus();
        }}
      />
    </div>
  );
}
