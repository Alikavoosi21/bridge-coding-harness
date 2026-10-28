'use client';

import { ArrowLeftIcon, ArrowRightIcon, CheckCircleIcon, CodeIcon, FolderOpenIcon, KeyIcon, ListChecksIcon, ShieldCheckIcon, TerminalIcon, type Icon } from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';
import { BridgeSymbol } from '@/components/shared/brand';
import { Button } from '@/components/ui/button';
import { useBackend } from '@/lib/backend';
import { api, ApiError } from '@/lib/api';
import { cn } from '@/lib/utils';

const SEEN_KEY = 'bridge-coding-intro-v3';
export function onboardingSeen() {
  try { return localStorage.getItem(SEEN_KEY) === '1'; } catch { return false; }
}
function remember() {
  try { localStorage.setItem(SEEN_KEY, '1'); } catch { /* Introduction stays available without storage. */ }
}
function Point({ icon: Symbol, title, children }: { icon: Icon; title: string; children: React.ReactNode }) {
  return <li className="flex gap-3"><span className="bg-primary-soft text-primary flex size-10 shrink-0 items-center justify-center rounded-lg"><Symbol className="size-5" /></span><div><h2 className="text-sm font-semibold">{title}</h2><p className="text-muted-foreground mt-1 text-sm leading-7">{children}</p></div></li>;
}
const steps = [
  {
    title: 'تسک را بسپار. تغییر را خودت تأیید کن.',
    lead: 'Bridge میز کار کدنویسی توست؛ برای شناخت پروژه، رفع باگ و ساخت قابلیت، از درخواست تا کدِ بررسی‌شده.',
    body: <div className="space-y-6">
      <div className="bg-surface rounded-lg border p-5"><div className="text-primary mb-3 text-xs font-medium">نمونهٔ درخواست برای یک پروژهٔ کدنویسی</div><p className="text-sm leading-8">«علت شکست تست را پیدا کن، فقط کد مرتبط را اصلاح کن و قبل از اعمال، تغییرها و نتیجهٔ تست را نشان بده.»</p></div>
      <ul className="space-y-5"><Point icon={CodeIcon} title="همکارِ داخل پروژه">ایجنت ساختار مخزن و فایل‌های مرتبط را می‌خواند و کار را به گام‌های قابل پیگیری می‌شکند.</Point><Point icon={ShieldCheckIcon} title="تصمیم نهایی با توست">برنامه، مجوزها و تغییرات را می‌بینی؛ می‌توانی ویرایش یا رد کنی و هر زمان لازم شد توقف بخواهی.</Point></ul>
    </div>,
  },
  {
    title: 'اول برنامه، بعد تغییر.',
    lead: 'هر تسک یک مسیر روشن دارد. گفتگو، فعالیت، برنامه و بازبینی کد در همان میز کار کنار هم‌اند.',
    body: <ol className="space-y-5">
      <Point icon={ListChecksIcon} title="۱. بررسی و تأیید برنامه">پیش از تغییر، گام‌ها و محدودهٔ فایل‌ها را بررسی و در صورت نیاز اصلاح می‌کنی.</Point>
      <Point icon={TerminalIcon} title="۲. اجرا و اصلاح در محیط جدا">فایل‌ها در فضای همین گفتگو ساخته می‌شوند؛ اجرا و تست با ابزارهای همراه خود اپ انجام می‌شوند. بعد از دو اصلاح ناموفق، ادامه به تصمیم تو نیاز دارد.</Point>
      <Point icon={CheckCircleIcon} title="۳. بازبینی و اعمال">diff و خروجی واقعی تست را می‌بینی، دستی ویرایش می‌کنی و انتخاب می‌کنی کدام تغییر روی پروژهٔ اصلی اعمال شود.</Point>
    </ol>,
  },
  {
    title: 'پروژه‌ات را برای اولین تسک آماده کن.',
    lead: 'راه‌اندازی را می‌توانی الان انجام بدهی یا رد کنی و بعداً از داخل برنامه ادامه بدهی.',
    body: <div className="space-y-5"><ul className="space-y-4">
      <Point icon={FolderOpenIcon} title="پروژه">پوشهٔ مخزن کد را انتخاب کن. برای شروع می‌توانی از نمونهٔ python-bug همراه سورس استفاده کنی.</Point>
      <Point icon={KeyIcon} title="مدل">نشانی سرویس، نام مدل و کلید API را در گام مدل وارد کن؛ مدل ذخیره‌شده را بررسی و پیش‌فرض کن. حساب همین چت خودکار به Bridge وصل نمی‌شود.</Point>
      <Point icon={TerminalIcon} title="محیط و فرمان‌ها">Python و Node همراه برنامه‌اند؛ چیزی نصب نکن. برای دیدن نتیجه «اجرا و نمایش» را بزن.</Point>
      <Point icon={ShieldCheckIcon} title="بازبینی راه‌اندازی">مدل، پروژه و دسترسی‌ها را مرور کن و خودت پایان راه‌اندازی را تأیید کن.</Point>
    </ul><p className="bg-primary-soft text-primary rounded-lg p-4 text-xs leading-7">بدون کلید هم می‌توانی روند را با مدل نمایشی ببینی؛ demo کدنویسی با مدل واقعی نیست. انتخاب پوشه اختیاری است؛ Bridge خودش فضای ساخت را آماده می‌کند. فرمان محلی دسترسی حساب ویندوز تو را دارد.</p></div>,
  },
];
export function Onboarding({ onDone }: { onDone: () => void }) {
  const [index, setIndex] = useState(0);
  const scrollRegion = useRef<HTMLDivElement>(null);
  useEffect(() => { scrollRegion.current?.scrollTo(0, 0); }, [index]);
  const engineReady = useBackend(s => s.status === 'ready');
  const completed = useBackend(s => s.settings?.setup.completed ?? false);
  const refreshSettings = useBackend(s => s.refreshSettings);
  const [leaving, setLeaving] = useState(false);
  const [error, setError] = useState('');
  const last = index === steps.length - 1;
  const finish = () => { remember(); onDone(); };
  const later = async () => {
    setLeaving(true);
    try { if(!completed){await api.post('/setup/defer', {}); await refreshSettings();} finish(); }
    catch(e){setError(e instanceof ApiError ? e.message : 'ورود به برنامه ممکن نشد.');}
    finally{setLeaving(false);}
  };
  return <div className="bg-background flex h-dvh flex-col">
    <div className="desktop-strip app-drag" />
    <div ref={scrollRegion} className="scrollbar-minimal flex flex-1 items-start justify-center overflow-y-auto p-4 sm:p-6">
      <section aria-labelledby="coding-intro-title" className="bg-panel my-auto w-full max-w-2xl rounded-xl border p-5 sm:p-8">
        <div className="flex items-center gap-3"><BridgeSymbol size={42} /><div className="flex-1"><div dir="ltr" className="text-start text-sm font-semibold">Bridge Coding</div><p className="text-muted-foreground mt-1 text-xs">هارنس کدنویسی محلی</p></div><Button variant="ghost" size="xs" disabled={leaving || !engineReady} onClick={()=>void later()}>رد کردن</Button></div>
        <div className="mt-6 flex gap-2" role="progressbar" aria-label="معرفی هارنس کدنویسی" aria-valuemin={1} aria-valuemax={steps.length} aria-valuenow={index + 1}>{steps.map((step,i)=><span key={step.title} className={cn('h-1 flex-1 rounded-full',i<=index?'bg-primary':'bg-secondary')} />)}</div>
        <h1 id="coding-intro-title" className="mt-6 text-xl font-semibold leading-9">{steps[index].title}</h1>
        <p className="text-muted-foreground mt-2 text-sm leading-7">{steps[index].lead}</p>
        <div className="mt-6">{steps[index].body}</div>
        {error&&<p role="alert" className="text-danger mt-3 text-sm">{error}</p>}
        {last&&!completed&&<Button variant="ghost" className="mt-4" disabled={leaving || !engineReady} onClick={()=>void later()}>فعلاً وارد برنامه می‌شوم</Button>}
        <div className="mt-7 flex items-center justify-between gap-3 border-t pt-5"><Button variant="ghost" size="sm" disabled={index===0} onClick={()=>setIndex(index-1)}><ArrowRightIcon /> قبلی</Button><span className="text-muted-foreground text-xs">{index+1} از {steps.length}</span>{last?<Button onClick={finish}>{completed?'ورود به میز کار':'راه‌اندازی پروژه'}<ArrowLeftIcon /></Button>:<Button onClick={()=>setIndex(index+1)}>بعدی<ArrowLeftIcon /></Button>}</div>
      </section>
    </div>
  </div>;
}
