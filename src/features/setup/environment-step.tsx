'use client';

import { ArrowsClockwiseIcon, CheckCircleIcon, FileTextIcon, InfoIcon, WarningIcon } from '@phosphor-icons/react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Badge, PathText } from '@/components/ui/primitives';
import { api, ApiError, type Preflight, type Readiness, type WorkspaceDetail, type WorkspaceProfile } from '@/lib/api';
import { initialCommandSelection } from '@/lib/harness/setup-flow';
import { RuntimeCard } from '@/features/settings/readiness-panel';
import { cn } from '@/lib/utils';

const conflictText: Record<string, string> = {
  lockfile_conflict: 'بیش از یک lockfile برای یک زبان وجود دارد؛ مدیر بسته روشن نیست.',
  package_manager_conflict: 'package.json یک مدیر بسته اعلام می‌کند اما lockfile از مدیر دیگری است.',
  package_json_invalid: 'package.json خوانده نشد.',
  pyproject_invalid: 'pyproject.toml خوانده نشد.',
};

const kindLabel: Record<Preflight['detected']['kind'], string> = {
  node: 'پروژهٔ Node',
  python: 'پروژهٔ Python',
  mixed: 'پروژهٔ Node و Python',
  generic: 'پوشهٔ عمومی',
};

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} بایت`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} کیلوبایت`;
  return `${(bytes / 1024 / 1024).toFixed(1)} مگابایت`;
}

/**
 * Step 3: inspect the project without running anything, then optionally save
 * the suggested verification profile. Saving is a record, not a first run.
 */
