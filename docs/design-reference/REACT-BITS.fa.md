# انتخاب و تطبیق React Bits

snapshot بررسی‌شده: e12c22192ac7b4b452c5e2feb9b586d74765d696. سایت نمونهٔ live و source branch جاری می‌توانند بعداً تغییر کنند. این انتخاب‌ها برای محصول تیرهٔ local و رنگ‌های فایل Vertex تنظیم شده‌اند؛ نام componentها به‌تنهایی به معنی استفادهٔ مناسب در همهٔ صفحه‌ها نیست.

## اجرا در کاتالوگ

چهار مؤلفهٔ واقعی upstream در کاتالوگ محلی bundle شده‌اند. فایل‌های TSX/CSS بررسی‌شده به‌صورت scratch زیر `.data/onboard-design-reactbits` نگه‌داری می‌شوند؛ خروجی تحویل، application-specific bundle است و component pack نیست. هیچ npm install، CDN runtime یا تغییر dependencies اپ اصلی انجام نشده است. Stepper دو import آیکون Hugeicons را با SVGهای محلی جایگزین می‌کند؛ API و باقی renderer از upstream است.

### Aurora

پس‌زمینهٔ WebGL فقط در خانه/onboarding یا hero سایت؛ نه diff یا approval. recipe:

```tsx
<Aurora colorStops={['#052E16', '#10B981', '#4ADE80']}
  opacity={0.28} speed={0.18} amplitude={0.65} height={0.65}
  glow={0.2} mouseInteraction={false} intro={false} dpr={1} />
```

در reduced motion/hidden canvas mount نمی‌شود؛ fallback CSS gradient. pause offscreen باید در integration محصول اضافه و benchmark شود. [نمایش رسمی](https://reactbits.dev/backgrounds/aurora) · [source pinned](https://github.com/DavidHDev/react-bits/blob/e12c22192ac7b4b452c5e2feb9b586d74765d696/src/ts-default/Backgrounds/Aurora/Aurora.tsx).

### ShinyText

عبارت کوتاه درحال‌اجرا، با اتصال حروف فارسی حفظ‌شده؛ متن روی حروف تکه‌تکه نمی‌شود.

```tsx
<ShinyText text="در حال بررسی فایل‌ها…" color="#B8C2BB"
  shineColor="#4ADE80" speed={3} delay={1} glow={0}
  disabled={reducedMotion || !isRunning || hidden} />
```

فقط هنگام event واقعی و یک‌بار در viewport؛ متن خودش status را بیان می‌کند. [صفحهٔ رسمی](https://reactbits.dev/text-animations/shiny-text) · [source pinned](https://github.com/DavidHDev/react-bits/blob/e12c22192ac7b4b452c5e2feb9b586d74765d696/src/ts-default/TextAnimations/ShinyText/ShinyText.tsx).

### SpotlightCard

تنها کارت انتخاب پروژه/Skill در خانه؛ focus ring مستقل و border 3:1 حفظ شود.

```tsx
<SpotlightCard spotlightColor="#4ADE80" intensity={0.08}
  borderGlow={0.12} ambient={false} flare={false} grain={0}
  theme="dark" style={{ background:'#191C21', borderColor:'#58705F', borderRadius:8 }}>
  {children}
</SpotlightCard>
```

نسخهٔ reduced مقدار intensity/borderGlow صفر و وضعیت hover را با border عادی نمایش می‌دهد. [source pinned](https://github.com/DavidHDev/react-bits/blob/e12c22192ac7b4b452c5e2feb9b586d74765d696/src/ts-default/Components/SpotlightCard/SpotlightCard.tsx).

### Stepper

برای setup؛ در plan زنده کنترل مرحله از backend می‌آید، نه کلیک خودکار کاربر.

```tsx
<Stepper step={step} onStepChange={setStep} theme="dark"
  accentColor="#4ADE80" frame={false} radius={8} width="100%"
  transition={reducedMotion ? 'none' : 'fade'}
  backButtonText="قبلی" nextButtonText="ادامه" completeButtonText="پایان">
  <Step title="پروژه">{project}</Step>
  <Step title="مدل">{model}</Step>
  <Step title="محیط">{runtime}</Step>
</Stepper>
```

Source فعلی icon dependency اضافی دارد؛ کاتالوگ همان آیکون‌ها را با SVG ساده جایگزین می‌کند. RTL و متن فارسی در reference دیده می‌شوند؛ آزمون screen reader کامل انجام نشده است. [صفحهٔ رسمی](https://reactbits.dev/components/stepper) · [source pinned](https://github.com/DavidHDev/react-bits/blob/e12c22192ac7b4b452c5e2feb9b586d74765d696/src/ts-default/Components/Stepper/Stepper.tsx).

### AnimatedContent انتخاب مکمل

recipe پیشنهادی برای panel و نتیجهٔ تازه؛ وابستگی GSAP دارد و به کاتالوگ این تحویل اضافه نشده است. کاتالوگ با دکمهٔ بازپخش معادل مستقل CSS opacity/translateY را نشان می‌دهد و آن را upstream معرفی نمی‌کند.

```tsx
<AnimatedContent distance={6} duration={0.2} scale={1} blur={0}
  trigger="mount" once={true} animateOpacity={true}>
  {resultPanel}
</AnimatedContent>
```

فعال‌بودن reduced motion و behavior container scroller پیش از integration بررسی شود. [source بررسی‌شده](https://github.com/DavidHDev/react-bits/blob/e12c22192ac7b4b452c5e2feb9b586d74765d696/src/ts-default/Animations/AnimatedContent/AnimatedContent.tsx).

## دستورهای افزودن در مرحلهٔ integration

```text
npx shadcn@latest add @react-bits/Aurora-TS-CSS
npx shadcn@latest add @react-bits/ShinyText-TS-CSS
npx shadcn@latest add @react-bits/SpotlightCard-TS-CSS
npx shadcn@latest add @react-bits/Stepper-TS-CSS
```

این دستورها راهنمای registry هستند و در این تحویل اجرا نشده‌اند. latest نسخهٔ commit بررسی‌شده را تضمین نمی‌کند؛ قبل از product integration source باید pin و diff شود. نصب component صرفاً برای رنگ‌بندی یک border کوچک لازم نیست؛ اگر bundle budget با نیاز محصول نمی‌خواند معادل CSS ساده با attribution الهام جدا ارائه شود.

## مجوز و توزیع

مجوز source بررسی‌شده **MIT + Commons Clause** است. استفاده در محصول و نگه‌داری notices باید مطابق متن license باشد؛ توزیع خود componentها به‌شکل component pack یا فروش جداگانه محدود است. این بسته یک reference app و خروجی خلاقانهٔ برند است؛ فایل assets/REACT-BITS-LICENSE.md متن اصلی را حفظ می‌کند. code اصلی پروژهٔ ما AGPL اعلام شده و ادغام نهایی در سورس عمومی محصول نیازمند بررسی سازگاری این شروط است؛ سازگاری حقوقی قطعی ادعا نمی‌شود. برای جلوگیری از مخلوط‌شدن، build کاتالوگ فعلاً جدا از app است. [مجوز رسمی](https://github.com/DavidHDev/react-bits/blob/e12c22192ac7b4b452c5e2feb9b586d74765d696/LICENSE.md).
