'use client';

import {
  ArrowsClockwiseIcon,
  CheckCircleIcon,
  CpuIcon,
  CubeIcon,
  FolderSimpleIcon,
  InfoIcon,
  PlugsConnectedIcon,
  StackIcon,
  WarningIcon,
  XCircleIcon,
} from '@phosphor-icons/react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { BlockLabel, Row, RowGroup } from '@/components/ui/patterns';
import { Badge, PathText, Switch } from '@/components/ui/primitives';
import { api, ApiError, type ModelCapabilities, type Readiness, type Settings } from '@/lib/api';
import { useBackend } from '@/lib/backend';
import { capabilityOf, disclosureText, DISCLOSURE_KEYS, type DisclosureKey } from '@/lib/harness/setup-flow';
import { useUi } from '@/lib/store';
import { cn } from '@/lib/utils';

const issueText: Record<string, string> = {
  schema_invalid: 'پایگاه‌دادهٔ داخلی قابل خواندن نیست.',
  schema_outdated: 'نسخهٔ پایگاه‌دادهٔ داخلی قدیمی است؛ برنامه باید آن را به‌روز کند.',
  docker_missing: 'Docker روی این سیستم نصب نیست.',
  docker_unavailable: 'Docker نصب است اما موتور آن در حال اجرا نیست.',
  image_missing: 'image سندباکس ساخته نشده است.',
  workspace_closed: 'هیچ پوشه‌ای باز نیست.',
  model_missing: 'هیچ مدلی انتخاب نشده است.',
  provider_key_missing: 'مدل انتخابی کلید API ندارد.',
  model_tools_unproven: 'توانایی ابزار این مدل بررسی نشده است.',
  model_tools_unavailable: 'این مدل فراخوانی ابزار را تأیید نکرده است.',
};

/** The server explains the task mode in technical English; the UI says the same fact in Persian. */
export function taskReasonText(readiness: Readiness | null): string {
  if (!readiness) return 'وضعیت سندباکس خوانده نشد؛ تغییر فایل قطعاً ممکن نیست.';
  if (readiness.task.can_write) return 'سندباکس آماده است؛ تغییر فایل ممکن است.';
  const codes = new Set(readiness.issues.map((issue) => issue.code));
  if (codes.has('workspace_closed')) return 'هیچ پوشه‌ای باز نیست؛ اول پروژه را انتخاب کنید.';
  if (codes.has('model_missing') || codes.has('provider_key_missing')) return 'اول مدل را وصل کنید؛ بدون آن هیچ کاری شروع نمی‌شود.';
  if (codes.has('model_tools_unproven') || codes.has('model_tools_unavailable')) return 'این مدل توانایی ابزار را تأیید نکرده؛ کار فقط می‌خواند و توضیح می‌دهد.';
  if (codes.has('docker_missing')) return 'Docker روی این سیستم نصب نیست؛ کار فقط می‌خواند.';
  if (codes.has('docker_unavailable')) return 'Docker نصب است اما موتور آن اجرا نشده؛ کار فقط می‌خواند.';
  if (codes.has('image_missing')) return 'image سندباکس ساخته نشده؛ کار فقط می‌خواند.';
  return 'سندباکس هنوز آماده نیست؛ کار فقط می‌خواند.';
}

function State({ ok, label, detail, tone }: { ok: boolean | null; label: string; detail?: React.ReactNode; tone?: 'warning' | 'danger' }) {
  const icon = ok === true ? <CheckCircleIcon className="text-success size-4 shrink-0" /> : ok === false ? <XCircleIcon className={cn('size-4 shrink-0', tone === 'danger' ? 'text-danger' : 'text-warning')} /> : <WarningIcon className="text-warning size-4 shrink-0" />;
  return (
    <div className="flex min-w-0 items-start gap-2.5">
      {icon}
      <div className="min-w-0">
        <div className="text-sm font-medium">{label}</div>
        {detail && <div className="text-muted-foreground mt-0.5 text-xs leading-5">{detail}</div>}
      </div>
    </div>
  );
}

