'use client';

import {
  BellIcon,
  CaretDownIcon,
  CaretUpDownIcon,
  CheckIcon,
  FolderOpenIcon,
  FolderSimpleIcon,
  GearSixIcon,
  PlusIcon,
  SidebarSimpleIcon,
} from '@phosphor-icons/react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { BridgeSymbol } from '@/components/shared/brand';
import { useTaskList } from '@/features/tasks/use-task-list';
import { isActiveTaskState, taskStateTone } from '@/features/tasks/status';
import { Button } from '@/components/ui/button';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Dialog, DialogContent, Popover, PopoverContent, PopoverTrigger } from '@/components/ui/overlays';
import { navRow } from '@/components/ui/patterns';
import { Dot, Hint, Kbd, PathText } from '@/components/ui/primitives';
import { ApiError } from '@/lib/api';
import { useBackend } from '@/lib/backend';
import type { HarnessTaskSummary } from '@/lib/harness/client';
import { useUi } from '@/lib/store';
import { cn } from '@/lib/utils';
import { navItems } from './nav';

const railRow = 'justify-center px-0';

const runTone: Record<string, string> = { running: 'primary', waiting: 'warning', finished: 'neutral' };

export function LogoMark({ className }: { className?: string }) {
  return <BridgeSymbol size={26} className={className} />;
}

/** The open workspace and the other folders this machine has used. A workspace is
 *  its folder, like a repository: switching means opening another folder. */
function WorkspaceSwitcher({ open }: { open: boolean }) {
  const workspace = useBackend((s) => s.workspace);
  const openWorkspace = useBackend((s) => s.openWorkspace);
  const router = useRouter();
  const drafts = useUi(s => s.drafts);
  const setDraft = useUi(s => s.setDraft);
  const [pendingPath, setPendingPath] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const sourcePath = workspace?.path ?? '';

  const completeSwitch = async (path: string, transfer: boolean) => {
    setSwitching(true);
    const sourceText = drafts[sourcePath] ?? '';
    try {
      await openWorkspace(path);
      if (transfer) {
        const destination = useBackend.getState().workspace?.path ?? path;
        const destinationText = useUi.getState().drafts[destination] ?? '';
        setDraft(destination, [destinationText, sourceText].filter(Boolean).join('\n\n'));
        setDraft(sourcePath, '');
      }
      setPendingPath(null);
      router.push('/');
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'باز کردن فضای کاری ممکن نشد.');
    } finally { setSwitching(false); }
  };

  const switchTo = async (path: string) => {
    if (path === sourcePath) return;
    if ((drafts[sourcePath] ?? '').trim()) { setPendingPath(path); return; }
    await completeSwitch(path, false);
  };
  const pickNew = async () => {
    const folder = await window.desktop?.pickFolder?.();
    if (folder) await switchTo(folder);
    else if (!window.desktop?.pickFolder) toast('انتخاب پوشه فقط در برنامهٔ دسکتاپ ممکن است.');
  };

  return (
    <>
    <Menu>
      <MenuTrigger
        className={cn(
          'hover:bg-hover data-[state=open]:bg-hover border-border flex h-9 min-w-0 items-center gap-2 rounded-lg border border-transparent text-start outline-none',
          open ? 'flex-1 px-2' : 'w-9 justify-center',
        )}
        aria-label="فضای کاری"
      >
        <FolderSimpleIcon className="text-muted-foreground size-4 shrink-0" />
        {open && (
          <>
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{workspace?.name || 'انتخاب پروژه'}</span>
            <CaretUpDownIcon className="text-faint size-4 shrink-0" />
          </>
        )}
      </MenuTrigger>
      <MenuContent align="start" className="w-72">
        <MenuLabel>فضاهای کاری این سیستم</MenuLabel>
        {(workspace?.known ?? []).map((known) => (
          <MenuItem key={known.path} className="h-auto py-1.5" onSelect={() => known.path !== workspace?.path && switchTo(known.path)}>
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block truncate">{known.name}</span>
              <PathText path={known.path} className="text-faint text-[11px]" />
            </span>
            {known.path === workspace?.path && <CheckIcon className="text-primary!" />}
          </MenuItem>
        ))}
        <MenuSeparator />
        <MenuItem onSelect={pickNew}>
          <FolderOpenIcon />
          باز کردن پوشه‌ای دیگر
        </MenuItem>
      </MenuContent>
    </Menu>
    <Dialog open={pendingPath !== null} onOpenChange={open => { if(!open && !switching) setPendingPath(null); }}>
      <DialogContent title="پیش‌نویس این پروژه را چه کنیم؟" description="فقط متن قابل انتقال است؛ فایل‌های مرجع به پروژهٔ بعدی منتقل نمی‌شوند.">
        <p className="text-muted-foreground text-sm">انتقال، متن را به پیش‌نویس مقصد اضافه می‌کند؛ پیش‌نویس قبلی مقصد حذف نمی‌شود.</p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Button disabled={switching} onClick={() => pendingPath && void completeSwitch(pendingPath,true)}>انتقال متن</Button>
          <Button disabled={switching} variant="outline" onClick={() => pendingPath && void completeSwitch(pendingPath,false)}>نگه‌داشتن در پروژهٔ فعلی</Button>
          <Button disabled={switching} variant="muted" onClick={() => setPendingPath(null)}>انصراف</Button>
        </div>
      </DialogContent>
    </Dialog>
    </>
  );
}

