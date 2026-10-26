'use client';

import { CheckCircleIcon, InfoIcon, WarningIcon } from '@phosphor-icons/react';

import { Button } from '@/components/ui/button';
import { Row, RowGroup } from '@/components/ui/patterns';
import { Badge, PathText } from '@/components/ui/primitives';
import type { Readiness, Settings } from '@/lib/api';
import { capabilityOf, DISCLOSURE_KEYS, missingForCompletion, missingLabel, type DisclosureKey } from '@/lib/harness/setup-flow';
import { DisclosureChecklist, taskReasonText } from '@/features/settings/readiness-panel';
import { cn } from '@/lib/utils';

/** Step 4: one last honest summary, then the explicit act of finishing setup. */
export function ReviewStep({
  settings,
  readiness,
  disclosures,
  onChange,
  onFinish,
  busy,
}: {
  settings: Settings;
  readiness: Readiness | null;
  disclosures: Partial<Record<DisclosureKey, boolean>>;
  onChange: (key: DisclosureKey, value: boolean) => void;
  onFinish: () => void;
  busy: boolean;
}) {
  const model = settings.models.find((item) => item.id === settings.default_model) ?? null;
  const view = model ? capabilityOf(model) : null;
  const missing = missingForCompletion({
    workspaceOpen: settings.workspace.open,
    modelConfigured: Boolean(model),
    modelHasKey: model ? model.base_url.startsWith('demo://') || model.has_key : false,
  });
  const acknowledged = DISCLOSURE_KEYS.every((key) => disclosures[key]);
  const ready = missing.length === 0 && acknowledged;

  return (
    <div className="space-y-6">
      <RowGroup>
        <Row
          label="فضای کاری"
          description={settings.workspace.open ? <PathText path={settings.workspace.path ?? ''} className="text-muted-foreground text-xs" /> : 'انتخاب نشده'}
        >
          {settings.workspace.open ? <Badge tone="success">{settings.workspace.name}</Badge> : <Badge tone="warning">ندارد</Badge>}
        </Row>
        <Row label="مدل" description={view?.detail ?? 'انتخاب نشده'}>
          {model ? (
            <span className="flex items-center gap-2">
              <span className="text-sm">{model.name}</span>
              {view && <Badge tone={view.tone}>{view.label}</Badge>}
            </span>
          ) : (
            <Badge tone="warning">ندارد</Badge>
          )}
        </Row>
        <Row label="حالت اجرا" description={taskReasonText(readiness ?? null)}>
          <Badge tone={readiness?.task.can_write ? 'success' : 'warning'}>{readiness?.task.can_write ? 'تغییر فایل ممکن' : 'فقط خواندن'}</Badge>
        </Row>
      </RowGroup>

      <div>
        <div className="mb-2 flex items-center justify-between gap-3">
          <div className="text-sm font-semibold">آگاهی‌های لازم</div>
          <span className={cn('text-xs', acknowledged ? 'text-success' : 'text-muted-foreground')}>{DISCLOSURE_KEYS.filter((key) => disclosures[key]).length} از {DISCLOSURE_KEYS.length}</span>
        </div>
        <DisclosureChecklist values={disclosures} onChange={onChange} disabled={busy} />
      </div>

      {missing.length > 0 && (
        <div className="border-warning/30 bg-warning-soft/30 rounded-xl border px-4 py-3">
          <div className="flex items-start gap-2.5">
            <WarningIcon className="text-warning mt-0.5 size-4 shrink-0" />
            <div className="min-w-0">
              <div className="text-sm font-medium">راه‌اندازی هنوز کامل نمی‌شود:</div>
              <ul className="text-muted-foreground mt-1 space-y-0.5 text-xs leading-6">
                {missing.map((item) => (
                  <li key={item}>{missingLabel[item]}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {!acknowledged && missing.length === 0 && <p className="text-muted-foreground text-xs leading-6">برای پایان، هر چهار آگاهی بالا را بخوانید و تیک بزنید.</p>}

      <div className="bg-popover rounded-xl border px-4 py-3">
        <div className="flex items-start gap-2.5">
          <InfoIcon className="text-muted-foreground mt-0.5 size-4 shrink-0" />
          <p className="text-muted-foreground text-xs leading-6">
            با پایان راه‌اندازی وارد میز کار می‌شوی؛ هنوز هیچ تسکی اجرا نشده است. برنامهٔ کار و مجوزهای اجرا را برای همان تسک بررسی و تأیید می‌کنی.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={onFinish} disabled={!ready || busy}>
          {busy ? 'در حال ثبت…' : 'پایان راه‌اندازی'}
        </Button>
        <span className="text-muted-foreground flex items-center gap-1.5 text-xs">
          <CheckCircleIcon className={cn('size-4', ready ? 'text-success' : 'text-muted-foreground/50')} />
          {ready ? 'همهٔ شرط‌ها آماده است.' : 'تا آماده شدن شرط‌ها، دکمه غیرفعال است.'}
        </span>
      </div>
    </div>
  );
}
