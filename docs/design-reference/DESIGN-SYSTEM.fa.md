# سیستم دیزاین Onboard Harness

نسخه 1.0.0 پیش‌نویس اجرایی · حالت تیره · دسکتاپ Windows و نمایشگر وب محلی · لوگوی منتخب Bridge.

این راهنما زبان بصری Vertex را به محصول گفتگویی هارنس تبدیل می‌کند. رنگ‌های پایه و گردی 8px از فایل Vertex ارسالی‌اند؛ میزان تفصیل، معرفی حالت‌ها و مستندسازی حرکت از بستهٔ مطالعهٔ ترب الهام گرفته‌اند. مقادیر تکمیلی این سند تصمیم طراحی ما هستند و به ترب یا سازندهٔ Vertex نسبت داده نمی‌شوند. صفحهٔ HTML مرجع Vertex در پیوست وجود ندارد؛ screenshotها فقط ظاهر صفحهٔ معرفی آن را نشان می‌دهند. بازسازی پیکسلی خود hero یا بررسی live آن ادعا نمی‌شود.

این بسته شامل توکن JSON/CSS، نشان SVG و PNG، پنج GIF واقعی با poster ثابت، کاتالوگ HTML آفلاین و انتخاب‌های مستند React Bits است. کاتالوگ دادهٔ نمایشی با برچسب صریح دارد؛ محصول واقعی یا engine متصل نیست.

## 1 مبنای هویت و سطح شواهد

| ورودی | نقش | آنچه حفظ می‌شود | آنچه برای هارنس تغییر می‌کند |
|---|---|---|---|
| فایل Vertex DESIGN.md | مرجع برند | green #4ADE80، accent #10B981، canvas #010A04، surface #191C21، rounded 8px | display تبلیغاتی به رابط فشردهٔ coding تبدیل می‌شود |
| screenshotهای کاربر | مرجع ظاهر | سطوح تیره، هندسهٔ صاف، تاکید سبز کنترل‌شده | hero پرتحرک وارد صفحهٔ diff/approval نمی‌شود |
| ZIP مطالعهٔ ترب | مرجع عمق مستندات | حالت‌ها، آناتومی composer، RTL، نقش mascot، سطح شواهد | رنگ قرمز، لوگو و فونت اختصاصی ترب استفاده نمی‌شوند |
| مصاحبهٔ محصول | مرجع رفتار | گفتگو محور، plan/diff زنده، مجوز کنار composer، دو repair | UI باید تفاوت محیط و سطح مجوز را آشکار کند |
| لوگوی انتخاب‌شده B | تایید جهت کاربر | H با اتصال پله‌ای | نسخهٔ دوم GIFها با اجازهٔ کاربر، چرخش و تبدیل خود نشان را به کار می‌برد |
| React Bits pinned source | منبع انیمیشن خارجی | API واقعی و نسخهٔ ثبت‌شده | palette، شدت، دامنه کاربرد و کاهش حرکت محدود می‌شوند |

اصل طراحی: گفتگو و کد مرکز توجه‌اند؛ وضعیت‌ها باید قابل‌فهم باشند و افکت فقط هنگام تغییر معنی ظاهر شود. رنگ سبز نشان برند و فعالیت است؛ موفقیت باید علاوه بر رنگ آیکون/متن و نتیجهٔ verifier داشته باشد. نمایش «محلی» محل اجرای هارنس را توضیح می‌دهد، نه تضمین آفلاین بودن مدل API.

## 2 شخصیت بصری و سلسله‌مراتب

شخصیت: دقیق، آرام، فنی، قابل‌کنترل و همراه. بوم سبز نزدیک به مشکی، سطح‌های خنثی اندکی سبز، یک اقدام اصلی روشن و متن سفید. کنترل‌ها گوشهٔ 8px دارند؛ composer و dialog برای تشخیص محفظه 12px. pill فقط badge، شمارنده و انتخاب‌گر کوچک است؛ همهٔ کارت‌ها کپسولی نمی‌شوند.

ترتیب توجه در خانه: هدف کاربر → composer → workspace/model/مجوز → وضعیت محیط → تاریخچه. در task فعال: آخرین رخداد معنی‌دار → درخواست تأیید در صورت وجود → Stop → گام جاری → diff و نتیجهٔ بررسی. در review: فایل تغییرکرده → diff → نتیجهٔ بررسی → اعمال روی پروژهٔ اصلی.

سبز روشن روی سطح اصلی کمتر از حدود 10٪ مساحت نمونهٔ معمول باشد؛ این نسبت guideline بصری است و معیار ماشینی انطباق نیست. سفید روی دکمهٔ سبز ممنوع؛ متن روی برند #010A04 است. glow جای contrast را نمی‌گیرد.

## 3 معماری توکن

سه لایه: primitive → semantic → component. primitive فقط تعریف پالت/اندازه است؛ component از semantic استفاده می‌کند. مثال: green.400 → action.primary → button.primary.background. شناسه‌های JSON و نام‌های CSS در tokens.json و tokens.css مرجع اجرا هستند. کد محصول نباید HEX پراکنده یا alias بی‌معنی مانند primary2 بسازد.

