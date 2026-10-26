# اقتباس این محصول مستقل

Bridge Coding Harness از کد پروژهٔ محلی Onboard Harness اقتباس شده است. مجوز AGPL-3.0 و انتساب‌های زیر حفظ می‌شوند. نام‌ها و ادعاهای تاریخی زیر مربوط به پروژهٔ مبدأ هستند.

# دفتر منابع و اقتباس‌های شخص ثالث

**وضعیت:** T001 — baseline تثبیت‌شده در ۲۰۲۶-۱۰-۲۴. این فایل مرجع notices و مجوز اقتباس است؛ ممیزی حقوقی کامل dependency tree نیست.

محصول `Onboard Harness` با مجوز **AGPL-3.0-only** منتشر می‌شود (فایل `LICENSE` بدون تغییر). اضافه‌شدن dependency یا الگوی اقتباسی، مجوز محصول را تغییر نمی‌دهد و مجوز کد اقتباس‌شده را هم بازنویسی نمی‌کند.

## قاعدهٔ اقتباس

1. برای framework از package نصب‌شده استفاده می‌شود؛ source کامل framework در repo محصول vendor نمی‌شود.
2. هر فایل واقعاً اقتباس‌شده (نه صرفاً الهام‌گرفته) باید origin URL + commit/release + مجوز + تغییرهای محلی + notice داشته باشد و در همین فایل ثبت شود.
3. هیچ نمونهٔ UI یا هارنس خارجی در حین بررسی نصب/اجرا نشد؛ فقط source در commit ثابت خوانده شد.
4. الگوهای UI با theme، RTL و رفتار محصول بازنویسی می‌شوند؛ clone کامل template مجاز نیست.
5. ریپوهایی که مجوز محدودکننده دارند (نمونه: React Bits با Commons Clause) خارج از مسیر ضروری MVP می‌مانند و به‌عنوان MIT ادعا نمی‌شوند.

## هفت ریپوی هارنس (الگوی معماری)

