'use client';

import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';

type Permission = { id: string; expiry: number };
type Consent = { confirm: true; expected_revision: number; duration_seconds: number; idempotency_key: string };

export function SandboxNetwork({ taskId, revision, status, readOnly }: {
  taskId: string; revision: number; status?: string | null; readOnly: boolean;
}) {
  const [permission, setPermission] = useState<Permission | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const pending = useRef<Consent | null>(null);
  const endpoint = `/tasks/${encodeURIComponent(taskId)}/network-permission`;
  useEffect(() => {
    let disposed = false;
    setLoaded(false);
    void api.get<{ permission: Permission | null }>(endpoint).then(result => {
      if (!disposed) { setPermission(result.permission); setLoaded(true); setError(null); }
    }).catch(error => { if (!disposed) setError(error instanceof Error ? error.message : 'خواندن مجوز ممکن نشد.'); });
    return () => { disposed = true; };
  }, [endpoint, revision, status]);
  useEffect(() => {
    if (!permission) return;
    setNow(Date.now() / 1000);
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [permission]);
  const active = loaded && permission !== null && permission.expiry > now;
  const idle = !['queued', 'planning', 'executing', 'verifying', 'repairing', 'stopping', 'closed', 'failed', 'cancelled', 'recovery_required'].includes(status ?? 'closed');
  const change = async (revoke: boolean) => {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      if (revoke) {
        await api.post(`${endpoint}/revoke`);
        setPermission(null); pending.current = null; setConfirmed(false);
      } else {
        if (!pending.current) {
          const task = await api.get<{ revision: number }>(`/tasks/${encodeURIComponent(taskId)}`);
          pending.current = { confirm: true, expected_revision: task.revision, duration_seconds: 300, idempotency_key: crypto.randomUUID() };
        }
        const result = await api.post<{ permission: Permission | null }>(endpoint, pending.current);
        setPermission(result.permission); setLoaded(true); setNow(Date.now() / 1000);
        pending.current = null; setConfirmed(false);
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : 'تغییر مجوز ممکن نشد.');
      // Retain the same consent receipt for a transport retry; a definitive
      // rejection can be reviewed afresh by unchecking the consent.
    } finally { setBusy(false); }
  };
  return <section aria-label="شبکهٔ محیط ایزوله" className="space-y-3 rounded-lg border p-3 text-xs leading-6">
    <p className="font-semibold">شبکهٔ محیط ایزوله: {!loaded ? 'وضعیت نامشخص' : active ? 'فعال برای همین کار' : 'غیرفعال'}</p>
    <p className="text-muted-foreground">اتصال سرویس مدل جداست. مجوز شبکه پنج دقیقه اعتبار دارد؛ هر فرمان شبکه یا نصب همچنان تأیید جداگانه می‌خواهد.</p>
    {active ? <><p role="status">اعتبار باقی‌مانده: {Math.max(0, Math.ceil(permission.expiry - now)).toLocaleString('fa-IR')} ثانیه</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void change(true)}>لغو شبکه و درخواست توقف اجرای جاری</Button></> : <>
      <label className="flex items-start gap-2"><input type="checkbox" checked={confirmed} disabled={busy || readOnly || !idle || !loaded} onChange={event => { setConfirmed(event.target.checked); pending.current = null; }} />اجازه می‌دهم فرمان‌های تأییدشدهٔ این کار تا پنج دقیقه به اینترنت دسترسی داشته باشند.</label>
      <Button size="sm" variant="outline" disabled={!confirmed || busy || readOnly || !idle || !loaded} onClick={() => void change(false)}>فعال‌سازی پنج‌دقیقه‌ای شبکه</Button>
      {(readOnly || !idle) && <p className="text-muted-foreground">فعال‌سازی فقط برای کار قابل‌نوشتن و متوقف‌شده ممکن است.</p>}
    </>}
    {error && <p role="alert" className="text-danger">{error}</p>}
  </section>;
}