| توکن پایه از Vertex | مقدار | سیاست |
|---|---|---|
| brand.primary | #4ADE80 | برند و CTA با متن تیره |
| brand.accent | #10B981 | تزئین و حرکت محیطی؛ متن ریز روی آن خودکار سفید نشود |
| brand.secondary | #000000 | مشکی مطلق برای برند/مونو؛ جایگزین تمام سطوح نیست |
| brand.canvas | #010A04 | بوم غالب |
| brand.surface | #191C21 | سطح فیلد/کنترل |
| neutral.0 | #FFFFFF | متن اصلی |
| border.source | #D4D4D4 | رنگ مرز اعلام‌شده مرجع؛ فقط مرز با تاکید زیاد، نه همه کارت‌ها |

پالت سبز تکمیلی: 50 #F0FDF4، 100 #DCFCE7، 200 #BBF7D0، 300 #86EFAC، 400 #4ADE80، 500 #22C55E، 600 #16A34A، 700 #15803D، 800 #166534، 900 #14532D، 950 #052E16. این پله‌ها تکمیل طراحی‌اند و از screenshot استخراج نشده‌اند.

## 4 رنگ‌های معنایی و کنتراست

| نام CSS | HEX | کاربرد |
|---|---|---|
| --bg-canvas | #010A04 | صفحهٔ اصلی |
| --bg-sidebar | #080E0B | ناوبری |
| --bg-panel | #101712 | inspector و plan |
| --bg-surface | #191C21 | input، card و dialog |
| --bg-raised | #222A25 | سطح برجسته |
| --bg-hover | #28352C | hover کنترل خنثی |
| --bg-selected | #12351F | انتخاب task/tab |
| --bg-code | #080D0B | کد و command |
| --text-primary | #FFFFFF | متن اصلی |
| --text-secondary | #B8C2BB | توضیح و متن فرعی |
| --text-muted | #9CA89F | metadata و caption خواندنی |
| --text-disabled | #6D7870 | فقط کنترل واقعا disabled |
| --border-subtle | #2C3930 | تقسیم‌بندی تزئینی |
| --border-default | #58705F | مرز لازم برای شناخت کنترل |
| --border-strong | #91A798 | تاکید بدون active |
| --focus-ring | #4ADE80 | فوکوس keyboard |
| --action-primary | #4ADE80 | CTA و Send |
| --action-hover | #86EFAC | hover CTA |
| --action-pressed | #22C55E | pressed |
| --text-on-brand | #010A04 | label روی CTA |

متن muted نسبت به Vertex از #A1A1AA به سبزخاکستری خواناتر تکمیل شده؛ مقدار اصلی فقط در primitive می‌ماند. مرز اولیه #526A59 نسبت 2.90 روی surface داشت و به #58705F با نسبت 3.17 اصلاح شد. border-subtle مدرک مرز کنترل نیست و برای کنترل‌های بدون سطح متمایز تنها استفاده نمی‌شود.

| جفت محاسبه‌شده | نسبت | هدف |
|---|---|---|
| سفید روی canvas | 20.07 | ≥4.5 متن |
| secondary روی surface | 9.33 | ≥4.5 |
| muted روی surface | 6.93 | ≥4.5 |
| on-brand روی primary | 11.52 | ≥4.5 |
| focus روی surface | 9.80 | ≥3 نشانهٔ غیرمتنی |
| border-default روی surface | 3.17 | ≥3 |
| warning روی warning-bg | 10.24 | ≥4.5 |
| danger روی danger-bg | 8.73 | ≥4.5 |

گزارش ماشینی checks/contrast.json صرفاً جفت‌های توکن اعلام‌شده را می‌سنجد؛ اثبات انطباق کل UI با WCAG نیست. ترکیب نهایی alpha، text روی gradient و حالت focus در صفحه باید جدا بررسی شود. حالت high contrast به forced-colors سیستم واگذار می‌شود؛ به box-shadow تنها برای focus اتکا نمی‌کنیم.

### رنگ وضعیت و کد

| معنی | foreground | background | نشانهٔ مکمل |
|---|---|---|---|
| درحال اجرا | #4ADE80 | #12351F | حرکت سیگنال/برچسب |
| موفقیت بررسی | #86EFAC | #102B1B | check و نام check |
| انتظار تایید | #FCD34D | #30270F | pause و دکمه‌های تصمیم |
| خطا | #FDA4AF | #31171E | علامت خطا، متن و راه بازیابی |
| اطلاع | #93C5FD | #122336 | info و توضیح |
| توقف | #B8C2BB | #191C21 | مربع/paused بدون loop |

diff اضافه: زمینه #102B1B، متن #BBF7D0 و +؛ حذف: زمینه #31171E، متن #FECDD3 و −. علامت‌ها و شمارهٔ خط برای color-blind ضروری‌اند. syntax keyword #C4B5FD، string #BBF7D0، number #FCD34D، function #93C5FD، comment #9CA89F؛ این رنگ‌ها status نیستند و parser editor مسئول رنگ‌گذاری است.

## 5 تایپوگرافی فارسی و کد

متن فارسی از Vazirmatn موجود پروژه، self-hosted و دارای OFL استفاده می‌کند؛ Pixelify Sans اعلام‌شده در Vertex برای بدنهٔ فارسی جایگزین نشده است. حال‌وهوای پیکسلی در wordmark و قطعه‌های حرکت می‌ماند. Inter برای display لاتین و JetBrains Mono برای code در spec ترجیح‌اند؛ فایل آن‌ها در این بسته دریافت نشده، پس fallback واقعی کاتالوگ Segoe UI و Consolas/Cascadia Code است. هیچ فونت CDN در اجرای محلی لود نمی‌شود.

