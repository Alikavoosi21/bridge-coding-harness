// Pure setup rules shared by the wizard and the settings screen.
//
// These functions make no network calls and hold no React state, so the
// resumable-step, completion and capability rules can be tested directly. The
// backend enforces the same rules; this module only decides what to show and
// when a button may be pressed.

export type SetupStep = 1 | 2 | 3 | 4;

export type SetupPrerequisites = {
  workspaceOpen: boolean;
  modelConfigured: boolean;
  modelHasKey: boolean;
};

export type CapabilityInput = {
  base_url: string;
  has_key: boolean;
  capabilities?: {
    tools?: boolean | null;
    error_code?: string | null;
    error_message?: string | null;
    checked_at?: number | null;
  } | null;
};

export type CapabilityView = {
  tone: 'success' | 'warning' | 'danger' | 'neutral';
  label: string;
  detail: string;
  canWrite: boolean;
};

export const DISCLOSURE_KEYS = ['model_api', 'sandbox_network', 'demo_state', 'read_only'] as const;

export type DisclosureKey = (typeof DISCLOSURE_KEYS)[number];

export const disclosureText: Record<DisclosureKey, { title: string; body: string }> = {
  model_api: {
    title: 'گفتگو به سرویس مدل می‌رود',
    body: 'هر پیام شما، و بخشی از فایل‌های پروژه که برای پاسخ لازم است، به همان آدرس مدلی که انتخاب کرده‌اید فرستاده می‌شود. این اتصال از طرف برنامه به اینترنت باز می‌شود؛ کلید API فقط از مخزن امن سیستم‌عامل خوانده می‌شود و در رابط یا گزارش‌ها نمایش داده نمی‌شود.',
  },
  sandbox_network: {
    title: 'شبکهٔ sandbox بسته است',
    body: 'فرمان‌ها داخل container و با شبکهٔ قطع (`--network none`) اجرا می‌شوند. sandbox به اینترنت، شبکهٔ محلی یا Docker socket دسترسی ندارد. اگر کاری به شبکه نیاز دارد، در این نسخه اجرا نمی‌شود؛ به‌جای آن، خود مدل می‌تواند از سرویس شما پاسخ بگیرد.',
  },
  demo_state: {
    title: 'مدل نمایشی، بدون تماس بیرونی',
    body: 'مدل نمایشی (`demo`) هیچ کلیدی نمی‌خواهد و هیچ درخواستی به بیرون نمی‌فرستد؛ پاسخ‌هایش از پیش نوشته شده‌اند تا روند کار را ببینید. برای کار واقعی، مدل خودتان را تعریف کنید.',
  },
  read_only: {
    title: 'بدون sandbox فقط خواندن',
    body: 'تا زمانی که Docker و image آن آماده نباشد، یا مدل انتخابی توانایی فراخوانی ابزار را تأیید نکرده باشد، کارها فقط می‌خوانند و توضیح می‌دهند و هیچ فایلی تغییر نمی‌کند. برنامه هیچ shell جایگزینی روی سیستم شما اجرا نمی‌کند.',
  },
};

const failures: Record<string, { label: string; hint: string }> = {
  provider_auth: {
    label: 'کلید پذیرفته نشد',
    hint: 'سرویس پاسخ داد اما کلید را رد کرد. کلید API و دسترسی آن را بررسی کنید.',
  },
  provider_unreachable: {
    label: 'سرویس در دسترس نیست',
    hint: 'هیچ پاسخی از آدرس مدل نرسید. نشانی، اتصال شبکه و روشن بودن سرویس محلی را بررسی کنید.',
  },
  model_not_found: {
    label: 'نام مدل پیدا نشد',
    hint: 'سرویس پاسخ داد اما این نام مدل را نمی‌شناسد. نام دقیق مدل را در سرویس ببینید.',
  },
  tools_unsupported: {
    label: 'ابزارها پشتیبانی نمی‌شود',
    hint: 'این مدل یا سرویس فراخوانی ابزار را نمی‌پذیرد. با چنین مدلی کار تغییردهنده ممکن نیست.',
  },
  tools_not_observed: {
    label: 'ابزار فراخوانی نشد',
    hint: 'سرویس پاسخ داد اما مدل ابزار بررسی را صدا نزد. ممکن است این مدل ابزارها را پشتیبانی نکند.',
  },
  provider_error: {
    label: 'خطای سرویس',
    hint: 'سرویس پاسخ داد اما درخواست بررسی را نپذیرفت. پیام سرویس را ببینید.',
  },
};

