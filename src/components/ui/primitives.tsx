'use client';

import { cva, type VariantProps } from 'class-variance-authority';
import { Progress as ProgressPrimitive, Switch as SwitchPrimitive, Tooltip as TooltipPrimitive } from 'radix-ui';
import * as React from 'react';

import { cn } from '@/lib/utils';

/* ───────────── Badge ───────────── */

const badgeVariants = cva(
  'inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full px-2 text-xs leading-5 font-medium whitespace-nowrap [&_svg]:size-3.5',
  {
    variants: {
      tone: {
        neutral: 'bg-raised text-muted-foreground',
        outline: 'border border-border text-muted-foreground',
        primary: 'bg-primary-soft text-primary',
        success: 'bg-success-soft text-success',
        warning: 'bg-warning-soft text-warning',
        danger: 'bg-danger-soft text-danger',
        info: 'bg-info-soft text-info',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
);

export type Tone = NonNullable<VariantProps<typeof badgeVariants>['tone']>;

export function Badge({ className, tone, ...props }: React.ComponentProps<'span'> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

/* ───────────── Card ───────────── */

export function Card({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('bg-surface text-card-foreground rounded-lg border', className)} {...props} />;
}

/** The one panel pattern: divided header (title, count, description, action) over a body. */
export function SectionCard({
  title,
  count,
  description,
  action,
  flush = false,
  className,
  bodyClassName,
  children,
}: {
  title?: React.ReactNode;
  count?: number;
  description?: React.ReactNode;
  action?: React.ReactNode;
  flush?: boolean;
  className?: string;
  bodyClassName?: string;
  children?: React.ReactNode;
}) {
  return (
    <Card className={cn('overflow-hidden', className)}>
      {(title || action) && (
        <div className="border-border flex items-center justify-between gap-3 border-b px-5 py-3.5">
          {/* Title and its note share one line; nothing stacks under a heading. */}
          <div className="flex min-w-0 items-baseline gap-2.5">
            <h2 className="shrink-0 text-sm font-semibold">
              {title}
              {count != null && <span className="text-faint ms-1.5 font-normal">{count.toLocaleString('fa-IR')}</span>}
            </h2>
            {description && <span className="text-muted-foreground truncate text-xs">{description}</span>}
          </div>
          {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
        </div>
      )}
      {flush ? children : <div className={cn('p-5', bodyClassName)}>{children}</div>}
    </Card>
  );
}

/* ───────────── Inputs ───────────── */

export function Input({ className, ...props }: React.ComponentProps<'input'>) {
  return (
    <input
      className={cn(
        'border-input bg-surface placeholder:text-muted-foreground focus-visible:border-ring disabled:bg-raised h-10 w-full rounded-lg border px-3 text-sm text-foreground transition-colors disabled:cursor-not-allowed disabled:text-[var(--text-disabled)]',
        className,
      )}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: React.ComponentProps<'textarea'>) {
  return (
    <textarea
      className={cn(
        'border-input bg-surface placeholder:text-muted-foreground focus-visible:border-ring disabled:bg-raised scrollbar-minimal max-h-52 min-h-[72px] w-full resize-none rounded-lg border px-3 py-3 text-[15px] leading-7 text-foreground transition-colors disabled:cursor-not-allowed disabled:text-[var(--text-disabled)]',
        className,
      )}
      {...props}
    />
  );
}

export function Label({ className, ...props }: React.ComponentProps<'label'>) {
  return <label className={cn('text-muted-foreground mb-1.5 block text-xs font-semibold', className)} {...props} />;
}

export function Kbd({ className, ...props }: React.ComponentProps<'kbd'>) {
  return (
    <kbd
      className={cn(
        'bg-raised text-muted-foreground border-border inline-flex h-5 min-w-5 items-center justify-center rounded border px-1.5 font-mono text-[11px] leading-none font-medium',
        className,
      )}
      {...props}
    />
  );
}

export function Separator({ className, vertical }: { className?: string; vertical?: boolean }) {
  return <div className={cn('bg-border shrink-0', vertical ? 'h-4 w-px' : 'h-px w-full', className)} />;
}

/* ───────────── Switch ───────────── */

export function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        'bg-raised border-input data-[state=checked]:bg-primary data-[state=checked]:border-primary inline-flex h-5 w-9 shrink-0 items-center rounded-full border p-0.5 transition-colors',
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="block size-3.5 rounded-full bg-white shadow-sm transition-transform data-[state=checked]:-translate-x-4 ltr:data-[state=checked]:translate-x-4" />
    </SwitchPrimitive.Root>
  );
}

/* ───────────── Progress ───────────── */

const progressTone: Record<string, string> = {
  primary: 'bg-primary',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
};

export function Progress({
  value,
  tone = 'primary',
  className,
}: {
  value: number;
  tone?: 'primary' | 'success' | 'warning' | 'danger';
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <ProgressPrimitive.Root value={clamped} className={cn('bg-raised h-1 w-full overflow-hidden rounded', className)}>
      <div className={cn('h-full rounded transition-[width] duration-500', progressTone[tone])} style={{ width: `${clamped}%` }} />
    </ProgressPrimitive.Root>
  );
}

/* ───────────── Tooltip (Kortix "Hint") ───────────── */

export function Hint({
  label,
  side = 'bottom',
  children,
}: {
  label: React.ReactNode;
  side?: 'top' | 'bottom' | 'left' | 'right';
  children: React.ReactNode;
}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          dir="rtl"
          side={side}
          sideOffset={6}
          className="bg-raised text-foreground border-border animate-in fade-in-0 zoom-in-95 z-[80] flex max-w-[280px] items-center gap-1.5 rounded-lg border px-3 py-2 text-xs leading-5 shadow-float"
        >
          {label}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

/* ───────────── Segmented control ───────────── */

/** A folder or file path on one line. When it does not fit, the beginning is cut and the
 *  end stays visible (the part that tells paths apart); hovering shows all of it. */
export function PathText({ path, className }: { path: string; className?: string }) {
  return (
    <Hint label={<span dir="ltr" className="block max-w-[32rem] font-mono text-xs break-all">{path}</span>}>
      {/* A right-to-left box clips on the left, which is where a path begins. */}
      <span dir="rtl" className={cn('block min-w-0 truncate font-mono', className)}>
        <bdi dir="ltr">{path}</bdi>
      </span>
    </Hint>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  size = 'default',
  className,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: React.ReactNode; icon?: React.ReactNode }[];
  size?: 'default' | 'sm';
  className?: string;
}) {
  return (
    <div className={cn('bg-panel border-border inline-flex items-center gap-0.5 rounded-lg border p-0.5', className)} role="tablist">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            'text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 rounded-md px-2.5 font-medium whitespace-nowrap transition-colors [&_svg]:size-4',
            size === 'sm' ? 'h-7 text-xs' : 'h-8 text-sm',
            value === option.value && 'bg-active text-primary',
          )}
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}

/* ───────────── Small bits ───────────── */

const dotTone: Record<string, string> = {
  neutral: 'bg-faint',
  primary: 'bg-primary',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
};

export function Dot({ tone = 'neutral', pulse, className }: { tone?: string; pulse?: boolean; className?: string }) {
  return <span className={cn('inline-block size-1.5 shrink-0 rounded-full', dotTone[tone], pulse && 'animate-pulse-dot', className)} />;
}

/** Tinted square that carries an icon or initial; used for agents, files and connections. */
export function Glyph({
  children,
  tone = 'neutral',
  size = 'md',
  className,
}: {
  children: React.ReactNode;
  tone?: Tone | 'chart2' | 'chart3' | 'chart4';
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}) {
  const tones: Record<string, string> = {
    neutral: 'bg-raised text-muted-foreground',
    outline: 'border text-muted-foreground',
    primary: 'bg-primary-soft text-primary',
    success: 'bg-success-soft text-success',
    warning: 'bg-warning-soft text-warning',
    danger: 'bg-danger-soft text-danger',
    info: 'bg-info-soft text-info',
    chart2: 'bg-chart-2/12 text-chart-2',
    chart3: 'bg-chart-3/12 text-chart-3',
    chart4: 'bg-chart-4/12 text-chart-4',
  };
  const sizes = {
    sm: 'size-6 rounded-md text-[11px] [&_svg]:size-3.5',
    md: 'size-8 rounded-lg text-sm [&_svg]:size-4',
    lg: 'size-10 rounded-lg text-base [&_svg]:size-5',
  };
  return (
    <span className={cn('inline-flex shrink-0 items-center justify-center font-semibold', tones[tone], sizes[size], className)}>
      {children}
    </span>
  );
}