| نقش | اندازه/line-height px | وزن | کاربرد |
|---|---|---|---|
| display لاتین | 48/56؛ فقط landing تا 64/67 | 500 | نام و پیام افتتاحیه؛ نه عنوان task |
| h1 فارسی | 28/40 | 700 | عنوان صفحه |
| h2 | 22/34 | 600 | بخش اصلی |
| h3 | 18/28 | 600 | card/dialog title |
| body | 15/28 | 400 | پاسخ و متن UI |
| body-lg | 16/30 | 400 | composer و توضیح شروع |
| label | 14/24 | 600 | دکمه و input label |
| caption | 12/20 | 400 | metadata با contrast مناسب |
| code | 13/22 | 400 | diff و command |
| technical label | 12/20 | 600 | مدل، runtime و اندازه‌ها |

متن فارسی letter-spacing صفر، wrapping طبیعی و نیم‌فاصله درست دارد. اعداد تجربهٔ کاربری فارسی‌اند؛ code، hash، port، token count فنی و path بدون تبدیل حروف باقی می‌مانند. پاراگراف مدل dir=auto؛ shell/code همیشه dir=ltr و unicode-bidi:isolate. path تک‌خطی در bdi، trim وسط برای مسیر طولانی و امکان copy کامل. متن فارسی داخل badge uppercase نمی‌شود.

## 6 فاصله هندسه و اندازه

پایهٔ layout برابر 8px با ریزمقیاس 4px؛ scale: 0،2،4،6،8،12،16،20،24،32،40،48،64،80. 2 برای micro separation/outline، 6 برای icon gap و motion distance، 8 برای ردیف فشرده، 16 برای کنترل‌های گروهی، 24 برای card، 32 برای بخش صفحه و 80 فقط landing section.

| مورد | مقدار |
|---|---|
| radius کوچک | 4px برای code chip |
| radius control/card | 8px |
| radius composer/dialog | 12px |
| radius pill | 9999px فقط badge |
| مرز | 1px؛ focus 2px با offset 3px |
| button sm/md/lg | ارتفاع 32/40/48؛ padding افقی 12/16/20 |
| icon | 16/20/24؛ stroke یکنواخت family |
| icon button | 36×36 استاندارد؛ 40×40 اقدام مهم |
| sidebar | 264px؛ rail 64px |
| inspector | 320px؛ قابل resize از 280 تا 420 |
| header | 56px زیر titlebar |
| titlebar Electron | 36px؛ کنترل OS با theme هماهنگ |
| عرض خواندن گفتگو | max 880px |
| padding صفحه | 24px؛ در compact برابر 16px |

حداقل hit target داخلی 32px برای dense row و 40px برای اقدام اصلی؛ فاصله حداقل 8px میان targets نزدیک. سایهٔ پیش‌فرض card صفر؛ dialog با 0 16px 48px #00000066 و popover با 0 8px 24px #0000004D. focus ring shadow تزئینی نیست و outline واقعی دارد.

## 7 layout و رفتار تغییر اندازه

v1 اپ دسکتاپ است؛ حداقل window 1024×640، مرجع 1440×900. پوسته `height:100dvh`، grid و `minmax(0,1fr)`؛ transcript تنها ناحیهٔ scroll گفتگو است و composer ثابت در پایین ستون خود باقی می‌ماند. صفحه با افکت hero بلند جایگزین نمی‌شود.

| عرض | ناوبری | inspector | diff |
|---|---|---|---|
| 1440 و بالاتر | sidebar 264 | 320 باز | side-by-side در فضای کافی |
| 1280–1439 | sidebar یا rail | tab/drawer؛ کاربر می‌تواند باز کند | side-by-side با حداقل هر ستون 360 |
| 1024–1279 | rail 64 | drawer با overlay | unified پیش‌فرض |
| زیر 1024 فقط کاتالوگ/وب | منوی کوچک | modal/tab | unified و scroll افقی code |

این بسته کاتالوگ موبایل هم دارد تا reference قابل‌مطالعه باشد؛ این به معنی افزودن mobile app به scope نیست. content inspector در RTL سمت چپ بدنه، ناوبری سمت راست و titlebar controls سمت تعیین‌شدهٔ OS قرار می‌گیرند. استفاده از inline-start/end به‌جای left/right ثابت ضروری است؛ code gutter با RTL mirror نمی‌شود.

z-index: base 0، sticky 10، popover 30، scrim 40، drawer 50، dialog 60، toast 70، tooltip 80. منوی permission داخل dialog باید در portal لایهٔ درست باشد و زیر scrim نرود. user selection در diff و command نباید با draggable titlebar تداخل کند.

## 8 قرارداد حالات مشترک کنترل‌ها

| حالت | ظاهر | رفتار |
|---|---|---|
| default | surface، border-default، text-primary | focusable |
| hover | bg-hover؛ CTA action-hover | فقط pointer؛ اطلاعات لازم مخفی در hover نباشد |
| focus-visible | 2px ring و offset 3 | keyboard focus بدون حذف outline |
| pressed | action-pressed یا raised | transform اختیاری حداکثر 1px؛ layout نجنبد |
| selected | selected-bg و indicator سبز + متن | aria-selected/current مطابق control |
| disabled | زمینه raised، text-disabled | native disabled و دلیل بیرون tooltip |
| busy | اندازه و label ثابت، spinner جای icon | دوباره submit نشود؛ aria-busy |
| invalid | border danger و helper مرتبط | aria-invalid/describedby؛ متن ورودی حفظ شود |
| read-only | ظاهر قابل‌خواندن با label فقط‌خواندنی | قابل‌انتخاب/copy؛ disabled تقلید نشود |

