'use client';

import {
  ArrowSquareOutIcon,
  ArrowsClockwiseIcon,
  CpuIcon,
  FolderSimpleIcon,
  GlobeIcon,
  PencilSimpleIcon,
  PlugsConnectedIcon,
  PlusIcon,
  ShieldCheckIcon,
  StarIcon,
  TrashIcon,
  type Icon,
} from '@phosphor-icons/react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/features/shell/page';
import { Button } from '@/components/ui/button';
import { BlockLabel, EmptyNote, navRow, Row, RowGroup, subNav, Table, TBody, Td, Th, THead, Tr } from '@/components/ui/patterns';
import { Badge, Hint, Input, PathText } from '@/components/ui/primitives';
import { api, ApiError, type Model } from '@/lib/api';
import { openOutside, useBackend } from '@/lib/backend';
import { useUi, type SettingsTab } from '@/lib/store';
import { cn } from '@/lib/utils';
import { CapabilityBadge } from '@/features/settings/capability';
import { ModelDialog } from '@/features/settings/model-dialog';
import { DisclosureSettings, ReadinessPanel } from '@/features/settings/readiness-panel';
import { DataPanel } from '@/features/settings/data-panel';

const tabs: { id: SettingsTab; label: string; icon: Icon }[] = [
  { id: 'general', label: 'عمومی', icon: GlobeIcon },
  { id: 'models', label: 'مدل‌ها', icon: CpuIcon },
  { id: 'readiness', label: 'آمادگی', icon: ShieldCheckIcon },
  { id: 'workspace', label: 'فضای کاری', icon: FolderSimpleIcon },
  { id: 'data', label: 'داده‌ها و عیب‌یابی', icon: FolderSimpleIcon },
];

function General() {
  const setIntroOpen = useUi((s) => s.setIntroOpen);
  const setSetupOpen = useUi((s) => s.setSetupOpen);
  const setup = useBackend((s) => s.settings?.setup ?? null);
  return (
    <>
      <BlockLabel>راهنما</BlockLabel>
      <RowGroup>
        <Row label="راهنمای شروع" description="هارنس کدنویسی Bridge چیست و چطور پروژه و مدل را وصل کنیم">
          <Button variant="outline" size="xs" onClick={() => setIntroOpen(true)}>
            دوباره ببین
          </Button>
        </Row>
      </RowGroup>
      <BlockLabel className="mt-6">راه‌اندازی</BlockLabel>
      <RowGroup>
        <Row
          label="بازبینی راه‌اندازی"
          description={
            setup?.completed
              ? `راه‌اندازی در ${setup.completed_at ? new Date(setup.completed_at * 1000).toLocaleDateString('fa-IR') : 'قبل'} تمام شد؛ می‌توانید پوشه، مدل و آگاهی‌ها را دوباره ببینید.`
              : 'راه‌اندازی هنوز تمام نشده است: پوشه، مدل و آگاهی‌ها.'
          }
        >
          <Button variant="outline" size="xs" onClick={() => setSetupOpen(true)}>
            <ShieldCheckIcon /> {setup?.completed ? 'بازبینی' : 'ادامه'}
          </Button>
        </Row>
      </RowGroup>
      <p className="text-muted-foreground mt-3 text-xs leading-6">
        بازبینی، هیچ مجوز اجرا یا دسترسی تازه‌ای نمی‌سازد؛ فقط گام‌های همان راه‌اندازی را دوباره نشان می‌دهد.
      </p>
    </>
  );
}

