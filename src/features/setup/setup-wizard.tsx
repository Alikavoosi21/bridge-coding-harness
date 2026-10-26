'use client';

import { ArrowLeftIcon, ArrowRightIcon, ArrowsClockwiseIcon, FolderOpenIcon, PlusIcon, StarIcon, WarningIcon, XIcon } from '@phosphor-icons/react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { BridgeSymbol } from '@/components/shared/brand';
import { Button } from '@/components/ui/button';
import { Badge, Input, PathText } from '@/components/ui/primitives';
import { api, ApiError, type Model, type ProbeResponse, type Settings } from '@/lib/api';
import { useBackend } from '@/lib/backend';
import { capabilityOf, DISCLOSURE_KEYS, isDemo, missingLabel, resumeStep, stepTitles, type DisclosureKey, type MissingPrerequisite, type SetupStep } from '@/lib/harness/setup-flow';
import { ModelDialog } from '@/features/settings/model-dialog';
import { cn } from '@/lib/utils';
import { EnvironmentStep } from './environment-step';
import { ReviewStep } from './review-step';

function defaultModelOf(settings: Settings): Model | null {
  return settings.models.find((model) => model.id === settings.default_model) ?? null;
}

function modelUsable(model: Model | null): boolean {
  return Boolean(model) && (model!.base_url.startsWith('demo://') || model!.has_key);
}