هیچ حالت disabled اطلاعات لازم را کم‌رنگ و ناخوانا نکند؛ توضیح علت با text-secondary جدا ارائه می‌شود. loading هیچ ارتفاعی را تغییر ندهد. focus روی icon button aria-label فارسی و tooltip مکمل دارد.

## 9 کتابخانهٔ اجزای پایه

### دکمه

Primary فقط یک اقدام برجسته در ناحیهٔ تصمیم: ارسال، تایید برنامه یا اعمال تغییر. دکمهٔ خطر زمینهٔ danger-bg و متن danger دارد؛ سبز برای حذف نیست. Secondary سطح transparent با border-default؛ Ghost بدون مرز با hover-bg. محتوا label 14/24، gap 8، icon20. busy دکمه width ثابت دارد. لینک بازکنندهٔ خارج اپ با نشان external و disclosure؛ فعال‌بودن اینترنت فرض نشود.

### ورودی textarea select و checkbox

Input md ارتفاع 40، padding12، radius8 و label بالای فیلد با gap6؛ کمک/خطا زیر آن با فاصله6. API key با mask، نمایش/پنهان و copy غیرفعال پیش‌فرض؛ مقدار در نمونه کاتالوگ placeholder است. Select اطلاعات طولانی را wrap یا ellipsis با detail panel می‌دهد. checkbox 18px با hit area32؛ checked سبز با check تیره؛ state mixed برای انتخاب گروه فایل‌ها. switch فقط تنظیم فوری با rollback در failure، نه تصمیم اجرای command.

### badge tooltip menu tabs toast

Badge با padding4×8، font12، dot8 و label خوانا. درحال اجرا pulse کوچک، خطا ثابت و موفق check. Tooltip تاخیر350ms، max280px، padding8×12؛ اطلاعات حیاتی داخل آن محبوس نشود. Menu item حداقل36px، destructive جدا و shortcut monospace. Tabs ارتفاع40، indicator2px و aria-controls. Toast max420px پایین بدنه؛ موفقیت4s و خطای نیازمند اقدام تا dismiss؛ هیچ approval در toast گذرا نیست.

### dialog drawer alert progress

Dialog عرض480 برای تنظیم ساده و720 برای approval؛ padding24، header با عنوان18 و close؛ actionها footer با divider. Escape تصمیم را رد نمی‌کند؛ فقط dialog را می‌بندد و task همچنان waiting می‌ماند. focus trap/restore الزامی است. Drawer inspector 320 و با keyboard resize/close. Alert semantic با icon20، عنوان14 و متن13؛ خطا شامل مرحله و اقدام بازیابی. progress واقعی فقط با مقدار backend؛ loading نامعلوم indeterminate و بدون درصد تخمینی.

## 10 composer قرارداد اصلی محصول

آناتومی از بالا به پایین: context chips انتخاب‌شده → textarea → ردیف ابزار شامل workspace/model/permission و Send یا Stop → خط metadata محیط اجرا. سطح surface، radius12، border-default، padding16 و gap12. textarea min72 و max208px؛ scroll داخلی بعد از max؛ resize دستی خاموش. placeholder «کاری را در این پروژه بسپارید…» ثابت است و وسط تایپ عوض نمی‌شود.

| حالت | Send/Stop | رفتار و متن |
|---|---|---|
| بدون workspace | Send disabled | «ابتدا پوشهٔ پروژه را انتخاب کنید» و دکمه انتخاب |
| مدل تنظیم نشده | Send disabled برای واقعی | «مدل را وصل کنید»؛ demo جدا با برچسب |
| draft خالی | Send disabled | سایر کنترل‌ها فعال |
| آماده | Send سبز 40px | Enter ارسال؛ Shift+Enter خط جدید |
| بررسی و تولید | Stop visible | متن تکمیلی draft حفظ و ارسال به صف steering |
| منتظر تایید | Send پیام توضیحی مجاز | تصمیم اصلی روی کارت approval؛ Enter تایید خطرناک نیست |
| قطع engine/provider | retry در context خطا | متن draft پاک نشود |

در composition فارسی/IME، Enter با isComposing ارسال نمی‌کند. تغییر workspace هنگام task فعال به task جدید با تایید حفظ draft می‌رود؛ ریشهٔ کار جاری عوض نمی‌شود. در حالت focused border ring تنها روی محفظه است؛ textarea مرز دوم ندارد. local/Sandbox و API model با دو chip مستقل نمایش داده می‌شوند؛ هر دو سبز نیستند که به‌اشتباه کل مسیر آفلاین تعبیر شود.

انتخاب مجوز زیر textarea و قبل از Send است. گزینه‌ها: با تایید، مجوز همین کار، خودکار در محیط ایزوله؛ هرکدام subtitle و توضیح مدت/مرز دارند. تغییر گسترده‌تر نیازمند توضیح و ثبت policy revision است. رنگ حالت خودکار icon سبز و subtitle مشخص؛ full-access tooltip هرگز «امن کامل» نمی‌گوید. حالت فقط‌خواندن toggle مستقل است و shell را خاموش نشان می‌دهد.

## 11 گفتگو plan و فعالیت زنده

پیام کاربر max78٪ عرض ستون، زمینه raised و radius8؛ agent پاسخ Markdown در بوم و max100٪ ستون خواندن دارد، نه حباب بزرگ با padding اضافی. فاصله پیام‌ها24؛ فاصله داخل پاسخ16؛ پاراگراف15/28. heading داخل Markdown از h3 شروع می‌شود تا سلسله‌مراتب صفحه مخدوش نشود. جدول در wrapper scroll و code block LTR با copy action و نام زبان است. HTML خام مدل اجرا نمی‌شود.

