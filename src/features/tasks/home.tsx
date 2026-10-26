'use client';

import {
  ArrowLeftIcon,
  ChatsCircleIcon,
  CircleNotchIcon,
  CpuIcon,
  EyeIcon,
  FolderSimpleIcon,
  GearSixIcon,
  PlugsConnectedIcon,
  ShieldCheckIcon,
  WarningCircleIcon,
} from '@phosphor-icons/react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';

import { PageBody, PageHeader } from '@/features/shell/page';
import { Button } from '@/components/ui/button';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuTrigger } from '@/components/ui/overlays';
import { EmptyNote, ListRow } from '@/components/ui/patterns';
import { Badge, Dot, PathText, SectionCard, Switch } from '@/components/ui/primitives';
import { HarnessRequestError } from '@/lib/harness/client';
import { useBackend } from '@/lib/backend';
import { createBrowserClient } from '@/lib/harness/browser';
import { useUi } from '@/lib/store';
import { cn, fa } from '@/lib/utils';

import { PromptInput, composerTool } from './prompt-input';
import { isActiveTaskState, taskStateLabel, taskStateTone } from './status';
import { useTaskList } from './use-task-list';

type AccessMode = 'ask' | 'grant' | 'auto';

/** The three permission modes of P02/P06, with the fixed explanation from the design. */
const accessModes: { value: AccessMode; label: string; hint: string }[] = [
  { value: 'ask', label: 'با تأیید', hint: 'هر تغییر فایل و هر فرمان را پیش از اجرا بررسی می‌کنید.' },
  { value: 'grant', label: 'مجوز برای همین کار', hint: 'فقط مجوزهای مشخصی که تأیید می‌کنید تا پایان همین کار می‌مانند.' },
  { value: 'auto', label: 'خودکار در محیط ایزوله', hint: 'پس از تأیید برنامه، ویرایش و فرمان آفلاین خودکار است؛ شبکه و نصب جدا تصمیم می‌گیرند.' },
];

const suggestions = [
  { label: 'رفع خطا', prompt: 'یک خطای واقعی در این پروژه را پیدا و رفع کن؛ رفتار فعلی حفظ شود.' },
  { label: 'ساخت قابلیت', prompt: 'یک قابلیت کوچک و قابل آزمون به این پروژه اضافه کن.' },
  { label: 'بررسی پروژه', prompt: 'ساختار این پروژه را بررسی کن و ریسک‌ها و قدم بعدی را کوتاه بگو.' },
];

function relative(seconds: number | null | undefined): string {
  if (seconds == null || seconds <= 0) return '—';
  const diff = Date.now() / 1000 - seconds;
  if (diff < 90) return 'همین حالا';
  if (diff < 3600) return `${fa(Math.round(diff / 60))} دقیقه پیش`;
  if (diff < 86400) return `${fa(Math.round(diff / 3600))} ساعت پیش`;
  return `${fa(Math.round(diff / 86400))} روز پیش`;
}

function readableError(error: unknown): string {
  if (error instanceof HarnessRequestError) {
    if (error.code === 'runtime_unavailable') return 'محیط ایزوله در دسترس نیست؛ تغییر فایل ممکن نیست. کار را فقط خواندنی شروع کنید یا محیط را در تنظیمات بررسی کنید.';
    if (error.code === 'model_tools_unavailable') return 'این مدل توان اجرای ابزار را تأیید نکرده است؛ کار را فقط خواندنی شروع کنید یا در تنظیمات مدل دیگری انتخاب کنید.';
    if (error.code === 'conflict' && error.details.reason === 'no_workspace') return 'اول یک پروژه باز کنید.';
    if (error.code === 'invalid_request') {
      const reason = error.details.reason;
      if (reason === 'outside_workspace') return 'یکی از فایل‌های مرجع بیرون پروژه است. اول آن را داخل پوشهٔ پروژه کپی کنید.';
      return error.message || 'درخواست پذیرفته نشد.';
    }
    return error.message || 'شروع کار ممکن نشد.';
  }
  if (error instanceof Error && error.message) return error.message;
  return 'شروع کار ممکن نشد.';
}

function ReadinessDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="text-muted-foreground flex items-center gap-1.5 text-[11px]">
      <Dot tone={ok ? 'success' : 'warning'} />
      {label}
    </span>
  );
}

/**
 * P02: turn a goal into a task.
 *
 * The only write here is `POST /tasks`; planning starts on the task page as a
 * separate read-only pass. The model is the configured one, not a per-task
 * pick: the controller reads the configured model, so offering a selector here
 * would promise something the task does not carry.
 */