/** The bell lists what is waiting for the user right now: paused actions, across all tasks. */
function Notifications({waiting}:{waiting:HarnessTaskSummary[]}) {
  const router = useRouter();
  return (
    <Popover>
      <Hint label="منتظر شما" side="bottom">
        <PopoverTrigger asChild>
          <Button variant="muted" size="icon-sm" aria-label="اعلان‌ها" className="relative">
            <BellIcon />
            {waiting.length > 0 && <span className="bg-primary ring-sidebar absolute end-1.5 top-1.5 size-2 rounded-full ring-2" />}
          </Button>
        </PopoverTrigger>
      </Hint>
      <PopoverContent align="end" side="bottom" className="w-92 p-0">
        <div className="border-b px-4 py-3 text-sm font-semibold">منتظر تأیید شما</div>
        {waiting.length === 0 ? (
          <p className="text-muted-foreground px-4 py-6 text-center text-sm">چیزی منتظر شما نیست.</p>
        ) : (
          <ul className="divide-border divide-y">
            {waiting.map((run) => (
              <li key={run.id}>
                <button className="hover:bg-hover flex w-full gap-3 px-4 py-3 text-start" onClick={() => router.push(`/tasks?task=${encodeURIComponent(run.id)}`)}>
                  <Dot tone="warning" className="mt-2.5 size-2" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{run.title || 'کار بدون عنوان'}</span>
                    <span className="text-muted-foreground block truncate text-xs">برای بازبینی درخواست‌ها باز کنید.</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}

/** Expanded: navigation and recent tasks. Collapsed: an icon rail, so the way back is always visible. */
export function AppSidebar({ open, canExpand = true }: { open: boolean; canExpand?: boolean }) {
  const pathname = usePathname();
  const router = useRouter();
  const toggleSidebar = useUi((s) => s.toggleSidebar);
  const setActiveThread = useUi((s) => s.setActiveThread);
  const activeThread = useUi((s) => s.activeThread);
  const status = useBackend((s) => s.status);
  const [recentOpen, setRecentOpen] = useState(true);
  const tasks = useTaskList({ limit: 12 });
  const waiting = useTaskList({limit:200,status:'awaiting_action'});
  const waitingCount = waiting.items.length;
  const settingsActive = pathname.startsWith('/settings');

  return (
    <aside
      className={cn(
        'bg-sidebar border-border flex shrink-0 flex-col border-e pb-3 transition-[width] duration-200 ease-[cubic-bezier(0.2,0,0,1)]',
        open ? 'w-[264px] px-3' : 'w-16 px-2',
      )}
    >
      <div className="flex h-12 shrink-0 items-center gap-2 px-1">
        <Link href="/" className="flex min-w-0 items-center gap-2 outline-none" aria-label="خانه">
          <LogoMark />
          {open && <span className="truncate text-sm font-semibold">Bridge Coding</span>}
        </Link>
        {open && (
          <Hint side="left" label={<>بستن منو <Kbd className="bg-background/20 text-background ltr-nums">Ctrl B</Kbd></>}>
            <Button variant="muted" size="icon-sm" aria-label="بستن منو" className="ms-auto" onClick={toggleSidebar}>
              <SidebarSimpleIcon className="-scale-x-100" />
            </Button>
          </Hint>
        )}
      </div>

      <div className={cn('mt-2 flex items-center gap-1', !open && 'flex-col')}>
        <WorkspaceSwitcher open={open} />
        <Notifications waiting={waiting.items}/>
        {!open && canExpand && (
          <Hint side="left" label={<>بازکردن منو <Kbd className="bg-background/20 text-background ltr-nums">Ctrl B</Kbd></>}>
            <Button variant="muted" size="icon-sm" aria-label="بازکردن منو" onClick={toggleSidebar}>
              <SidebarSimpleIcon className="-scale-x-100" />
            </Button>
          </Hint>
        )}
      </div>

      <Link href="/" className={cn(navRow, 'mt-3 shrink-0', !open && railRow)} onClick={() => setActiveThread(null)} aria-label="کار جدید">
        <PlusIcon />
        {open && (
          <>
            <span className="flex-1">کار جدید</span>
            <Kbd className="ltr-nums opacity-0 group-hover/row:opacity-100">Ctrl J</Kbd>
          </>
        )}
      </Link>

      <nav className="scrollbar-none mt-1 min-h-0 flex-1 overflow-y-auto">
        <ul className="flex flex-col gap-0.5">
          {navItems.map((item) => {
            const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
            const badge = item.href === '/approvals' ? waitingCount : 0;
            const link = (
              <Link href={item.href} className={cn(navRow, !open && railRow)} data-active={active} aria-label={item.label}>
                <item.icon weight={active ? 'fill' : 'bold'} />
                {open && <span className="flex-1 truncate">{item.label}</span>}
                {badge > 0 &&
                  (open ? (
                    <span className="bg-primary text-primary-foreground flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 text-[11px] font-medium">
                      {badge.toLocaleString('fa-IR')}
                    </span>
                  ) : (
                    <span className="bg-primary ring-sidebar absolute end-2 top-1.5 size-2 rounded-full ring-2" />
                  ))}
              </Link>
            );
            return <li key={item.href}>{open ? link : <Hint label={item.label} side="left">{link}</Hint>}</li>;
          })}
        </ul>

        {open && tasks.items.length > 0 && (
          <div className="mt-5">
            <button
              onClick={() => setRecentOpen((v) => !v)}
              aria-expanded={recentOpen}
              className="text-faint hover:text-foreground flex h-8 w-full items-center gap-1 px-3 text-xs font-medium"
            >
              کارهای اخیر
              <CaretDownIcon className={cn('size-3 transition-transform', !recentOpen && 'rotate-90')} />
            </button>
            <ul className={cn('flex flex-col gap-0.5', !recentOpen && 'hidden')}>
              {tasks.items.map((run) => (
                <li key={run.id} className="group/task relative">
                  <button
                    className={cn(navRow, 'pe-9 font-normal')}
                    data-active={pathname.startsWith('/tasks') && activeThread === run.id}
                    onClick={() => {
                      setActiveThread(run.id);
                      router.push(`/tasks?task=${encodeURIComponent(run.id)}`);
                    }}
                  >
                    <Dot tone={taskStateTone[run.status]} pulse={isActiveTaskState(run.status)} className="mx-1.5 size-2" />
                    <span className="flex-1 truncate text-start">{run.title || 'کار بدون عنوان'}</span>
                  </button>

                </li>
              ))}
            </ul>
          </div>
        )}
      </nav>

      <div className={cn('text-faint mt-2 flex items-center gap-2 px-2 py-1.5 text-xs', !open && 'justify-center px-0')}>
        <Dot tone={status === 'ready' ? 'success' : status === 'connecting' ? 'warning' : 'danger'} pulse={status === 'connecting'} />
        {open && <span>{status === 'ready' ? 'موتور آماده' : status === 'connecting' ? 'در حال اتصال' : 'موتور در دسترس نیست'}</span>}
      </div>

      <Link href="/settings" className={cn(navRow, 'shrink-0', !open && railRow)} data-active={settingsActive} aria-label="تنظیمات">
        <GearSixIcon weight={settingsActive ? 'fill' : 'bold'} />
        {open && <span className="flex-1">تنظیمات</span>}
      </Link>
    </aside>
  );
}