Tool activity ردیف32–40px با icon16، نام action، path کوتاه و مدت اجرا. خروجی بزرگ جمع‌شده با summary واقعی؛ خطا visible و جزئیات با accordion. plan panel عنوان، revision، وضعیت تایید، steps مرتب و actions دارد. step pending دایرهٔ توخالی؛ in_progress سیگنال؛ completed check؛ blocked pause amber؛ failed danger. متن خط‌خورده برای همهٔ stepهای کامل به خوانایی لطمه می‌زند و پیش‌فرض نیست.

Plan edit حالت draft را نشان می‌دهد؛ Save و Cancel؛ approval قدیمی روی revision جدید معتبر نمایش داده نمی‌شود. re-plan مهم badge «برنامه تغییر کرده» و diff متن قبل/بعد دارد. درصد پیشرفت از تعداد taskها برابر کار واقعی محسوب نمی‌شود؛ «۲ گام از ۵» صحیح‌تر است. انیمیشن stepper فقط نمایش است؛ حرکت جلو مجوز backend ایجاد نمی‌کند.

## 12 درخواست تایید و ایمنی قابل‌فهم

Approval card عرض ستون و border-warning دارد؛ نام ابزار، عمل، دلیل درخواست، مسیر/cwd، command یا diff، مدت و scope. رنگ amber برای انتظار است، نه danger برای هر تایید عادی. action اصلی «تایید این بار»، secondary «ویرایش»، ghost «رد»؛ انتخاب «برای همین کار مجاز» در scope selector جدا با توضیح محدوده.

command block max-height240، copy و نمایش کامل LTR؛ truncation در متن تایید تصمیم‌ساز ممنوع. edit فرم با validation و review تغییر command/cwd قبل از تایید دارد. reject reason اختیاری و حد پیشنهادی1000 حرف؛ رد task را completed نمی‌کند. decision قدیمی یا دوبار ثبت‌شده state conflict و refresh نشان می‌دهد، نه success سبز ساختگی.

اطلاعات دائمی روی card: «این اقدام روی نسخهٔ کاری ایجنت انجام می‌شود» یا «اعمال روی پروژهٔ اصلی». این تفاوت از رنگ استنباط نمی‌شود. GIF approval حداکثر32px کنار title، در صورت reduce-motion poster ثابت و در صورت انتظار طولانی بدون ضربان آزاردهنده.

## 13 diff ویرایش دستی و اعمال

سربرگ review شامل تعداد فایل‌ها، added/deleted lines، وضعیت verifier و دکمه apply انتخاب‌شده. navigation فایل عرض240 تا280، diff باقی فضا؛ unified در عرض کم. شمارهٔ خطوط بدون تبدیل فارسی، font13/22، gutter min48px، هر ستون side-by-side حداقل360. whitespace و file path copy قابل‌کنترل‌اند. long line wrap انتخاب کاربر با حفظ کارایی است.

file stateها: added با +، deleted با −، modified با قلم، conflict با !، binary با B، unsupported با توضیح. approve file checkbox با selected count؛ bulk apply فقط پس از مرور summary و hash check. partial hunk apply در v1 ندارد. manual edit روی working copy badge «ویرایش دستی» و verifier stale می‌کند؛ timestamp و نسخه روشن‌اند.

Apply button label «اعمال ۳ فایل روی پروژهٔ اصلی» و disclosure «بررسی‌ها متعلق به کدام نسخه‌اند» دارد. پس از apply نتیجهٔ فایل‌به‌فایل و restore action. conflict dialog مسیر، before/current/working و انتخاب بازبینی دارد؛ تایید قبلی روی فایل تغییرکرده قابل‌استفاده نیست. Undo نباید معنای Git reset کل پروژه بدهد.

## 14 terminal verifier و دو repair

خروجی command panel با header نام shell/cwd، status، مدت و exit code، بدنه scroll و footer cap/truncated. نگه‌داری کامل خروجی محدود است و badge «بخشی از خروجی نمایش داده می‌شود» لازم است. never use green line streaming به‌عنوان پاس‌شدن تست. کنترل Stop نزدیک command و Stop کلی task همگام‌اند.

Verification panel ردیف‌های format/lint/test/build با command، consent، baseline result، result جدید و timestamp. حالت‌ها passed، failed، skipped، not configured، stopped و timed out متمایزند. «کل checks موفق» فقط وقتی همهٔ required checkهای نسخهٔ جاری passed باشند. checkهای اختیاری در summary جدا هستند.

دو repair به‌صورت «اصلاح ۱ از ۲» و «اصلاح ۲ از ۲» نشان داده می‌شوند؛ countdown یا progress ساختگی ندارد. پس از شکست دوم، card تصمیم ثابت با گزینهٔ افزودن یک تلاش، ویرایش درخواست، بازبینی خروجی و پایان کار است. GIF correcting در طول تلاش واقعی فعال است، نه هنگام انتظار انسان. pass تست معادل apply نیست و موفقیت GIF فقط متن «بررسی‌ها موفق بودند» دارد.

## 15 Skills تنظیمات و تاریخچه