function Models() {
  const models = useBackend((s) => s.models);
  const refresh = useBackend((s) => s.refreshModels);
  const refreshReadiness = useBackend((s) => s.refreshReadiness);
  // `key` remounts the dialog so its form starts from the model being edited.
  const [dialog, setDialog] = useState<{ open: boolean; editing: Model | null; key: number }>({ open: false, editing: null, key: 0 });
  const [probing, setProbing] = useState<string | null>(null);
  const openDialog = (editing: Model | null) => setDialog((d) => ({ open: true, editing, key: d.key + 1 }));
  const act = (action: Promise<unknown>) => action.then(refresh).catch((e) => toast.error(e instanceof ApiError ? e.message : 'انجام نشد.'));

  // Unlike the dialog's probe, this one stores its result: it is evidence for a
  // model the user kept, and readiness uses it to permit writes.
  const probe = async (model: Model) => {
    setProbing(model.id);
    try {
      await api.post('/models/probe', { id: model.id });
      await Promise.all([refresh(), refreshReadiness().catch(() => null)]);
      toast.success('نتیجهٔ بررسی ذخیره شد.');
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'بررسی مدل ممکن نشد.');
    } finally {
      setProbing(null);
    }
  };

  return (
    <>
      <BlockLabel
        action={
          <Button size="xs" onClick={() => openDialog(null)}>
            <PlusIcon /> تعریف مدل
          </Button>
        }
      >
        مدل هر کار را در کادر پیام انتخاب می‌کنید
      </BlockLabel>
      {models.length === 0 ? (
        <EmptyNote icon={<PlugsConnectedIcon />} title="هنوز مدلی تعریف نشده">آدرس سرویس، کلید و نام مدل خودتان را وارد کنید.</EmptyNote>
      ) : (
        <Table>
          <THead>
            <Th>نام</Th>
            <Th>Model Name</Th>
            <Th>Base URL</Th>
            <Th>کلید</Th>
            <Th>توانایی ابزار</Th>
            <Th className="w-px" />
          </THead>
          <TBody>
            {models.map((model) => (
              <Tr key={model.id}>
                <Td className="font-medium whitespace-nowrap">
                  <span className="flex items-center gap-2">
                    {model.name}
                    {model.is_default && <Badge tone="primary">پیش‌فرض</Badge>}
                  </span>
                </Td>
                <Td className="whitespace-nowrap">
                  <span className="ltr-nums font-mono text-[0.8125rem]">{model.model}</span>
                </Td>
                <Td className="text-muted-foreground max-w-64">
                  <PathText path={model.base_url} className="text-[0.8125rem]" />
                </Td>
                <Td className="whitespace-nowrap">{model.base_url.startsWith('demo://') ? <span className="text-muted-foreground">لازم نیست</span> : model.has_key ? <Badge tone="success">ذخیره شده</Badge> : <Badge tone="warning">ندارد</Badge>}</Td>
                <Td className="whitespace-nowrap">
                  <CapabilityBadge model={model} />
                </Td>
                <Td>
                  <div className="flex items-center justify-end gap-0.5">
                    {!model.base_url.startsWith('demo://') && model.has_key && (
                      <Hint label="بررسی توانایی ابزار">
                        <Button variant="muted" size="icon-xs" aria-label="بررسی توانایی ابزار" disabled={probing === model.id} onClick={() => void probe(model)}>
                          <ArrowsClockwiseIcon className={cn(probing === model.id && 'animate-spin')} />
                        </Button>
                      </Hint>
                    )}
                    <Hint label={model.is_default ? 'مدل پیش‌فرض' : 'پیش‌فرض کن'}>
                      <Button variant="muted" size="icon-xs" aria-label="پیش‌فرض" onClick={() => act(api.post(`/models/${model.id}/default`))}>
                        <StarIcon weight={model.is_default ? 'fill' : 'bold'} className={cn(model.is_default && 'text-primary')} />
                      </Button>
                    </Hint>
                    <Hint label="ویرایش">
                      <Button variant="muted" size="icon-xs" aria-label="ویرایش" onClick={() => openDialog(model)}>
                        <PencilSimpleIcon />
                      </Button>
                    </Hint>
                    <Hint label="حذف">
                      <Button variant="muted" size="icon-xs" aria-label="حذف" onClick={() => act(api.del(`/models/${model.id}`))}>
                        <TrashIcon />
                      </Button>
                    </Hint>
                  </div>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
      <p className="text-muted-foreground mt-3 text-xs leading-6">
        «بررسی توانایی ابزار» یک فراخوانی آزمایشی به همان سرویس می‌فرستد و هیچ فایلی از پروژه را نمی‌خواند. تا وقتی این بررسی برای مدل انتخابی موفق نشود، کارها فقط می‌خوانند.
      </p>
      <ModelDialog key={dialog.key} editing={dialog.editing} open={dialog.open} onOpenChange={(open) => setDialog((d) => ({ ...d, open }))} onSaved={refresh} />
    </>
  );
}

function ReadinessSection() {
  return (
    <div className="space-y-8">
      <ReadinessPanel />
      <DisclosureSettings />
    </div>
  );
}

function WorkspacePane() {
  const workspace = useBackend((s) => s.workspace);
  const renameWorkspace = useBackend((s) => s.renameWorkspace);
  const refreshReadiness = useBackend((s) => s.refreshReadiness);
  const [name, setName] = useState(workspace?.name ?? '');
  useEffect(() => setName(workspace?.name ?? ''), [workspace?.name]);

  const rename = async () => {
    try {
      await renameWorkspace(name);
      await refreshReadiness().catch(() => null);
      toast.success('نام فضای کاری عوض شد.');
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'تغییر نام ممکن نشد.');
    }
  };

  return (
    <>
      <BlockLabel>فضای کاری باز</BlockLabel>
      <RowGroup>
        <Row label="نام" description="فقط نامی که در برنامه می‌بینید عوض می‌شود، نه نام پوشه">
          <Input className="h-8 w-56" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && name.trim() && rename()} />
          <Button size="xs" disabled={!name.trim() || name.trim() === workspace?.name} onClick={rename}>
            ذخیره
          </Button>
        </Row>
        <Row label="پوشه" description={<PathText path={workspace?.path ?? ''} />}>
          <Button variant="outline" size="xs" onClick={() => openOutside(workspace?.path ?? '', toast)}>
            <ArrowSquareOutIcon /> باز کردن پوشه
          </Button>
        </Row>
      </RowGroup>
      <p className="text-muted-foreground mt-3 text-xs leading-6">
        پوشهٔ یک فضای کاری عوض نمی‌شود. برای کار در پوشه‌ای دیگر، از منوی بالای نوار کناری پوشهٔ دیگری را باز کنید. قوانین و منابع پروژه می‌توانند داخل پوشهٔ <span className="ltr-nums font-mono">.harness</span> همین فضای کاری باشند؛ تاریخچه، checkpoint و نسخه‌های کاری در پوشهٔ دادهٔ محصول نگه‌داری می‌شوند.
      </p>
    </>
  );
}

const panes: Record<SettingsTab, () => React.ReactNode> = { general: General, models: Models, readiness: ReadinessSection, workspace: WorkspacePane, data: DataPanel };

export default function SettingsPage() {
  const tab = useUi((s) => s.settingsTab);
  const setTab = useUi((s) => s.setSettingsTab);
  useEffect(()=>{if(new URLSearchParams(window.location.search).get('tab')==='data')setTab('data')},[setTab]);
  const Pane = panes[tab] ?? General;

  return (
    <>
      <PageHeader title="تنظیمات" />
      <div className="flex min-h-0 flex-1">
        <nav className={subNav}>
          {tabs.map((item) => (
            <button key={item.id} onClick={() => setTab(item.id)} data-active={tab === item.id} className={navRow}>
              <item.icon weight={tab === item.id ? 'fill' : 'bold'} className={cn(tab === item.id && 'text-primary')} />
              {item.label}
            </button>
          ))}
        </nav>
        <div className="scrollbar-minimal min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[880px] px-6 py-6">
            <Pane />
          </div>
        </div>
      </div>
    </>
  );
}