/** The sandbox card, including the only place an image build can be agreed to. */
export function RuntimeCard({ readiness, onChanged }: { readiness: Readiness | null; onChanged: () => Promise<unknown> | void }) {
  const runtime = readiness?.runtime;
  const [consent, setConsent] = useState(false);
  const [building, setBuilding] = useState(false);
  const [output, setOutput] = useState<string | null>(null);

  const engineReachable = Boolean(runtime?.server_version);
  const canBuild = engineReachable && !runtime?.image_present;

  const build = async () => {
    if (!consent) return;
    setBuilding(true);
    setOutput(null);
    try {
      const result = await api.post<{ build: { output?: string } }>('/runtime/prepare', { consent: true });
      setOutput(result.build?.output || 'image با موفقیت ساخته شد.');
      setConsent(false);
      toast.success('image سندباکس ساخته شد.');
      await onChanged();
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'ساخت image ممکن نشد.';
      setOutput(message);
      toast.error(message);
    } finally {
      setBuilding(false);
    }
  };

  if (!runtime) {
    return <State ok={null} label="وضعیت سندباکس خوانده نشد" detail="دوباره تلاش کنید." tone="warning" />;
  }

  return (
    <div className="space-y-3">
      <State
        ok={runtime.available}
        label={runtime.available ? 'سندباکس آماده است' : runtime.server_version ? 'image سندباکس ساخته نشده' : 'Docker آماده نیست'}
        detail={
          runtime.available
            ? 'فرمان‌ها فقط داخل نسخهٔ کاری اجرا می‌شوند.'
            : runtime.server_version
              ? 'image سندباکس ساخته نشده؛ تغییر فایل ممکن نیست.'
              : 'Docker یا موتور آن در دسترس نیست؛ تغییر فایل ممکن نیست.'
        }
        tone={runtime.available ? undefined : 'warning'}
      />
      <div className="text-muted-foreground space-y-1 text-xs leading-6">
        <div>
          image: <span dir="ltr" className="font-mono">{runtime.image}</span>
        </div>
        {runtime.server_version && (
          <div>
            Docker: <span dir="ltr" className="font-mono">{runtime.server_version}</span>
          </div>
        )}
      </div>

      {canBuild && (
        <div className="bg-secondary/60 rounded-xl px-3.5 py-3">
          <p className="text-xs leading-6">
            ساخت image فقط از تعریف ثابت برنامه انجام می‌شود؛ هیچ فرمانی از این صفحه یا از مدل اجرا نمی‌شود. image با کاربر غیرروت، شبکهٔ قطع و سقف منابع اجرا خواهد شد.
          </p>
          {runtime.dockerfile && <PathText path={runtime.dockerfile} className="text-muted-foreground mt-1 text-[0.6875rem]" />}
          <label className="mt-3 flex cursor-pointer items-center justify-between gap-3 text-xs font-medium">
            <span>می‌فهمم و اجازهٔ ساخت این image را می‌دهم.</span>
            <Switch checked={consent} onCheckedChange={setConsent} disabled={building} />
          </label>
          <Button className="mt-2" size="xs" disabled={!consent || building} onClick={build}>
            {building ? 'در حال ساخت…' : 'ساخت image سندباکس'}
          </Button>
        </div>
      )}

      {!engineReachable && !runtime.server_version && (
        <p className="text-muted-foreground text-xs leading-6">
          {runtime.reason.includes('not installed')
            ? 'این برنامه Docker را خودش نصب نمی‌کند و نصاب پنهانی ندارد. Docker Desktop را از سایت رسمی نصب کنید و دوباره این صفحه را تازه کنید. راهنمای محلی در docs/local-setup.md است.'
            : 'Docker نصب است؛ برنامهٔ Docker را اجرا کنید و دوباره تازه کنید.'}
        </p>
      )}

      {output && (
        <pre dir="ltr" className="bg-secondary/60 text-muted-foreground max-h-40 overflow-auto rounded-lg px-3 py-2 font-mono text-[0.6875rem] whitespace-pre-wrap">
          {output}
        </pre>
      )}
    </div>
  );
}