Skill list: نام، description دوخطی، scope project/personal/bundled، hash کوتاه، trust و enabled. invalid source با متن خطا و action بازکردن محل؛ disabled switch نیازمند consent نیست ولی enable محتوای ناشناخته preview/تایید می‌خواهد. directory path با bdi و مسیر کامل copy؛ شخصی/پروژه‌ای دو رنگ برند جدا نمی‌گیرند. scriptها در details با badge «نیازمند مجوز اجرا». reload وسط task با پیام «در کار بعدی استفاده می‌شود» مگر انتخاب صریح re-pin.

Model settings: protocol selector، base URL، model id، secret، probe و error. probe busy و اطلاعات tool calling/stream/usage؛ نام provider به معنی tested نیست. local model endpoint و online provider در badge نوع اتصال تفکیک شوند. Settings ذخیره/خطا inline و بدون ازبین‌رفتن draft؛ API key نه در toast و نه در HTML preview نمایش داده نشود.

History row ارتفاع64، نام task و workspace، status icon، آخرین زمان و menu. search/filter افقی، empty «هنوز کاری شروع نشده» و action جدید. task closed/paused/awaiting_decision badges جدا؛ hover menu تنها مسیر دسترسی نیست. حذف history توضیح می‌دهد فایل‌های اصلی حذف نمی‌شوند.

## 16 onboarding local و خطاهای شروع

چهار گام قابل‌برگشت: معرفی محل داده و انتخاب demo/واقعی → انتخاب پروژه → مدل → وضعیت محیط ایزوله. step index نمایش setup است و از backend permission مستقل. مدل API با متن «بخش لازم از کد به سرویس انتخابی شما ارسال می‌شود»؛ بدون حساب محصول یا cloud login اضافی.

Preflight آیتمی است: engine، OS، WSL/Docker، Linux image و دیسک؛ هر ردیف check/pending/error و اقدام مرتبط. Docker absent را engine offline نشان ندهید. بدون sandbox: read-only و demo در دسترس؛ اجرای command غیرفعال و setup guidance. دانلود image با اندازه/نیاز اینترنت و تایید؛ دکمهٔ نصب غیرفعال نباید وانمود کند خود اپ قبلا نصب کرده است.

Close با task فعال: ماندن، توقف و خروج؛ گزینهٔ «لغو خروج» تکرار همان ماندن محسوب می‌شود و در UI نهایی تنها دو انتخاب روشن حفظ شود. force exit مسیر advanced با recovery warning است. recovery صفحه status action unknown، آخرین event و انتخاب بازبینی/پایان؛ دکمه «ادامه خودکار همه» ندارد.

## 17 نشان Bridge و کیت هویت

نشان منتخب حرف H از دو ریل ثابت و اتصال پله‌ای ساخته می‌شود. grid نماد256×256؛ ریل40unit و گره/پله32unit؛ bbox40..216 و مرکز128. توازن دو ریل حفظ می‌شود. master اصلی SVG path با fill و بدون فونت، raster/filter/گرادیان است. wordmark سفارشی outline با glyphهای شبکه‌ای ONBOARD / HARNESS ساخته شده؛ به فونت نصب‌شده وابسته نیست.

نسخه‌ها: brand سبز، black، white، accent-mono، horizontal، stacked، wordmark، small و app icon. clear-space حداقل40unit از علامت256؛ در header نشان24 با فاصله8 تا نام. حداقل نمایش نماد اصلی24px؛ favicon16 از نسخه small با grid مستقل. app icon256 با container radius48 و لوگوی داخلی75٪؛ Windows icon می‌تواند از PNG/ICO تولیدشده استفاده کند. فایل favicon.ico شامل16/32/48/256 است؛ icon installer پروژه در این نوبت جایگزین نشده است.

رنگ سبز RGB(74,222,128)؛ تبدیل فرمولی CMYK حدود67/0/42/13 درصد است و soft proof چاپ نیست. Pantone تعیین نشده چون محصول دیجیتال است؛ تولید چاپی به proof نیاز دارد. نشان روی عکس/gradient با container تیرهٔ ثابت، بدون glow در master. master ثابت نچرخد و کشیده نشود؛ تغییر هندسه در انیمیشن‌های وضعیت تأییدشدهٔ کاربر مجاز است. outline دلخواه یا تایپ‌نشان فونتی جانشین wordmark نشود. نشان H آیکون success یا تضمین امنیت نیست؛ status badge کنارش معنی را می‌دهد.

مطالعهٔ کتابخانه و دو audit هندسه انجام شده‌اند؛ این کار بررسی trademark یا تضمین تمایز حقوقی نیست. در اندازه16، حرف پله‌ای به small companion متکی است؛ متن کوچک در favicon حذف می‌شود.

## 18 پنج GIF و منطق حالت

فایل‌ها در motion/ با master size256، نمایش معمول32–64 و نمایش onboarding96 هستند. طبق بازخورد نهایی کاربر، آماده‌سازی قبلی حفظ شده و چهار حرکت دیگر با تغییر خود نشان بازطراحی شده‌اند. پس‌زمینهٔ GIF مات #010A04 است؛ شفافیت نیمه‌شفاف GIF ادعا نمی‌شود. برای surfaceهای متفاوت از SVG زنده یا poster داخل قاب هم‌رنگ استفاده شود.

| GIF | trigger | حرکت | مدت/fps | پایان |
|---|---|---|---|---|
| loading.gif | آماده‌سازی مدل/runtime | سه نقطه و نفس کم‌دامنهٔ نشان | 1600ms/20 | loop تا event بعدی |
| executing.gif | tool_running | چرخش کامل سه‌بعدی H | 1200ms/20 | loop؛ توقف با پایان ابزار |
| approval.gif | awaiting_human | باز شدن اتصال و تبدیل به خطوط مکث | 2400ms/20 | loop آرام؛ بعد30s تصویر ثابت پیشنهادی |
| correcting.gif | repair_started | قطعات H با تغییر زاویه جدا و دوباره متصل می‌شوند | 1800ms/20 | loop فقط حین repair |
| success.gif | required_checks_passed | تبدیل خود H به تیک بزرگ | 1000ms/20 + نگه‌داری frame آخر | one-shot، بدون جشن دائمی |