export function Home() {
  const router = useRouter();
  const workspace = useBackend((s) => s.workspace);
  const models = useBackend((s) => s.models);
  const readiness = useBackend((s) => s.readiness);
  const readinessLoading = useBackend((s) => s.readinessLoading);
  const settings = useBackend((s) => s.settings);
  const openWorkspace = useBackend((s) => s.openWorkspace);
  const setSettingsTab = useUi((s) => s.setSettingsTab);
  const setActiveThread = useUi((s) => s.setActiveThread);
  const draft = useUi((s) => (workspace?.path ? (s.drafts[workspace.path] ?? '') : ''));
  const setDraft = useUi((s) => s.setDraft);
  const taskList = useTaskList({ limit: 5 });

  const client = useMemo(() => createBrowserClient(), []);
  const [access, setAccess] = useState<AccessMode>('auto');
  const [readOnlyChoice, setReadOnly] = useState<boolean | null>(null);
  const [references, setReferences] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const startKey = useRef<{ payload: string; key: string } | null>(null);
  const previousWorkspace = useRef(workspace?.path ?? null);

  const hasModel = models.length > 0;
  const demoOnly = hasModel && models.every((model) => model.base_url.startsWith('demo://'));
  const modelName = readiness?.model.name ?? models.find((model) => model.is_default)?.name ?? models[0]?.name ?? null;
  const canWrite = readiness?.runtime.available === true && readiness?.model.tools === true;
  const readOnly = !canWrite || readOnlyChoice === true;
  const workerBusy = readiness?.worker.state === 'busy';
  const activeTask = taskList.items.find((task) => isActiveTaskState(task.status)) ?? null;
  const busyName = activeTask?.title?.trim() || activeTask?.prompt?.trim().slice(0, 48) || null;

  useEffect(() => {
    setActiveThread(null);
  }, [setActiveThread]);

  // A reference means a path inside one project. Switching folders must not
  // carry it over silently, even when the typed text is transferred.
  useEffect(() => {
    if (previousWorkspace.current === (workspace?.path ?? null)) return;
    previousWorkspace.current = workspace?.path ?? null;
    setReferences([]);
    setError(null);
  }, [workspace?.path]);

  const chooseProject = async () => {
    const folder = await window.desktop?.pickFolder?.();
    if (folder) {
      try {
        await openWorkspace(folder);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : 'باز کردن پروژه ممکن نشد.');
      }
    }
  };

  const start = async () => {
    const prompt = draft.trim();
    if (!prompt || !hasModel || !workspace?.path || readinessLoading) return;
    setError(null);
    setStarting(true);
    try {
      const payload = JSON.stringify([workspace.path, prompt, access, readOnly, references]);
      const key = startKey.current?.payload === payload ? startKey.current.key : `start:${crypto.randomUUID()}`;
      startKey.current = { payload, key };
      const result = await client.startTask({
        prompt,
        mode: access,
        read_only: readOnly,
        ...(references.length > 0 ? { references } : {}),
        idempotency_key: key,
      });
      startKey.current = null;
      setDraft(workspace.path, '');
      setReferences([]);
      setActiveThread(result.task.id);
      void taskList.refresh();
      router.push(`/tasks?task=${encodeURIComponent(result.task.id)}`);
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setStarting(false);
    }
  };

  const mode = accessModes.find((item) => item.value === access) ?? accessModes[0];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="خانه"
        meta={
          <>
            <FolderSimpleIcon className="size-4" />
            <span className="max-w-52 truncate">{workspace?.name}</span>
            {workspace?.path && <PathText path={workspace.path} className="max-w-52" />}
          </>
        }
        actions={
          <Button asChild variant="ghost" size="icon-sm" aria-label="تنظیمات پروژه">
            <Link href="/settings" onClick={() => setSettingsTab('readiness')}>
              <GearSixIcon />
            </Link>
          </Button>
        }
      />

      <PageBody className="pt-10 pb-12">
        <div className="mx-auto flex w-full max-w-[880px] flex-col">
          {!settings?.setup.completed&&(!workspace?.path||!hasModel||demoOnly||!canWrite)&&<div className="bg-panel mb-6 flex flex-wrap items-center gap-3 rounded-lg border p-4 text-sm">
            <span className="flex-1">پروژه و مدل را بعداً هم می‌توانی تنظیم کنی.</span>
            <Button variant="outline" size="sm" onClick={()=>useUi.getState().setSetupOpen(true)}>ادامهٔ راه‌اندازی</Button>
            <Button asChild size="sm"><Link href="/settings" onClick={()=>setSettingsTab('models')}>اتصال مدل</Link></Button>
          </div>}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
              <FolderSimpleIcon className="text-muted-foreground size-4 shrink-0" />
              <span className="truncate">{workspace?.name}</span>
            </span>
            <ReadinessDot
              ok={readiness?.runtime.available === true}
              label={readinessLoading?'در حال بررسی محیط…':readiness?.runtime.available === true ? 'محیط ایزوله آماده است' : 'محیط اجرا آماده نیست'}
            />
            <ReadinessDot
              ok={readiness?.model.configured === true}
              label={modelName ? `مدل: ${modelName}` : 'مدل تنظیم نشده'}
            />
            {workerBusy && <ReadinessDot ok={false} label="worker مشغول است" />}
            {!workspace?.path && (
              <Button size="xs" onClick={() => void chooseProject()}>
                انتخاب پروژه
              </Button>
            )}
            <span className="flex-1" />
            <span className="text-faint hidden text-[11px] sm:inline">پروژه و آمادگی محیط</span>
          </div>

          <span dir="ltr" className="text-primary mt-10 text-center font-mono text-[11px] tracking-[0.18em]">
            LOCAL WORKSPACE
          </span>
          <h1 className="mt-2 text-center text-[28px] leading-10 font-bold">روی چه چیزی کار کنیم؟</h1>
          <p className="text-muted-foreground mt-1 text-center text-sm leading-7">
            تسک یا سؤالت را بنویس؛ قبل از تغییر کد، برنامه را تأیید کن.
          </p>

          <PromptInput
            className="mt-6"
            large
            autoFocus
            value={draft}
            onValueChange={(next) => {
              setDraft(workspace?.path ?? '', next);
              // A failed request kept its idempotency key; editing the goal
              // makes it a different request and needs a fresh key.
              if (startKey.current !== null) startKey.current = null;
            }}
            onSend={start}
            references={references}
            onReferencesChange={setReferences}
            disabled={!hasModel || !workspace?.path}
            sendDisabled={!hasModel || !workspace?.path || !draft.trim() || readinessLoading}
            sendLabel={readinessLoading?'در حال بررسی محیط…':starting ? 'در حال ساخت کار…' : workerBusy ? 'افزودن به صف' : 'شروع کار'}
            placeholder={workspace?.name ? `کاری را در «${workspace.name}» بسپارید…` : 'کاری را در این پروژه بسپارید…'}
            controls={
              <>
                <span className={cn(composerTool, 'cursor-default')} title="مدل از تنظیمات خوانده می‌شود">
                  <CpuIcon />
                  <span className="truncate">{modelName ?? 'بدون مدل'}</span>
                </span>

                <Menu>
                  <MenuTrigger className={composerTool} aria-label="حالت مجوز">
                    <ShieldCheckIcon />
                    <span className="truncate">{mode.label}</span>
                  </MenuTrigger>
                  <MenuContent align="start" side="top" className="w-80">
                    <MenuLabel>چقدر بدون پرسیدن پیش برود؟</MenuLabel>
                    {accessModes.map((item) => (
                      <MenuItem key={item.value} onSelect={() => setAccess(item.value)} className="h-auto py-2">
                        <span className="min-w-0 flex-1 leading-tight">
                          <span className="block">{item.label}</span>
                          <span className="text-muted-foreground block text-[11px]">{item.hint}</span>
                        </span>
                        {access === item.value && <span className="text-primary text-xs font-medium">انتخاب شد</span>}
                      </MenuItem>
                    ))}
                  </MenuContent>
                </Menu>

                <label
                  className={cn(
                    composerTool,
                    'cursor-pointer gap-2',
                    !canWrite && 'cursor-not-allowed opacity-60',
                  )}
                  title={canWrite ? 'با خاموش‌کردن فقط خواندن، تغییر فایل ممکن می‌شود' : 'بدون مدل اثبات‌شده و محیط ایزوله، فقط خواندن ممکن است'}
                >
                  <EyeIcon />
                  فقط خواندن
                  <Switch
                    checked={readOnly}
                    disabled={!canWrite}
                    onCheckedChange={(checked) => setReadOnly(checked)}
                    aria-label="فقط خواندن"
                  />
                </label>

                <Link
                  href="/settings"
                  onClick={() => setSettingsTab('models')}
                  className={cn(composerTool, 'hidden sm:flex')}
                >
                  <GearSixIcon />
                  تنظیمات
                </Link>
              </>
            }
            notice={
              error ? (
                <p role="alert" className="bg-danger-soft text-danger rounded-lg px-3 py-2 text-xs leading-6">
                  {error}
                </p>
              ) : demoOnly ? (
                <p className="bg-primary-soft text-muted-foreground flex flex-wrap items-center gap-2 rounded-lg px-3 py-2 text-xs leading-6">
                  <PlugsConnectedIcon className="text-primary size-4 shrink-0" />
                  <span className="min-w-0 flex-1">
                    مدل نمایشی روشن است: بدون کلید و بدون تماس بیرونی روند کار را نشان می‌دهد. برای کار واقعی مدل خودتان را وصل کنید.
                  </span>
                  <Link href="/settings" onClick={() => setSettingsTab('models')} className="text-primary shrink-0 font-medium hover:underline">
                    تعریف مدل
                  </Link>
                </p>
              ) : undefined
            }
            hint={
              !hasModel ? (
                <span className="flex flex-wrap items-center gap-1.5">
                  <WarningCircleIcon className="text-warning size-3.5" />
                  هنوز مدلی تنظیم نشده است. اول مدل را در تنظیمات تعریف کنید.
                  <Link href="/settings" onClick={() => setSettingsTab('models')} className="text-primary font-medium hover:underline">
                    تنظیم مدل
                  </Link>
                </span>
              ) : readOnly ? (
                'فقط خواندن روشن است: برنامه و فایل‌ها خوانده می‌شوند، ولی چیزی تغییر نمی‌کند.'
              ) : (
                'پس از تأیید برنامه، تغییرها در نسخهٔ کاری انجام می‌شوند؛ ذخیره در پوشهٔ اصلی با انتخاب توست.'
              )
            }
          />

          {!hasModel && (
            <div className="border-warning/40 bg-warning-soft mt-4 flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3">
              <WarningCircleIcon className="text-warning size-5 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold">مدل هنوز تنظیم نشده است</div>
                <p className="text-muted-foreground mt-0.5 text-xs leading-6">
                  برای ساختن کار، یک مدل واقعی یا مدل نمایشی را در تنظیمات فعال کنید.
                </p>
              </div>
              <Button asChild size="sm">
                <Link href="/settings" onClick={() => setSettingsTab('models')}>
                  تنظیم مدل
                </Link>
              </Button>
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-2">
            {suggestions.map((suggestion) => (
              <button
                key={suggestion.label}
                type="button"
                onClick={() => {
                  setDraft(workspace?.path ?? '', suggestion.prompt);
                  if (startKey.current !== null) startKey.current = null;
                }}
                className="bg-panel border-border text-muted-foreground hover:bg-hover hover:text-foreground rounded-lg border px-2.5 py-1 text-xs"
              >
                {suggestion.label}
              </button>
            ))}
          </div>

          <div className="mt-10">
            <SectionCard
              title="کارهای اخیر"
              count={taskList.items.length > 0 ? Math.min(taskList.items.length, 5) : undefined}
              description={workerBusy && busyName ? `کار مشغول: ${busyName}` : undefined}
              flush
              action={
                <Button asChild variant="soft" size="xs">
                  <Link href="/tasks">
                    همهٔ کارها <ArrowLeftIcon />
                  </Link>
                </Button>
              }
            >
              {taskList.loading ? (
                <div className="text-muted-foreground flex items-center justify-center gap-2 px-5 py-8 text-sm">
                  <CircleNotchIcon className="size-4 animate-spin" />
                  در حال خواندن کارها…
                </div>
              ) : taskList.error ? (
                <div className="flex flex-col items-center gap-2 px-5 py-8 text-center">
                  <p className="text-danger text-sm">خواندن کارها ممکن نشد.</p>
                  <Button variant="outline" size="sm" onClick={() => void taskList.refresh()}>
                    تلاش دوباره
                  </Button>
                </div>
              ) : taskList.items.length === 0 ? (
                <EmptyNote icon={<ChatsCircleIcon />} title="هنوز کاری انجام نشده است">
                  اولین کار را از کادر بالا شروع کنید.
                </EmptyNote>
              ) : (
                <div className="p-1.5">
                  {taskList.items.slice(0, 5).map((task) => (
                    <ListRow
                      key={task.id}
                      onClick={() => {
                        setActiveThread(task.id);
                        router.push(`/tasks?task=${encodeURIComponent(task.id)}`);
                      }}
                      icon={<Dot tone={taskStateTone[task.status]} pulse={isActiveTaskState(task.status)} className="mx-1 size-2.5" />}
                      title={<span className="truncate" dir="auto">{task.title?.trim() || task.prompt?.trim() || 'کار بدون عنوان'}</span>}
                      meta={<span>{relative(task.created_at)}</span>}
                      trailing={<Badge tone={taskStateTone[task.status]}>{taskStateLabel[task.status]}</Badge>}
                    />
                  ))}
                </div>
              )}
            </SectionCard>
          </div>
        </div>
      </PageBody>
    </div>
  );
}