/** The four Step-status cards, each with the action that actually fixes it. */
export function ReadinessPanel() {
  const readiness = useBackend((s) => s.readiness);
  const refreshReadiness = useBackend((s) => s.refreshReadiness);
  const refreshSettings = useBackend((s) => s.refreshSettings);
  const setSetupOpen = useUi((s) => s.setSetupOpen);
  const [busy, setBusy] = useState(false);
  const [probing, setProbing] = useState(false);

  useEffect(() => {
    refreshReadiness().catch(() => {});
  }, [refreshReadiness]);

  const refreshAll = async () => {
    setBusy(true);
    try {
      await Promise.all([refreshReadiness(), refreshSettings()]);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'تازه‌سازی ممکن نشد.');
    } finally {
      setBusy(false);
    }
  };

  const probeDefault = async () => {
    const modelId = readiness?.model.id;
    if (!modelId) return;
    setProbing(true);
    try {
      await api.post<{ probe: ModelCapabilities }>('/models/probe', { id: modelId });
      await refreshAll();
      toast.success('نتیجهٔ بررسی مدل ذخیره شد.');
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'بررسی مدل ممکن نشد.');
    } finally {
      setProbing(false);
    }
  };

  if (!readiness) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 py-8 text-sm">
        <ArrowsClockwiseIcon className="size-4 animate-spin" /> در حال خواندن وضعیت…
      </div>
    );
  }

  const model = readiness.model;
  const modelCapability = capabilityOf({
    base_url: model.demo ? 'demo://' : 'https://configured.invalid',
    has_key: model.has_key,
    capabilities: { tools: model.tools, error_code: model.capability_error ?? null },
  });

  return (
    <div className="space-y-6">
      <div className={cn('rounded-lg border px-5 py-4', readiness.task.can_write ? 'border-success/30 bg-success-soft' : 'border-warning/30 bg-warning-soft')}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Badge tone={readiness.task.mode === 'sandbox' ? 'success' : 'warning'}>{readiness.task.mode === 'sandbox' ? 'تغییر فایل ممکن است' : 'فقط خواندن'}</Badge>
            <span className="text-sm font-medium">{readiness.task.can_write ? 'سندباکس و مدل آماده‌اند.' : 'تغییر فایل فعلاً ممکن نیست.'}</span>
          </div>
          <Button variant="outline" size="xs" onClick={refreshAll} disabled={busy}>
            <ArrowsClockwiseIcon className={cn(busy && 'animate-spin')} /> تازه‌سازی
          </Button>
        </div>
        <p className="text-muted-foreground mt-2 text-xs leading-6">{taskReasonText(readiness)}</p>
        {!readiness.task.can_write && (
          <p className="text-muted-foreground mt-1 text-xs leading-6">
            گفتگو ممکن است ({readiness.task.can_chat ? 'بله' : 'خیر'})، اما هیچ فایلی تغییر نمی‌کند.
          </p>
        )}
      </div>

      <div>
        <BlockLabel>اجزای لازم</BlockLabel>
        <RowGroup>
          <Row
            leading={<CpuIcon className="text-muted-foreground size-5" />}
            label="موتور و پایگاه‌دادهٔ داخلی"
            description={
              <div className="space-y-1">
                <State ok={readiness.engine.ok} label={readiness.engine.ok ? `موتور آماده (Python ${readiness.engine.python})` : 'موتور پاسخ نمی‌دهد'} />
                <State
                  ok={readiness.schema.ok}
                  label={readiness.schema.ok ? `پایگاه‌دادهٔ داخلی نسخهٔ ${readiness.schema.expected}` : `پایگاه‌داده نسخهٔ ${readiness.schema.version ?? '?'} از ${readiness.schema.expected} است`}
                />
              </div>
            }
          />
          <Row
            leading={<StackIcon className="text-muted-foreground size-5" />}
            label="مدل"
            description={
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm">{model.configured ? model.name : 'مدلی انتخاب نشده'}</span>
                  {model.configured && <Badge tone={modelCapability.tone}>{modelCapability.label}</Badge>}
                </div>
                <p className="text-muted-foreground text-xs leading-5">{modelCapability.detail}</p>
                <div className="flex flex-wrap gap-2">
                  {model.configured && !model.demo && model.has_key && (
                    <Button size="xs" variant="outline" onClick={probeDefault} disabled={probing}>
                      <ArrowsClockwiseIcon className={cn(probing && 'animate-spin')} /> بررسی توانایی ابزار
                    </Button>
                  )}
                  <Button size="xs" variant="ghost" onClick={() => setSetupOpen(true)}>
                    تغییر مدل
                  </Button>
                </div>
              </div>
            }
          />
          <Row
            leading={<CubeIcon className="text-muted-foreground size-5" />}
            label="سندباکس Docker"
            description={<RuntimeCard readiness={readiness} onChanged={refreshAll} />}
          />
          <Row
            leading={<FolderSimpleIcon className="text-muted-foreground size-5" />}
            label="فضای کاری"
            description={
              <div className="space-y-2">
                <State ok={readiness.workspace.open} label={readiness.workspace.open ? readiness.workspace.name ?? 'باز است' : 'هیچ پوشه‌ای باز نیست'} />
                {!readiness.workspace.open && (
                  <Button size="xs" variant="outline" onClick={() => setSetupOpen(true)}>
                    <FolderSimpleIcon /> انتخاب پوشه
                  </Button>
                )}
              </div>
            }
          />
        </RowGroup>
      </div>

      {readiness.issues.length > 0 && (
        <div>
          <BlockLabel>کارهایی که باید انجام شود</BlockLabel>
          <div className="space-y-2">
            {readiness.issues.map((issue) => (
              <div key={issue.code} className="bg-popover flex items-start gap-2.5 rounded-xl border px-4 py-3">
                <WarningIcon className="text-warning mt-0.5 size-4 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{issueText[issue.code] ?? issue.message}</div>
                  <div className="text-muted-foreground mt-0.5 text-xs leading-5">
                    بخش: {issue.component} · {issue.retryable ? 'با تازه‌سازی ممکن است حل شود' : 'نیازمند تغییر تنظیمات'} · <span dir="ltr" className="font-mono">{issue.code}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-popover rounded-xl border px-4 py-3">
        <div className="flex items-start gap-2.5">
          <InfoIcon className="text-muted-foreground mt-0.5 size-4 shrink-0" />
          <p className="text-muted-foreground text-xs leading-6">
            برای تغییر کد، مدلِ بررسی‌شده و محیط Docker باید آماده باشند. برنامهٔ هر تسک را پیش از اجرا تأیید می‌کنی و تغییرات را در پایان بازبینی و اعمال می‌کنی.
          </p>
        </div>
      </div>

      <div className="text-muted-foreground flex items-center gap-2 text-xs">
        <PlugsConnectedIcon className="size-4" />
        وضعیت worker: {readiness.worker.state === 'busy' ? 'در حال کار' : readiness.worker.state === 'idle' ? 'آزاد' : 'نامشخص'}
      </div>
    </div>
  );
}

/** Four checkboxes; a checked box is a record of reading, not a permission grant. */
export function DisclosureChecklist({ values, onChange, disabled = false }: { values: Partial<Record<DisclosureKey, boolean>>; onChange: (key: DisclosureKey, value: boolean) => void; disabled?: boolean }) {
  return (
    <div className="space-y-2.5">
      {DISCLOSURE_KEYS.map((key) => (
        <label key={key} className={cn('flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3', values[key] ? 'border-primary/30 bg-primary-soft/25' : 'bg-popover')}>
          <input
            type="checkbox"
            className="accent-primary mt-1 size-4 shrink-0"
            checked={Boolean(values[key])}
            disabled={disabled}
            onChange={(event) => onChange(key, event.target.checked)}
          />
          <span className="min-w-0">
            <span className="block text-sm font-medium">{disclosureText[key].title}</span>
            <span className="text-muted-foreground mt-0.5 block text-xs leading-6">{disclosureText[key].body}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

/** Readiness-tab disclosures: stored server-side and shown again after reload. */
export function DisclosureSettings() {
  const settings = useBackend((s) => s.settings);
  const refreshSettings = useBackend((s) => s.refreshSettings);
  const [values, setValues] = useState<Partial<Record<DisclosureKey, boolean>>>(settings?.disclosures ?? {});
  const [saving, setSaving] = useState(false);

  useEffect(() => setValues(settings?.disclosures ?? {}), [settings?.disclosures]);

  const save = async () => {
    setSaving(true);
    try {
      await api.put<Settings>('/settings', { disclosures: values });
      await refreshSettings();
      toast.success('یادداشت آگاهی‌ها ذخیره شد.');
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'ذخیره ممکن نشد.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <BlockLabel
        action={
          <Button size="xs" variant="outline" onClick={save} disabled={saving}>
            ذخیرهٔ یادداشت
          </Button>
        }
      >
        چه چیزی از این سیستم بیرون می‌رود
      </BlockLabel>
      <DisclosureChecklist values={values} onChange={(key, value) => setValues((prev) => ({ ...prev, [key]: value }))} disabled={saving} />
      <p className="text-muted-foreground mt-2 text-xs leading-6">
        این تیک‌ها فقط نشان می‌دهند چه چیزی به شما نشان داده شده است؛ هیچ‌کدام مجوز اجرا یا دسترسی تازه نمی‌سازد.
      </p>
    </div>
  );
}

/** Used by the wizard for the same model summary without duplicating the capability rules. */
export function ModelCapabilitySummary({ model }: { model: { name: string; demo: boolean; has_key: boolean; tools: boolean | null; error_code?: string | null } }) {
  const view = capabilityOf({
    base_url: model.demo ? 'demo://' : 'https://configured.invalid',
    has_key: model.has_key,
    capabilities: { tools: model.tools, error_code: model.error_code ?? null },
  });
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span className="text-sm">{model.name}</span>
      <Badge tone={view.tone}>{view.label}</Badge>
    </span>
  );
}