loop exporter: صفر برای repeat دائمی؛ success یک پخش/بدون loop تکرارشونده. زمان نگه‌داری frame آخر1500ms برای خواندن است و مدت sting1000ms جدا ثبت شده. manifest دقیق فریم‌ها و bytes در motion/manifest.json آمده. نام «موفقیت» فقط موفقیت بررسی‌هاست؛ completed_with_failures یا not_verified از آن استفاده نمی‌کند. خطا و توقف با poster ثابت و icon خطر/paused معرفی می‌شوند؛ پنج GIF با افزودن ششمین فایل جایگزین خواسته نشده‌اند.

هر وضعیت aria-live=polite متن مستقل دارد؛ تصویر decorative با alt خالی وقتی label مجاور هست. reduce-motion و تنظیم «کاهش حرکت» اپ تصویر poster همان state را جایگزین GIF می‌کنند؛ CSS نمی‌تواند GIF را pause کند. GIF از DOM حذف یا src به poster عوض می‌شود. صفحهٔ پس‌زمینه/hidden همه loopها و WebGL را متوقف کند؛ در وضعیت active فقط یک GIF برند هم‌زمان لازم است.

## 19 سیستم حرکت عمومی

مدت‌ها: micro100، control150، panel200، enter240، settle320ms. easing عمومی cubic-bezier(.2,0,0,1)، enter cubic-bezier(.16,1,.3,1). فاصله ورود6px؛ drawer از inline-end تنها مسافت موردنیاز و بدون پرتاب 100px محتوا. stagger حداکثر40ms و سقف کل240ms. transition:all ممنوع؛ opacity/transform/color صریح.

hover جابه‌جایی محتوا ندارد؛ card lift صرفا خانه/onboarding حداکثر2px. متن فارسی split به کاراکتر برای animation نمی‌شود تا اتصال حروف نشکند؛ reveal روی بلوک کامل. پاسخ streaming per-token animation ندارد؛ متن تایپ‌شده قبلی دوباره blur/reveal نمی‌شود. tooltip100، popover150، dialog200، row reveal150، collapse panel200ms. chart/خط‌زمان بدون پیشرفت واقعی animate percent نمی‌کند.

## 20 React Bits انتخاب و تطبیق

منبع با commit `e12c22192ac7b4b452c5e2feb9b586d74765d696` بررسی شده است. نسخهٔ زندهٔ registry تغییر می‌کند؛ APIهای این سند مربوط به همان snapshot هستند. چهار مؤلفه در کاتالوگ با کد upstream اجرا می‌شوند: Aurora، ShinyText، SpotlightCard و Stepper؛ آیکون‌های Stepper با SVG محلی جایگزین شده‌اند. AnimatedContent انتخاب پنجم در recipe است و در کاتالوگ با معادل CSS مستقل معرفی می‌شود؛ اجرای upstream آن در کاتالوگ ادعا نمی‌شود.

| مؤلفه | کاربرد منتخب | تنظیم رنگ/حرکت | fallback |
|---|---|---|---|
| Aurora | فقط بخش خوشامد/hero سایت | stops #052E16/#10B981/#4ADE80، opacity .28، speed .18، height .65 | gradient ثابت |
| ShinyText | label فعالیت کوتاه | color #B8C2BB، shineColor #4ADE80، speed3، delay1، glow0 | متن ثابت |
| SpotlightCard | کارت انتخاب پروژه/Skill | spotlight #4ADE80، intensity .08، borderGlow .12، ambient false | border معمولی focus-visible |
| Stepper | onboarding و نمایش مرحله | accentColor #4ADE80، theme dark، radius8، transition fade | مراحل ثابت و current text |
| AnimatedContent | ورود panel/کارت نتیجه | distance6، duration .2، scale1، blur0، mount/once | opacity1 بدون transform |

در task/diff/approval Aurora و spotlight دائمی استفاده نشوند؛ احتمال پرت‌کردن توجه و مصرف GPU دارند. Stepper برای step arbitrary مدل clickable نیست؛ کنترل رسیدن به مرحله از state backend می‌آید. custom SVG جایگزین Hugeicons وابستگی اضافی و icon family دوم را حذف می‌کند؛ attribution اصلی حفظ شده است. همهٔ script/styleها local bundle شده‌اند؛ اجرا نیاز به CDN یا فراخوانی سایت React Bits ندارد. shader برخلاف تصویر screenshot ممکن است روی GPU ضعیف دردسترس نباشد و fallback باید باقی بماند.

فایل REACT-BITS.fa.md لینک‌ها، recipe دقیق و ملاحظات license را دارد. منبع فعلی React Bits MIT + Commons Clause است، نه MIT خالص. استفاده در محصول با حفظ notices و محدودیت بازتوزیع component/tool pack باید بررسی شود؛ این بسته آن‌ها را در کاتالوگ محصول integrate می‌کند و code upstream جدا برای فروش/بازتوزیع component pack تحویل نمی‌دهد.

## 21 دسترس‌پذیری و کارایی حرکت

