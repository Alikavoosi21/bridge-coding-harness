'use client';

import { CheckCircleIcon, WarningCircleIcon } from '@phosphor-icons/react';
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { Badge, Input, Label, Switch } from '@/components/ui/primitives';
import { Button } from '@/components/ui/button';
import { Dialog, DialogClose, DialogContent } from '@/components/ui/overlays';
import { api, ApiError, type Model, type ModelCapabilities, type ProbeResponse } from '@/lib/api';
import { capabilityOf } from '@/lib/harness/setup-flow';
import { cn } from '@/lib/utils';

// Any OpenAI- or Anthropic-compatible endpoint works; these only pre-fill the address.
const presets = [
  { label: 'OpenAI', baseUrl: 'https://api.openai.com/v1' },
  { label: 'Anthropic', baseUrl: 'https://api.anthropic.com' },
  { label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1' },
  { label: 'Ollama (محلی)', baseUrl: 'http://localhost:11434/v1' },
];

/**
 * Add or edit a model, and ask it one harmless tool-call question.
 *
 * The probe here is deliberately not persisted: an unsaved address or key must
 * not replace evidence for the saved model. `probe after save` in the list
 * writes the result. Keys are sent once and never returned by the API.
 */
export function ModelDialog({ editing, open, onOpenChange, onSaved }: { editing: Model | null; open: boolean; onOpenChange: (open: boolean) => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    name: editing?.name ?? '',
    base_url: editing?.base_url ?? '',
    model: editing?.model ?? '',
    api_key: '',
    streaming: editing?.streaming ?? true,
  });
  const [probing, setProbing] = useState(false);
  const [result, setResult] = useState<ModelCapabilities | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<{id:string;name:string}[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [catalogError, setCatalogError] = useState('');
  const [filter, setFilter] = useState('');
  const [saving, setSaving] = useState(false);
  const [makeDefault, setMakeDefault] = useState(!editing);
  const catalogRevision = useRef(0);
  const set = (key: keyof typeof form, value: string | boolean) => {
    if(key==='base_url'||key==='api_key'){catalogRevision.current++;setCatalog([]);setCatalogError('');}
    setResult(null);
    setProbeError(null);
    setForm((prev) => ({ ...prev, [key]: value }));
  };
  const valid = form.base_url.trim() && form.model.trim();

  const save = async () => {
    setSaving(true);
    try {
      const saved=await api.post<Model>('/models', { id: editing?.id, ...form, api_key: form.api_key || undefined });
      if(makeDefault)await api.put('/settings',{default_model:saved.id});
      toast.success(editing ? 'مدل به‌روز شد.' : 'مدل اضافه شد.');
      onSaved();
      onOpenChange(false);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'ذخیره ممکن نشد.');
    } finally {setSaving(false);}
  };
  const discover = async () => {
    const revision=++catalogRevision.current;setDiscovering(true);setCatalogError('');setCatalog([]);
    try {
      const response=await api.post<{models:{id:string;name:string}[];partial:boolean}>('/models/discover',{
        base_url:form.base_url.trim(),api_key:form.api_key||undefined,
        id:editing&&editing.base_url.replace(/\/$/,'')===form.base_url.trim().replace(/\/$/,'')&&!form.api_key?editing.id:undefined,
      });
      if(revision!==catalogRevision.current)return;
      setCatalog(response.models);
      if(!response.models.length)setCatalogError('مدلی در پاسخ سرویس نبود؛ نام دقیق مدل را دستی وارد کن.');
      else if(response.partial)setCatalogError('بخشی از مدل‌های سرویس نمایش داده شده است؛ می‌توانی نام دقیق را دستی وارد کنی.');
    }catch(e){if(revision===catalogRevision.current)setCatalogError(e instanceof ApiError?e.message:'دریافت مدل‌ها ممکن نشد.');}
    finally{setDiscovering(false);}
  };

  const probe = async () => {
    if (!valid) return;
    setProbing(true);
    setProbeError(null);
    try {
      // A key the user just typed belongs to this check only. Reusing the saved
      // model id keeps the stored key in the backend and never sends it back.
      const unchanged = editing && editing.base_url === form.base_url.trim() && editing.model === form.model.trim() && !form.api_key;
      const body = unchanged
        ? { id: editing.id, persist: false }
        : { base_url: form.base_url.trim(), model: form.model.trim(), api_key: form.api_key || undefined, persist: false };
      const response = await api.post<ProbeResponse>('/models/probe', body);
      setResult(response.probe);
    } catch (e) {
      setProbeError(e instanceof ApiError ? e.message : 'بررسی ممکن نشد.');
    } finally {
      setProbing(false);
    }
  };

  const view = result
    ? capabilityOf({ base_url: form.base_url, has_key: Boolean(form.api_key) || Boolean(editing?.has_key), capabilities: result })
    : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={editing ? 'ویرایش مدل' : 'تعریف مدل'}
        description="سرویس را انتخاب کن، کلید را همین‌جا وارد کن و مدل‌های آن را بگیر. نام مدل را هم می‌توانی دستی وارد کنی."
        footer={
          <>
            <ButtonProbe probing={probing} valid={Boolean(valid)} onClick={probe} />
            <DialogClose asChild>
              <Button variant="ghost" size="sm">انصراف</Button>
            </DialogClose>
            <Button size="sm" disabled={!valid||saving} onClick={()=>void save()}>{saving?'در حال ذخیره…':'ذخیره'}</Button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <Label>Base URL</Label>
            <Input aria-label="Base URL" dir="ltr" className="font-mono" placeholder="https://api.example.com/v1" value={form.base_url} onChange={(e) => set('base_url', e.target.value)} />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {presets.map((preset) => (
                <button key={preset.label} type="button" onClick={() => set('base_url', preset.baseUrl)} className={cn('border-border h-8 rounded-md border px-3 text-xs', form.base_url === preset.baseUrl ? 'border-primary bg-primary-soft text-primary' : 'text-muted-foreground hover:bg-hover')}>
                  {preset.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <Label>API Key</Label>
            <Input aria-label="API Key" dir="ltr" type="password" className="font-mono" autoComplete="off" placeholder={editing?.has_key ? 'کلید ذخیره‌شده حفظ می‌شود؛ برای تغییر، کلید جدید را بنویسید' : 'sk-...'} value={form.api_key} onChange={(e) => set('api_key', e.target.value)} />
          </div>
          <div className="rounded-lg border p-3">
            <Button variant="outline" size="sm" disabled={!form.base_url.trim()||discovering} onClick={()=>void discover()}>{discovering?'در حال دریافت مدل‌ها…':'دریافت مدل‌های سرویس'}</Button>
            {catalogError&&<p role="status" className="text-warning mt-2 text-xs leading-6">{catalogError}</p>}
            {!!catalog.length&&<div className="mt-3 space-y-2">
              <Input aria-label="جستجوی مدل" placeholder="جستجو در مدل‌های سرویس…" value={filter} onChange={e=>setFilter(e.target.value)}/>
              <select aria-label="مدل‌های سرویس" size={5} value={form.model} onChange={e=>set('model',e.target.value)} className="bg-surface w-full rounded-lg border p-2 font-mono text-sm" dir="ltr">
                {catalog.filter(item=>(item.id+' '+item.name).toLowerCase().includes(filter.toLowerCase())).map(item=><option key={item.id} value={item.id}>{item.name===item.id?item.id:`${item.name} — ${item.id}`}</option>)}
              </select><p className="text-muted-foreground text-xs">وجود مدل در فهرست به معنی پشتیبانی ابزار نیست؛ توانایی آن را جدا بررسی کن.</p>
            </div>}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label>Model Name</Label>
              <Input aria-label="Model Name" dir="ltr" className="font-mono" placeholder="نام دقیق مدل" value={form.model} onChange={(e) => set('model', e.target.value)} />
            </div>
            <div>
              <Label>نام نمایشی (اختیاری)</Label>
              <Input placeholder="مثلاً: مدل دقیق" value={form.name} onChange={(e) => set('name', e.target.value)} />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={makeDefault} onChange={e=>setMakeDefault(e.target.checked)} className="accent-primary"/>استفاده به‌عنوان مدل پیش‌فرض</label>
          <label className="flex cursor-pointer items-center justify-between gap-3 text-sm">
            <span>
              نمایش پاسخ کلمه‌به‌کلمه
              <span className="text-muted-foreground block text-xs">اگر سرویس شما با ابزارها خطا می‌دهد، این را خاموش کنید.</span>
            </span>
            <Switch checked={form.streaming} onCheckedChange={(value) => set('streaming', value)} />
          </label>

          {(view || probeError) && (
            <div className={cn('rounded-xl border px-4 py-3 text-sm', view?.tone === 'success' ? 'border-success/30 bg-success-soft/40' : 'border-warning/30 bg-warning-soft/40')}>
              {probeError ? (
                <p className="flex items-start gap-2">
                  <WarningCircleIcon className="text-warning mt-0.5 size-4 shrink-0" />
                  <span>{probeError}</span>
                </p>
              ) : (
                view && (
                  <div className="flex items-start gap-2">
                    {view.canWrite ? <CheckCircleIcon className="text-success mt-0.5 size-4 shrink-0" /> : <WarningCircleIcon className="text-warning mt-0.5 size-4 shrink-0" />}
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={view.tone}>{view.label}</Badge>
                        <span className="text-muted-foreground text-xs">{result?.provider_reachable ? 'سرویس پاسخ داد' : 'سرویس پاسخ نداد'}</span>
                      </div>
                      <p className="text-muted-foreground mt-1.5 text-xs leading-6">{view.detail}</p>
                      {result?.error_message && <p dir="ltr" className="text-muted-foreground mt-1 font-mono text-[0.6875rem] break-all">{result.error_message}</p>}
                    </div>
                  </div>
                )
              )}
            </div>
          )}

          <p className="text-muted-foreground text-xs leading-6">
            کلید در مخزن امن سیستم‌عامل نگه داشته می‌شود، نه در پوشهٔ فضای کاری، و فقط به همین آدرس فرستاده می‌شود. «بررسی توانایی» یک فراخوانی ابزار آزمایشی می‌فرستد و هیچ فایلی از پروژه را نمی‌خواند.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ButtonProbe({ probing, valid, onClick }: { probing: boolean; valid: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!valid || probing}
      className="text-primary hover:bg-primary-soft me-auto inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-xs font-medium disabled:pointer-events-none disabled:opacity-50"
    >
      {probing ? 'در حال بررسی…' : 'بررسی توانایی ابزار'}
    </button>
  );
}