export function EnvironmentStep({
  workspaceId,
  savedProfile,
  readiness,
  refreshAll,
  onError,
}: {
  workspaceId: string;
  savedProfile: WorkspaceProfile | null;
  readiness: Readiness | null;
  refreshAll: () => Promise<unknown>;
  onError: (message: string | null) => void;
}) {
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [install, setInstall] = useState('');
  const [saved, setSaved] = useState(false);
  // The parent may pass a fresh inline function each render; keeping it in a ref
  // stops that from retriggering the preflight.
  const report = useRef(onError);
  report.current = onError;

  const load = useCallback(async () => {
    setLoading(true);
    report.current(null);
    try {
      const data = await api.post<Preflight>(`/workspaces/${workspaceId}/preflight`);
      setPreflight(data);
      setWorkspace(data.workspace ?? null);
      const suggested = data.profile.commands.map((command) => command.command);
      const previous = savedProfile?.commands.map((command) => command.command) ?? null;
      setSelected(initialCommandSelection(suggested, previous));
      setInstall(savedProfile?.install?.command ?? '');
      setSaved(false);
    } catch (error) {
      report.current(error instanceof ApiError ? error.message : 'بررسی پروژه ممکن نشد.');
    } finally {
      setLoading(false);
    }
  }, [workspaceId, savedProfile]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (command: string) => {
    setSaved(false);
    setSelected((current) => (current.includes(command) ? current.filter((item) => item !== command) : [...current, command]));
  };

  const saveProfile = async () => {
    if (!preflight) return;
    const commands = preflight.profile.commands.filter((command) => selected.includes(command.command));
    const chosenInstall = preflight.profile.installs.find((item) => item.command === install) ?? null;
    setSaving(true);
    report.current(null);
    try {
      await api.patch(`/workspaces/${workspaceId}`, { profile: { commands, install: chosenInstall } });
      await refreshAll();
      setSaved(true);
      toast.success('پیشنهاد ذخیره شد؛ هیچ فرمانی اجرا نشد و راه‌اندازی کامل نشد.');
    } catch (error) {
      report.current(error instanceof ApiError ? error.message : 'ذخیرهٔ پیشنهاد ممکن نشد.');
    } finally {
      setSaving(false);
    }
  };

  if (loading && !preflight) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 py-10 text-sm">
        <ArrowsClockwiseIcon className="size-4 animate-spin" /> در حال خواندن پروژه (فقط خواندن)…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="bg-primary-soft/40 border-primary/20 flex items-start gap-2.5 rounded-xl border px-4 py-3">
        <InfoIcon className="text-primary mt-0.5 size-4 shrink-0" />
        <p className="text-xs leading-6">
          این بررسی فقط <span className="font-semibold">می‌خواند</span>: package.json، pyproject.toml و lockfileها. هیچ فرمانی، نصب یا دانلودی انجام نمی‌شود و هیچ فایلی در پروژه نوشته نمی‌شود.
        </p>
      </div>

      {preflight && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="primary">{kindLabel[preflight.detected.kind]}</Badge>
              <span className="text-muted-foreground text-xs">
                {preflight.scan.file_count.toLocaleString('fa-IR')} فایل · {size(preflight.scan.bytes)}
              </span>
              {preflight.scan.secret_files > 0 && <Badge tone="warning">{preflight.scan.secret_files} فایل حساس کنار گذاشته می‌شود</Badge>}
              {preflight.scan.symlinks > 0 && <Badge tone="warning">{preflight.scan.symlinks} پیوند نمادین نادیده گرفته می‌شود</Badge>}
              {preflight.scan.truncated && <Badge tone="danger">شمارش به سقف رسید</Badge>}
            </div>
            <Button variant="outline" size="xs" onClick={() => void load()} disabled={loading}>
              <ArrowsClockwiseIcon className={cn(loading && 'animate-spin')} /> بررسی دوباره
            </Button>
          </div>

          {workspace && <PathText path={workspace.root} className="text-muted-foreground text-xs" />}

          {preflight.conflicts.length > 0 && (
            <div className="space-y-2">
              {preflight.conflicts.map((conflict) => (
                <div key={conflict.code} className="border-danger/30 bg-danger-soft/30 rounded-xl border px-4 py-3">
                  <div className="flex items-start gap-2.5">
                    <WarningIcon className="text-danger mt-0.5 size-4 shrink-0" />
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{conflictText[conflict.code] ?? conflict.message}</div>
                      <div className="text-muted-foreground mt-1 text-xs leading-5">
                        {conflict.files.join('، ')} · <span dir="ltr" className="font-mono">{conflict.code}</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
              <p className="text-muted-foreground text-xs leading-6">تا وقتی این تعارض برطرف نشود، هیچ فرمان یا نصبی پیشنهاد نمی‌شود.</p>
            </div>
          )}

          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <div className="text-sm font-semibold">فرمان‌های پیشنهادی</div>
              <span className="text-muted-foreground text-xs">{selected.length} از {preflight.profile.commands.length} انتخاب شده</span>
            </div>
            {preflight.profile.commands.length === 0 ? (
              <div className="text-muted-foreground bg-popover rounded-xl border px-4 py-5 text-sm leading-6">
                فرمان آزمون، لینت، بررسی نوع یا ساختی پیدا نشد. هیچ فرمانی حدس زده نمی‌شود؛ اگر فرمان درست را می‌دانید، بعداً از تنظیمات فضای کاری اضافه کنید.
              </div>
            ) : (
              <div className="bg-popover divide-border divide-y overflow-hidden rounded-xl border">
                {preflight.profile.commands.map((command) => (
                  <label key={command.command} className="hover:bg-hover flex cursor-pointer items-start gap-3 px-4 py-3">
                    <input
                      type="checkbox"
                      className="accent-primary mt-1 size-4 shrink-0"
                      checked={selected.includes(command.command)}
                      onChange={() => toggle(command.command)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">{command.label}</span>
                        {command.required && <Badge tone="outline">پیشنهاد ضروری</Badge>}
                      </span>
                      <span dir="ltr" className="text-muted-foreground mt-0.5 block truncate font-mono text-xs">{command.command}</span>
                      <span className="text-muted-foreground mt-0.5 block text-[0.6875rem]">
                        از <span dir="ltr" className="font-mono">{command.source}</span> · مهلت {command.timeout} ثانیه
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            )}
          </div>

          {preflight.profile.installs.length > 0 && (
            <div>
              <div className="mb-2 flex items-center gap-2">
                <div className="text-sm font-semibold">نصب پیشنهادی</div>
                <Badge tone="warning">نیازمند اجازهٔ جدا</Badge>
              </div>
              <div className="bg-popover divide-border divide-y overflow-hidden rounded-xl border">
                {preflight.profile.installs.map((item) => (
                  <label key={item.command} className="hover:bg-hover flex cursor-pointer items-start gap-3 px-4 py-3">
                    <input
                      type="checkbox"
                      className="accent-primary mt-1 size-4 shrink-0"
                      checked={install === item.command}
                      onChange={() => {
                        setSaved(false);
                        setInstall((current) => (current === item.command ? '' : item.command));
                      }}
                    />
                    <span className="min-w-0">
                      <span dir="ltr" className="block font-mono text-xs">{item.command}</span>
                      <span className="text-muted-foreground mt-0.5 block text-[0.6875rem]">
                        از <span dir="ltr" className="font-mono">{item.source}</span> · ذخیرهٔ آن به معنی اجازهٔ اجرا در آینده نیست
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {preflight.profile.notes.length > 0 && (
            <ul className="text-muted-foreground space-y-1 text-xs leading-6">
              {preflight.profile.notes.map((note) => (
                <li key={note} className="flex gap-2">
                  <InfoIcon className="mt-1 size-3.5 shrink-0" /> {note}
                </li>
              ))}
            </ul>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" disabled={saving || (selected.length === 0 && !install)} onClick={saveProfile}>
              {saving ? 'در حال ذخیره…' : 'ذخیرهٔ پیشنهاد'}
            </Button>
            {saved && (
              <span className="text-success flex items-center gap-1.5 text-xs">
                <CheckCircleIcon className="size-4" /> ذخیره شد؛ هنوز هیچ فرمانی اجرا نشده است.
              </span>
            )}
          </div>
          <p className="text-muted-foreground text-xs leading-6">
            ذخیرهٔ این پیشنهاد اجرای نخست را تأیید نمی‌کند. اولین اجرای راستی‌آزمایی یک اقدام جدا و با اجازهٔ خودتان است.
          </p>
        </>
      )}

      <div className="border-t pt-5">
        <div className="mb-2 flex items-center gap-2">
          <FileTextIcon className="text-muted-foreground size-4" />
          <div className="text-sm font-semibold">ابزار اجرای داخلی</div>
        </div>
        <RuntimeCard readiness={readiness} onChanged={refreshAll} />
      </div>
    </div>
  );
}