/** Four resumable steps: project, model, read-only environment, review. */
export function SetupWizard({ closable, onClose }: { closable: boolean; onClose: () => void }) {
  const settings = useBackend((s) => s.settings);
  const readiness = useBackend((s) => s.readiness);
  const known = useBackend((s) => s.workspace?.known ?? []);
  const openWorkspace = useBackend((s) => s.openWorkspace);
  const refreshSettings = useBackend((s) => s.refreshSettings);
  const refreshReadiness = useBackend((s) => s.refreshReadiness);

  const [step, setStep] = useState<SetupStep | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [path, setPath] = useState('');
  const [name, setName] = useState('');
  const [changingFolder, setChangingFolder] = useState(true);
  const [disclosures, setDisclosures] = useState<Partial<Record<DisclosureKey, boolean>>>({});
  const [dialog, setDialog] = useState<{ open: boolean; editing: Model | null; key: number }>({ open: false, editing: null, key: 0 });
  const [probing, setProbing] = useState<string | null>(null);

  // Resume once, from what the backend recorded; later local moves must not be
  // undone by a settings refresh.
  useEffect(() => {
    if (step !== null || !settings) return;
    const model = defaultModelOf(settings);
    const resumed = resumeStep(settings.setup.step, {
      workspaceOpen: settings.workspace.open,
      modelConfigured: Boolean(model),
      modelHasKey: modelUsable(model),
    });
    setStep(resumed);
    setDisclosures(settings.disclosures);
    setChangingFolder(!settings.workspace.open);
  }, [settings, step]);

  useEffect(() => {
    refreshReadiness().catch(() => {});
  }, [refreshReadiness]);

  if (!settings || step === null) {
    return (
      <div className="bg-sidebar flex h-dvh items-center justify-center">
        <ArrowsClockwiseIcon className="text-primary size-7 animate-spin" />
      </div>
    );
  }

  const model = defaultModelOf(settings);

  const storeStep = async (next: SetupStep, completed = false, acknowledgements?: Partial<Record<DisclosureKey, boolean>>) => {
    await api.put<Settings>('/settings', {
      setup: {
        step: next,
        completed,
        ...(acknowledgements ? { acknowledgements } : {}),
      },
    });
    await refreshSettings();
  };

  const go = async (next: SetupStep) => {
    setBusy(true);
    setError(null);
    try {
      // Reviewing a completed setup must not turn `completed` off; only the
      // final step changes that flag.
      if (!settings.setup.completed) await storeStep(next);
      if (next >= 3) await refreshReadiness();
      setStep(next);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'ذخیرهٔ گام ممکن نشد.');
    } finally {
      setBusy(false);
    }
  };

  const back = async () => {
    if (!step || step === 1) return;
    const next = (step - 1) as SetupStep;
    setStep(next);
    // A completed setup is never silently uncompleted by walking back.
    if (settings.setup.completed) return;
    try {
      await storeStep(next);
    } catch {
      // The step is local; the backend still resumes at the last saved one.
    }
  };

  const open = async (folder: string, workspaceName?: string) => {
    if (!folder.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await openWorkspace(folder.trim(), workspaceName?.trim() || undefined);
      if (!settings.setup.completed) await storeStep(2);
      await refreshReadiness();
      setStep(2);
      setChangingFolder(false);
      setPath('');
      setName('');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'باز کردن پوشه ممکن نشد.');
    } finally {
      setBusy(false);
    }
  };

  const pick = async () => {
    const folder = await window.desktop?.pickFolder?.();
    if (folder) await open(folder, name);
    else if (!window.desktop?.pickFolder) setError('انتخاب پوشه در برنامهٔ دسکتاپ ممکن است؛ مسیر را دستی بنویسید.');
  };

  const selectDefault = async (modelId: string) => {
    setError(null);
    try {
      await api.put<Settings>('/settings', { default_model: modelId });
      await refreshSettings();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'انتخاب مدل ممکن نشد.');
    }
  };

  const probe = async (modelId: string) => {
    setProbing(modelId);
    setError(null);
    try {
      const result = await api.post<ProbeResponse>('/models/probe', { id: modelId });
      await Promise.all([refreshSettings(), refreshReadiness()]);
      const view = capabilityOf({ base_url: result.probe.demo ? 'demo://' : 'https://probe.invalid', has_key: true, capabilities: result.probe });
      toast.success(`نتیجهٔ بررسی: ${view.label}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'بررسی مدل ممکن نشد.');
    } finally {
      setProbing(null);
    }
  };

  const finish = async () => {
    setBusy(true);
    setError(null);
    try {
      await storeStep(4, true, disclosures);
      await refreshReadiness();
      onClose();
    } catch (e) {
      if (e instanceof ApiError && e.code === 'setup_incomplete') {
        const missing = (e.details?.missing ?? []) as MissingPrerequisite[];
        setError(`راه‌اندازی کامل نشد: ${missing.map((item) => missingLabel[item]).join(' ')}`);
        setStep(missing.includes('workspace') ? 1 : 2);
      } else {
        setError(e instanceof ApiError ? e.message : 'پایان راه‌اندازی ممکن نشد.');
      }
    } finally {
      setBusy(false);
    }
  };

  const canGoNext = step === 1 ? settings.workspace.open : step === 2 ? modelUsable(model) : true;

  return (
    <div className="bg-sidebar flex h-dvh flex-col">
      <div className="desktop-strip app-drag" />
      <div className="scrollbar-minimal flex flex-1 items-start justify-center overflow-y-auto p-6">
        {/* `items-start` + `my-auto`: a short card is centred, a tall one starts at
            the top and stays scrollable. Centring directly in the scroll
            container would clip the top of an oversized card. */}
        <div className="bg-panel my-auto flex w-full max-w-3xl flex-col rounded-xl border p-8">
          <div className="flex items-center gap-3">
            <BridgeSymbol size={36} />
            <Button variant="ghost" size="xs" disabled={busy} onClick={async () => {
              setBusy(true);
              try { await api.post('/setup/defer', {}); await refreshSettings(); onClose(); }
              catch (e) { setError(e instanceof ApiError ? e.message : 'رد کردن راه‌اندازی ممکن نشد.'); }
              finally { setBusy(false); }
            }}>بعداً تنظیم می‌کنم</Button>
            <div className="flex flex-1 items-center gap-1.5" role="progressbar" aria-valuemin={1} aria-valuemax={4} aria-valuenow={step}>
              {([1, 2, 3, 4] as SetupStep[]).map((item) => (
                <span key={item} className={cn('h-1.5 flex-1 rounded-full transition-all duration-200', item === step ? 'bg-primary' : item < step ? 'bg-primary/40' : 'bg-secondary')} />
              ))}
            </div>
            {closable ? (
              <Button variant="muted" size="xs" onClick={onClose}>
                <XIcon /> بستن
              </Button>
            ) : (
              <span className="text-muted-foreground text-xs">گام {step} از ۴</span>
            )}
          </div>

          <h1 className="mt-7 text-xl font-semibold tracking-tight">{stepTitles[step].title}</h1>
          <p className="text-muted-foreground mt-2 text-sm leading-7">{stepTitles[step].lead}</p>

          <div className="mt-7 min-h-[22rem]">
            {step === 1 && (
              <StepProject
                settings={settings}
                path={path}
                name={name}
                changing={changingFolder}
                busy={busy}
                known={known}
                onPath={setPath}
                onName={setName}
                onChangeFolder={() => setChangingFolder(true)}
                onOpen={open}
                onPick={pick}
              />
            )}

            {step === 2 && (
              <div className="space-y-4">
                {settings.models.some((item) => isDemo(item)) && (
                  <div className="bg-primary-soft/40 border-primary/20 rounded-xl border px-4 py-3 text-xs leading-6">
                    <span className="font-semibold">مدل نمایشی روشن است:</span> بدون کلید و بدون هیچ تماس بیرونی، روند کار را نشان می‌دهد. برای کار واقعی مدل خودتان را تعریف کنید؛ تا آن زمان تغییر فایل با مدل واقعی ممکن نیست.
                  </div>
                )}

                <div className="bg-popover divide-border divide-y overflow-hidden rounded-xl border">
                  {settings.models.map((item) => {
                    const view = capabilityOf(item);
                    const selected = item.id === settings.default_model;
                    return (
                      <div key={item.id} className={cn('flex flex-wrap items-start gap-3 px-4 py-3', selected && 'bg-primary-soft/25')}>
                        <button type="button" onClick={() => void selectDefault(item.id)} aria-pressed={selected} className="mt-0.5" title="انتخاب به‌عنوان مدل پیش‌فرض">
                          {selected ? <StarIcon weight="fill" className="text-primary size-5" /> : <StarIcon className="text-muted-foreground size-5" />}
                        </button>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-medium">{item.name}</span>
                            {selected && <Badge tone="primary">انتخاب‌شده</Badge>}
                            {isDemo(item) && <Badge tone="outline">نمایشی</Badge>}
                            <Badge tone={view.tone}>{view.label}</Badge>
                          </div>
                          <div dir="ltr" className="text-muted-foreground mt-1 truncate font-mono text-[0.6875rem]">
                            {item.model} · {item.base_url}
                          </div>
                          <p className="text-muted-foreground mt-1 text-xs leading-5">{view.detail}</p>
                        </div>
                        <div className="flex items-center gap-1">
                          {!isDemo(item) && item.has_key && (
                            <Button variant="outline" size="xs" disabled={probing === item.id} onClick={() => void probe(item.id)}>
                              <ArrowsClockwiseIcon className={cn(probing === item.id && 'animate-spin')} /> بررسی
                            </Button>
                          )}
                          <Button variant="ghost" size="xs" onClick={() => setDialog((d) => ({ open: true, editing: item, key: d.key + 1 }))}>
                            ویرایش
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="outline" size="sm" onClick={() => setDialog((d) => ({ open: true, editing: null, key: d.key + 1 }))}>
                    <PlusIcon /> تعریف مدل تازه
                  </Button>
                  {!modelUsable(model) && (
                    <span className="text-warning flex items-center gap-1.5 text-xs">
                      <WarningIcon className="size-4" /> {model ? 'این مدل کلید ندارد؛ برای ادامه کلید را ذخیره کنید.' : 'یک مدل انتخاب کنید.'}
                    </span>
                  )}
                </div>

                {model && !isDemo(model) && capabilityOf(model).canWrite === false && model.has_key && (
                  <p className="text-muted-foreground text-xs leading-6">
                    می‌توانید بدون بررسی ادامه دهید، اما تا وقتی بررسی ابزار موفق نشود، همهٔ کارها فقط خواندن خواهند بود.
                  </p>
                )}
              </div>
            )}

            {step === 3 &&
              (settings.workspace.id ? (
                <EnvironmentStep
                  workspaceId={settings.workspace.id}
                  savedProfile={settings.workspace.profile}
                  readiness={readiness}
                  refreshAll={async () => {
                    await Promise.all([refreshSettings(), refreshReadiness()]);
                  }}
                  onError={setError}
                />
              ) : (
                <p className="text-danger text-sm">شناسهٔ فضای کاری پیدا نشد. به گام ۱ برگردید.</p>
              ))}

            {step === 4 && (
              <ReviewStep
                settings={settings}
                readiness={readiness}
                disclosures={disclosures}
                onChange={(key, value) => setDisclosures((current) => ({ ...current, [key]: value }))}
                onFinish={finish}
                busy={busy}
              />
            )}
          </div>

          {error && (
            <div className="border-danger/30 bg-danger-soft/30 mt-4 flex items-start gap-2.5 rounded-xl border px-4 py-3 text-sm">
              <WarningIcon className="text-danger mt-0.5 size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="mt-8 flex items-center justify-between gap-3 border-t pt-5">
            <Button variant="ghost" size="sm" className={cn(step === 1 && 'invisible')} onClick={back} disabled={busy}>
              <ArrowRightIcon /> قبلی
            </Button>
            {step < 4 ? (
              <Button onClick={() => void go((step + 1) as SetupStep)} disabled={busy || !canGoNext}>
                {busy ? 'در حال ذخیره…' : step === 1 ? 'ادامه' : step === 2 ? 'محیط و بررسی' : 'بازبینی'} <ArrowLeftIcon />
              </Button>
            ) : (
              <span className="text-muted-foreground text-xs">پایان راه‌اندازی را از داخل همین صفحه ثبت کنید.</span>
            )}
          </div>
        </div>
      </div>

      <ModelDialog
        key={dialog.key}
        editing={dialog.editing}
        open={dialog.open}
        onOpenChange={(open) => setDialog((d) => ({ ...d, open }))}
        onSaved={() => {
          refreshSettings().catch(() => {});
          refreshReadiness().catch(() => {});
        }}
      />
    </div>
  );
}

function StepProject({
  settings,
  path,
  name,
  changing,
  busy,
  known,
  onPath,
  onName,
  onChangeFolder,
  onOpen,
  onPick,
}: {
  settings: Settings;
  path: string;
  name: string;
  changing: boolean;
  busy: boolean;
  known: { path: string; name: string }[];
  onPath: (value: string) => void;
  onName: (value: string) => void;
  onChangeFolder: () => void;
  onOpen: (folder: string, name?: string) => Promise<void>;
  onPick: () => Promise<void>;
}) {
  const hasWorkspace = settings.workspace.open && !changing;

  if (hasWorkspace) {
    return (
      <div className="space-y-5">
        <div className="bg-popover rounded-xl border px-4 py-4">
          <div className="text-sm font-medium">{settings.workspace.name}</div>
          <PathText path={settings.workspace.path ?? ''} className="text-muted-foreground mt-1 text-xs" />
          <p className="text-muted-foreground mt-2 text-xs leading-6">این پوشه جایی است که ایجنت می‌خواند، می‌نویسد و سابقه نگه می‌دارد. برای پوشهٔ دیگر، همین‌جا عوضش کنید.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={onChangeFolder} disabled={busy}>
            <FolderOpenIcon /> تغییر پوشه
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="text-muted-foreground mb-1.5 block text-xs font-medium">نام فضای کاری (اختیاری)</label>
        <Input placeholder="مثلاً: API پروژهٔ من" maxLength={60} value={name} onChange={(event) => onName(event.target.value)} />
        <p className="text-muted-foreground mt-1 text-xs">اگر خالی بماند، نام پوشه نمایش داده می‌شود. بعداً در تنظیمات قابل تغییر است.</p>
      </div>

      {typeof window !== 'undefined' && window.desktop?.pickFolder ? (
        <Button onClick={() => void onPick()} disabled={busy}>
          <FolderOpenIcon /> {busy ? 'در حال باز کردن…' : 'انتخاب پوشه'}
        </Button>
      ) : (
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input dir="ltr" className="font-mono" placeholder="D:\MyWorkspace" value={path} onChange={(event) => onPath(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && void onOpen(path, name)} />
          <Button onClick={() => void onOpen(path, name)} disabled={busy || !path.trim()}>
            باز کن
          </Button>
        </div>
      )}

      {settings.workspace.open && changing && (
        <p className="text-muted-foreground text-xs leading-6">پوشهٔ فعلی: <PathText path={settings.workspace.path ?? ''} className="inline text-xs" /></p>
      )}

      {known.length > 0 && (
        <div className="border-t pt-4">
          <div className="text-muted-foreground mb-2 text-xs">فضاهای کاری قبلی</div>
          <div className="space-y-1">
            {known.map((item) => (
              <button key={item.path} type="button" onClick={() => void onOpen(item.path)} disabled={busy} className="hover:bg-hover block w-full rounded-lg px-3 py-2 text-start disabled:opacity-50">
                <span className="block truncate text-sm font-medium">{item.name}</span>
                <PathText path={item.path} className="text-muted-foreground text-xs" />
              </button>
            ))}
          </div>
        </div>
      )}

      <p className="text-muted-foreground text-xs leading-6">
        پوشهٔ کل درایو یا پوشهٔ خانه را انتخاب نکنید؛ فضای کاری باید پوشه‌ای جدا برای همین کار باشد. فایل‌های حساس مانند <span dir="ltr" className="font-mono">.env</span> هرگز به سندباکس کپی نمی‌شوند.
      </p>
    </div>
  );
}