keyboard همه کنترل‌ها، skip link به transcript، focus restore modal، aria-live محدود به event مهم و close کار با Escape بدون تایید ناخواسته. outline حداقل2px، contrast متن معمول4.5 و نشانه کنترل3؛ opacity روی کل card نباید متن لازم را ضعیف کند. animated progress percentage screen reader را هر فریم اسپم نمی‌کند. توصیف step «گام جاری ۲ از ۴» است و label با هر token تغییر نمی‌کند.

budget طراحی: حداکثر یک canvas WebGL در viewport و صفر در صفحهٔ task فعال؛ DPR حداکثر1.5 در hero، pause hidden و offscreen، بدون cursor trail/sitewide noise. مصرف واقعی CPU/GPU/FPS روی دستگاه مرجع هنوز benchmark نشده است. GIFها زیر200KB هدف هرکدام؛ bytes واقعی manifest مرجع است. layout هیچ متن اساسی را تا load animation مخفی نکند؛ JS off برای محتوای کاتالوگ و CSS fallback readable بماند.

## 22 متن رابط و خطا

لحن ساده، فارسی و عملی؛ از «عملیات ناموفق بود» بدون گام بعدی پرهیز شود. نمونه‌ها: «برنامه را بررسی کنید»، «این فرمان نیاز به تأیید دارد»، «نسخهٔ اصلی این فایل تغییر کرده است»، «دو بار اصلاح انجام شد؛ ادامه بدهم؟»، «Docker آماده نیست؛ تنظیم محیط را باز کنید». «هوش مصنوعی همه‌چیز را تضمین می‌کند» یا «امنیت کامل» متن محصول نیست.

date/time در UI محلی با timezone کاربر و نمایش relative مناسب؛ logs فنی UTC و digits لاتین. local badge «روی این دستگاه»؛ provider badge «مدل API»؛ sandbox badge «محیط ایزوله»؛ host fallback اگر روزی عرضه شد amber «اجرای مستقیم روی Windows». model و mode در همه taskها قابل‌دیدن و در حالت waiting مبهم نمی‌مانند.

## 23 اتصال به کد و migration بصری

tokens.css ابتدا در scope جدید theme کدنویسی import شود؛ app فعلی به‌طور ناگهانی با replace global recolor نشود. primitive، semantic و component aliases در مرحلهٔ integration با متغیرهای فعلی globals.css map شوند. Phosphor family موجود حفظ می‌شود؛ بعضی glyphهای نمونهٔ کاتالوگ فقط specimen هستند. تغییر logo.png، icon.ico، titlebar chrome و color tokens یک integration task مستقل دارد؛ فایل‌های تولیدشده هنوز در binary برنامه deploy نشده‌اند.

recipe components در کاتالوگ برای بررسی بصری‌اند؛ فایل‌های upstream از commit pinned build شده‌اند. برای product integration نسخهٔ دقیق dependencyها و تغییر CSP برای WebGL/data URI فقط پس از بررسی فعلی انجام شود. font جدید از CDN نصب نشود؛ Vazirmatn فعلی کافی است و Mono/Inter فقط در صورت نیاز bundle شوند.

## 24 کنترل نهایی و حدود تحویل

- توکن JSON و CSS یک generator دارند؛ contrast جفت‌های اعلام‌شده محاسبه می‌شود.
- لوگو v1/v2، audit، اندازه‌های16/32/64 و mono/reverse بررسی می‌شوند؛ آزمون انسانی trademark انجام نشده است.
- GIFها decoded frame count/duration/loop بررسی و contact sheet چند frame دیده می‌شود.
- کاتالوگ در desktop و عرض narrow، reduced-motion و اجرای آفلاین local بررسی می‌شود؛ این بررسی معادل آزمون اپ واقعی نیست.
- screen reader کامل، نمایش OS scaling روی Windows و عملکرد GPU چنددستگاهی در integration آینده باقی‌اند و نباید «تاییدشده» معرفی شوند.

اطلاعات اجرای کنترل‌ها در checks/validation.json و screenshotهای checks/ نگه‌داری می‌شود؛ README مسیر بازکردن reference و ابزار بازتولید را توضیح می‌دهد. مرجع اصلی اجرا tokens.json و این سند است؛ index.html نمونهٔ تعاملی تصمیم‌هاست، نه جایگزین قراردادهای هارنس.


### بازنگری حرکت — نسخهٔ دوم

طبق بازخورد کاربر، GIF آماده‌سازی بدون تغییر حفظ شد. چهار حرکت دیگر با `bridge-motion-v2.cjs` بازطراحی شدند: اجرا با یک چرخش کامل سه‌بعدی، انتظار تأیید با باز شدن اتصال و تبدیل به دو خط مکث، اصلاح با جداشدن و اتصال قطعات و موفقیت با تبدیل H به تیک. این قرارداد جایگزین توضیحات نسخهٔ نخست دربارهٔ ثابت ماندن هندسه و نشانک‌های بیرونی است. نسخهٔ نخست چهار حرکت در `motion/archive-v1` باقی است. پوستر انتظار همچنان H است و متن وضعیت کنار آن ضروری است.


## مرجع چیدمان و تعامل محصول

سند `PRODUCT-DESIGN.fa.md` نگاشت نیازمندی‌ها به ۱۵ صفحه و زیرنما، قواعد تعامل، stateها، استفاده از توکن‌ها و معیارهای پذیرش را مشخص می‌کند. `product-design-atlas.html` اطلس تصویری همین قرارداد است؛ نمونهٔ اتصال به engine نیست.
