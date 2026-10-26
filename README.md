# Bridge Coding Harness

هارنس کدنویسی محلی برای ویندوز: درخواست را تحلیل می‌کند، برنامه پیشنهاد می‌دهد، روی نسخهٔ کاری جدا کد می‌نویسد، تست می‌گیرد و خطاها را با نظارت شما اصلاح می‌کند.

[دانلود نصب‌کنندهٔ Windows x64](https://github.com/Alikavoosi21/bridge-coding-harness/releases/latest) · [راهنمای شروع](docs/QUICKSTART.fa.md) · [پوشش معیارهای چالش](docs/CHALLENGE-ACCEPTANCE-0.2.10.fa.md)

![نشان Bridge](public/brand/approved-bridge.svg)

## قابلیت‌ها

- برنامهٔ قابل ویرایش و تأیید پیش از تغییر کد؛ گفتگو، سؤال و اصلاح درخواست در همان چت.
- خواندن و جستجوی پروژه، ویرایش فایل و اجرای فرمان، نصب پکیج و تست در Docker.
- بررسی نتیجه و اصلاح خودکار؛ بعد از دو تلاش ناموفق، تصمیم شما برای ادامه یا توقف.
- افزودن Skill از فایل، پوشه یا ZIP، ساخت مهارت در اپ و فراخوانی با `/`.
- تأیید/ویرایش/رد عملیات حساس، مجوز همین تسک، Stop، تاریخچه و بازیابی.
- diff و ویرایش دستی، اعمال انتخابی و بازگردانی با حفظ تغییرهای کاربر.
- پیش‌نمایش HTML تعاملی، پنجرهٔ جدا و لینک مرورگر؛ اجرای Python/Node و وب‌سرور با خروجی واقعی.
- رابط فارسی RTL، طراحی سبز Bridge، راه‌اندازی قابل ردکردن و ورود API key و دریافت مدل‌های سرویس داخل اپ.

## نصب و اولین اجرا

۱. از [Releases](https://github.com/Alikavoosi21/bridge-coding-harness/releases/latest) فایل `Bridge-Coding-Harness-Setup-0.2.10.exe` را بگیرید و نصب کنید. فایل `SHA256SUMS.txt` کنار آن است.
۲. در اپ، پوشهٔ پروژه را انتخاب کنید. در تنظیمات مدل، آدرس سرویس و کلید شخصی خودتان را وارد کنید، مدل را انتخاب و توانایی ابزار را بررسی کنید.
۳. Docker Desktop را اجرا کنید و ساخت تصویر محیط Bridge را در بخش آمادگی تأیید کنید؛ تصویر شامل Python، Node و npm است.
۴. فرمان‌های test/lint/build پروژه را بررسی و انتخاب کنید، درخواست بدهید و برنامه را تأیید کنید. تغییرها پیش از Apply وارد پروژهٔ اصلی نمی‌شوند.

نسخهٔ نصبی موتور Python را همراه دارد و به نصب Node/Python روی میزبان نیاز ندارد. Docker و دسترسی API مدل برای اجرای واقعی لازم‌اند. `demo` فقط جریان محصول را نمایش می‌دهد. بدون Docker، shell میزبان جایگزین نمی‌شود. فایل نصب امضای ناشر ندارد و ممکن است Windows SmartScreen هشدار بدهد.

## توسعه از سورس

پیش‌نیاز: Windows، Node.js 24، Python 3.11 یا 3.12 و Docker Desktop برای آزمون اجرای ایزوله.

```powershell
npm ci
py -3.11 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -e "./backend[dev]"
npm run desktop
```

برنامه تنظیمات و کلید را از داخل رابط می‌گیرد. `.env.example` فقط تنظیمات اختیاری و بی‌کلید توسعه را توضیح می‌دهد؛ فایل `.env` خودکار بارگذاری نمی‌شود. هیچ کلید API مشترکی همراه پروژه ارائه نمی‌شود.

```powershell
npm run test:harness
npm run test:engine
npm run typecheck
npm run build:desktop-ui
npm run desktop:build
```

برای بسته‌بندی، `backend/dist/harness-server` توسط PyInstaller ساخته و همراه Electron قرار می‌گیرد. خروجی نصب در `release/dist/` است. تست‌های نیازمند Docker یا قابلیت سیستم‌عامل، بدون پیش‌نیاز واقعی صریحاً skipped می‌شوند؛ نتیجهٔ آن‌ها اثبات اجرا محسوب نمی‌شود.

## معماری و وضعیت بررسی

Next.js + shadcn + Vercel AI SDK در رابط؛ Electron برای دسکتاپ؛ FastAPI، Deep Agents و LangGraph برای موتور؛ SQLite/checkpoint برای ماندگاری؛ Docker برای اجرای فرمان‌ها. راهنمای موتور: [backend/README.md](backend/README.md).

نسخهٔ 0.2.10: ۴۳۹ تست بک‌اند موفق، ۳ skipped؛ ۵۳ بررسی عملی نسخهٔ بسته‌بندی‌شده موفق. سناریوی مدل واقعی و Docker، برنامه‌ریزی، شکست تست، اصلاح کد و موفقیت همان تست را در ۱۳ بررسی تأیید کرد. این اعداد تضمین حل هر پروژه یا پشتیبانی آزموده‌شده از تمام فریم‌ورک‌ها نیستند.

## حریم خصوصی و مجوز

کلید در Windows Credential Manager با هویت `bridge-coding-harness` ذخیره می‌شود. تنظیمات و تاریخچه در `%APPDATA%/BridgeCodingHarness` هستند. گفتگو و محتوای فایل‌های خوانده‌شده به سرویس مدل انتخابی شما ارسال می‌شوند. فایل‌های شخصی، `.env` واقعی، دیتابیس، trace، پروفایل تست و داده‌های کاربر در این مخزن منتشر نمی‌شوند. جزئیات: [SECURITY.md](SECURITY.md).

مجوز [AGPL-3.0](LICENSE). بخش‌هایی از پروژهٔ محلی Onboard Harness اقتباس شده‌اند؛ انتساب و مجوزهای وابستگی‌ها در [third-party-sources](docs/third-party-sources.md) و [docs/licenses](docs/licenses) حفظ شده‌اند. محصول، شناسهٔ ویندوز، تنظیمات و رابط Bridge مستقل‌اند.