| ریپو | مجوز ریشه | commit مرجع | آنچه اقتباس می‌شود | محدودیت | تسک |
|---|---|---|---|---|---|
| [langchain-ai/deepagents](https://github.com/langchain-ai/deepagents) | MIT | `6265589d9529c541778f4ea34f4adffbb9a14016` | backend قراردادمحور، تفکیک approval mode از TUI، middleware پایه | enum پیش‌فرض جای سه mode محصول نیست؛ default نسخهٔ نصب‌شده بررسی می‌شود | T006/T009 |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | MIT | `4c52e129eb1ab69a3da58b799f67929f77d81149` | interrupt/Command و SQLite saver پایدار | checkpoint اثبات نتیجهٔ runtime یا تراکنش filesystem نیست | T003/T006/T016 |
| [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) | MIT | `fee10e3d2909ebbf9950578575b1ee011492171e` | تفکیک نمای فایل/diff از داده و نمایش کد | Monaco و معماری cloud آن الزامی نیست | T013/T014 |
| [cline/cline](https://github.com/cline/cline) | Apache-2.0 | `40c5d99031fe1128189c5b52e40638d2b7787754` | تفکیک policy baseline از override و callback نمایش approval | `autoApproveAll` و session flag جای consent/hash پایدار نیست | T009/T010 |
| [anomalyco/opencode](https://github.com/anomalyco/opencode) | MIT | `0093fe5782766f180167efab86fb8fdb3c5b6a4a` | dock تصمیم نزدیک تعامل، props responding/decision | source آن SolidJS است؛ clone مستقیم React نمی‌شود؛ `always` فقط grant همین کار | T009/T010 |
| [Aider-AI/aider](https://github.com/Aider-AI/aider) | Apache-2.0 | `5dc9490bb35f9729ef2c95d00a19ccd30c26339c` | محدودیت token/context، انتخاب فایل مرتبط | graph-ranking/Tree-sitter کامل لازم نیست؛ search/sliced read کافی است | T004/T006 |
| [openai/codex](https://github.com/openai/codex) | Apache-2.0 | `970111f6cb62cc02fe36a82ea7d71b37a2889c97` | جداسازی request اجرا، cwd/env/network و adapter runtime | backend native OS آن کپی نمی‌شود؛ Docker template مرز اجراست | T004/T009 |

## پنج مرجع UI

| مرجع | commit مرجع | یادگیری | محدودیت | تسک |
|---|---|---|---|---|
| [vercel/ai](https://github.com/vercel/ai) | `39aae5425e9f9a25acce413cc7e6823c2b5a73c5` | قرارداد ChatTransport، chunk lifecycle و reconnect | direct protocol دوم یا LangGraph UI transport موازی اضافه نشود | T007 |
| [vercel/ai-elements](https://github.com/vercel/ai-elements) | `ca8be600bfd01b3131f9bf6134b51602a71f4374` | Conversation/PromptInput/Tool/Plan/Confirmation | component است، نه موتور؛ نصب preset نباید token/فونت را overwrite کند | T002/T008/T010 |
| [shadcn-ui/ui](https://github.com/shadcn-ui/ui) | `617134d5810bba521803b3ed787190bacbb80b35` | composition primitive و مالکیت source محلی | Radix موجود حفظ؛ alias/RTL portal بررسی شود | T002 |
| [vercel/chatbot](https://github.com/vercel/chatbot) | `c2f8235e1f3ea903ad8b7f61447c4f74164b5c58` | سازمان‌دهی chat component و anchoring | auth/cloud DB آن اقتباس نشود | T008 |
| [langchain-ai/agent-chat-ui](https://github.com/langchain-ai/agent-chat-ui) | `7a503412aeeb4534a24b04bd97b618ee3871821e` | نمایش interrupt و حفظ thread context | transport دوم آن اضافه نشود | T010/T016 |

شاهد دریافت فایل‌ها (اندازه و SHA256 محتوای نرمال‌شده) در `specs/004-local-harness-execution/repo-evidence.json` ثبت است. آن hash، hash آرشیو/commit نیست و raw فایل در محصول کپی نشده است.

## فایل‌های واقعاً اقتباس‌شده (نه فقط الگو)

| فایل مقصد | منبع | تغییرهای محلی |
|---|---|---|
| `src/components/ai-elements/conversation.tsx` | `https://registry.ai-sdk.dev/conversation.json` (vercel/ai-elements) | Button پروژهٔ موجود، `ArrowDownIcon` از Phosphor، aria-label فارسی، `start-[50%]` منطقی |
| `src/components/ai-elements/message.tsx` | `https://registry.ai-sdk.dev/message.json` | Button پروژه، ButtonGroup درون‌فایل، آیکون‌های Phosphor، `ms-auto`/`end-2`، متن‌های فارسی، حذف `title` تکراری SVG |
| `src/components/ai-elements/loader.tsx` | `https://registry.ai-sdk.dev/loader.json` | aria-hidden، حذف `<title>` تکراری |
| `src/components/ui/shadcn/*.tsx` (۱۶ فایل) | `https://ui.shadcn.com/r/styles/new-york/<name>.json` | import از `@/lib/utils`، آیکون Phosphor به‌جای lucide، `ms-auto` در منو |

مجوز shadcn، MIT است؛ `ai` و AI Elements مطابق LICENSE رسمی Vercel با Apache-2.0 ارائه می‌شوند. برچسب MIT قبلی برای AI Elements نادرست بود و با دریافت notice رسمی در T010 اصلاح شد. فایل‌های اقتباسی raw کپی نشده‌اند؛ تغییرها همان ستون آخر است. notice و متن مجوز در `docs/licenses/` نگهداری می‌شوند.

## Dependencyهای runtime و مجوز نصب‌شده

نسخه‌ها همان چیزی است که `package-lock.json` و `backend/uv.lock` قفل کرده‌اند؛ منبع حقیقت برای بازتولید همین دو فایل است.

### فرانت‌اند (npm)

| package | نسخهٔ قفل‌شده | مجوز |
|---|---|---|
| next | 16.4.3 | MIT |
| react / react-dom | 19.3.0 | MIT |
| ai | 7.0.153 | Apache-2.0 |
| @ai-sdk/react | 4.0.157 | Apache-2.0 |
| zod | 4.6.7 | MIT |
| @codemirror/state · view · merge | 6.7.6 · 6.43.15 · 6.12.3 | MIT |
| @uiw/react-codemirror | 4.25.12 | MIT |
| diff (jsdiff) | 9.0.0 | BSD-3-Clause |
| streamdown | 2.7.1 | Apache-2.0 |
| nanoid | 6.0.2 | MIT |
| use-stick-to-bottom | 1.1.6 | MIT |
| radix-ui | 1.7.0 | MIT |
| zustand | 5.0.15 | MIT |
| @phosphor-icons/react | 2.1.10 | MIT |
| react-markdown / remark-gfm | 10.1.0 / 4.0.1 | MIT |
| tailwindcss | 4.3.3 | MIT |
| electron | 44.7.0 | MIT |
| typescript | 5.9.3 | Apache-2.0 |

### بک‌اند (Python، از `backend/uv.lock`)

| package | نسخهٔ حل‌شده | مجوز |
|---|---|---|
| deepagents | 0.7.32 | MIT |
| langchain | 1.4.7 | MIT |
| langgraph | 1.2.17 | MIT |
| langgraph-checkpoint-sqlite | 3.1.2 | MIT |
| langchain-anthropic / langchain-openai | 1.7.6 / 1.7.2 | MIT |
| fastapi | 0.162.0 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| pydantic | 2.14.1 | MIT |
| keyring | 25.7.0 | MIT |
| pytest / httpx | 9.1.1 / 0.28.1 | MIT / BSD-3-Clause |
| wcmatch | 11.2 | MIT |
| openpyxl / python-docx / python-pptx | 3.1.5 / 1.2.0 / 1.0.2 | MIT |
| pypdf | 6.21.2 | BSD-3-Clause |
| xlrd / olefile | 2.0.2 / 0.47 | BSD |
| playwright | 1.64.1 | Apache-2.0 |
| pyyaml | 6.0.3 | MIT |

## فونت

`Vazirmatn-FD-*` در `src/app/fonts/` همراه `OFL.txt` عرضه می‌شود؛ از CDN بارگذاری نمی‌شود. متن مجوز فونت در همان پوشه نگه داشته می‌شود.

## کارهای باقی‌ماندهٔ notices

### T010 — فایل‌های Confirmation و Tool

`src/components/ai-elements/confirmation.tsx` و `tool.tsx` از منبع رسمی Apache-2.0ِ vercel/ai-elements در registry گرفته و برای UI محصول محدود/سازگار شدند (۲۰۲۶-۱۰-۲۵). مراجع دقیق منبع دریافت‌شده: [confirmation.json](https://registry.ai-sdk.dev/confirmation.json)، SHA-256 محتوای فایل `91d34ea897e0f8257bfc8e5450f4787390f35be4b0aea58b21ba9b274ee6a015`؛ [tool.json](https://registry.ai-sdk.dev/tool.json)، `c4ac8a0dede6e001314dc19f7bb60dde2a58d8446d8b70a8ec1be35d480c0ab6`. رجیستری commit ارائه نمی‌کند؛ این hashها نسخهٔ خوانده‌شده را مشخص می‌کنند، نه ادعای تطبیق با commit قدیمی جدول.

تغییرهای محلی: import اجزای shadcn موجود، Phosphor به‌جای Lucide، labels فارسی و توکن برند، stateهای واقعی SDK نصب‌شده بدون ts-expect-error، plain pre محدود به‌جای وابستگی code-block و فقط exportهای مصرف‌شده. callbackها تصمیم backend را فراخوانی می‌کنند؛ هیچ مجوز یا حلقهٔ اجرای AI SDK جداگانه‌ای ساخته نشده است. notice رسمی Copyright 2023 Vercel, Inc. در `docs/licenses/ai-elements-NOTICE.txt` و متن کامل Apache-2.0 در همان پوشه حفظ شده‌اند؛ source URL در سرآیند فایل‌های اقتباسی است.

- T018: بازبینی نهایی notices/source ledger همراه release gate و بررسی این‌که هیچ فایل اقتباسی بدون ردیف ثبت نشده باشد.
- پیش از هر اقتباس فایل جدید (نه صرفاً الگو)، همین جدول به‌روزرسانی شود.

## اتصال سرویس و انتخاب مدل (۰٫۲٫۲)

الگوی جریان از مستندات رسمی OpenCode providers/models بررسی شد؛ کد OpenCode کپی نشده است. تلاش خواندن فایل سورس 404 داد. جزئیات منابع و مرز اقتباس در deferred-setup-models.fa.md است.