export function providerFailure(code: string | null | undefined): { label: string; hint: string } {
  return (code && failures[code]) || { label: 'بررسی ممکن نشد', hint: 'نتیجهٔ بررسی روشن نیست. دوباره تلاش کنید.' };
}

export function isDemo(model: { base_url: string }): boolean {
  return model.base_url.startsWith('demo://');
}

/** What the UI may claim about a model's ability to change files. */
export function capabilityOf(model: CapabilityInput): CapabilityView {
  if (isDemo(model)) {
    return {
      tone: 'success',
      label: 'مدل نمایشی',
      detail: 'بدون کلید و بدون تماس با سرویس؛ برای دیدن روند کار.',
      canWrite: true,
    };
  }
  if (!model.has_key) {
    return {
      tone: 'warning',
      label: 'کلید ندارد',
      detail: 'بدون کلید، نه گفتگو ممکن است و نه تغییر فایل.',
      canWrite: false,
    };
  }
  const capabilities = model.capabilities;
  if (!capabilities || capabilities.tools === null || capabilities.tools === undefined) {
    return {
      tone: 'warning',
      label: 'بررسی نشده',
      detail: 'برای اجازهٔ تغییر فایل، توانایی ابزار این مدل را بررسی کنید.',
      canWrite: false,
    };
  }
  if (capabilities.tools === true) {
    return {
      tone: 'success',
      label: 'ابزارها تأیید شد',
      detail: 'این مدل در بررسی واقعی، ابزار را فراخوانی کرد.',
      canWrite: true,
    };
  }
  const failure = providerFailure(capabilities.error_code);
  return {
    tone: 'danger',
    label: failure.label,
    detail: failure.hint,
    canWrite: false,
  };
}

export function clampStep(value: number): SetupStep {
  if (value <= 1) return 1;
  if (value >= 4) return 4;
  return value === 2 ? 2 : 3;
}

/**
 * Where an interrupted setup continues. A step whose prerequisite disappeared
 * is not resumed: a missing folder returns to step 1, a model without a key to
 * step 2. Once both exist, the stored step is honoured (at least step 3,
 * because steps 1–2 are done).
 */
export function resumeStep(storedStep: number, state: SetupPrerequisites): SetupStep {
  if (!state.workspaceOpen) return 1;
  if (!state.modelConfigured || !state.modelHasKey) return 2;
  const stored = clampStep(storedStep);
  return stored <= 2 ? 3 : stored;
}

export type MissingPrerequisite = 'workspace' | 'model' | 'provider_key';

/** The same order and meaning as the backend's `setup_incomplete` details. */
export function missingForCompletion(state: SetupPrerequisites): MissingPrerequisite[] {
  const missing: MissingPrerequisite[] = [];
  if (!state.workspaceOpen) missing.push('workspace');
  if (!state.modelConfigured) missing.push('model');
  else if (!state.modelHasKey) missing.push('provider_key');
  return missing;
}

export function canComplete(state: SetupPrerequisites): boolean {
  return missingForCompletion(state).length === 0;
}

export const missingLabel: Record<MissingPrerequisite, string> = {
  workspace: 'یک پوشهٔ پروژه انتخاب نشده است.',
  model: 'هیچ مدلی انتخاب نشده است.',
  provider_key: 'مدل انتخابی کلید API ندارد.',
};

/** Preselect saved commands that the current preflight still suggests; otherwise all of them. */
export function initialCommandSelection(suggested: string[], saved?: string[] | null): string[] {
  if (!saved || saved.length === 0) return [...suggested];
  const allowed = new Set(suggested);
  return saved.filter((command) => allowed.has(command));
}

export const stepTitles: Record<SetupStep, { title: string; lead: string }> = {
  1: { title: 'مخزن کدت را باز کن', lead: 'پوشهٔ پروژه را انتخاب کن تا ساختار و فرمان‌هایش شناسایی شوند. بعداً می‌توانی بین پروژه‌ها جابه‌جا شوی.' },
  2: { title: 'مدل کدنویسی را وصل کن', lead: 'نشانی سرویس، نام مدل و کلید API را وارد کن. بعد از ذخیره، توانایی ابزار را بررسی و مدل را پیش‌فرض کن.' },
  3: { title: 'محیط اجرا و تست را آماده کن', lead: 'آمادگی Docker و فرمان‌های واقعی تست و build پروژه را بررسی کن؛ در این گام هیچ فرمان پروژه‌ای اجرا نمی‌شود.' },
  4: { title: 'پروژه، مدل و دسترسی‌ها را مرور کن', lead: 'نحوهٔ استفاده از داده را مرور کن و وارد میز کار شو. سطح اختیار هر تسک را کنار کادر درخواست انتخاب می‌کنی.' },
};
