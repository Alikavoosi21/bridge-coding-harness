import { cva, type VariantProps } from 'class-variance-authority';
import { Slot } from 'radix-ui';
import * as React from 'react';

import { cn } from '@/lib/utils';

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-lg text-sm font-semibold whitespace-nowrap outline-none transition-[color,background-color,border-color,opacity] duration-150 disabled:pointer-events-none disabled:border-transparent disabled:bg-raised disabled:text-[var(--text-disabled)] [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-5",
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary-strong active:bg-[#22c55e]',
        soft: 'bg-primary-soft text-primary hover:bg-active',
        secondary: 'border border-border-strong bg-transparent text-foreground hover:bg-hover',
        outline: 'border border-border-strong bg-transparent text-foreground hover:bg-hover',
        ghost: 'bg-transparent text-foreground hover:bg-hover',
        muted: 'bg-transparent text-muted-foreground hover:bg-hover hover:text-foreground',
        success: 'bg-success-soft text-success hover:bg-success/20',
        danger: 'bg-danger-soft text-danger hover:bg-danger/20',
        destructive: 'bg-danger-soft text-danger hover:bg-danger/20',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-10 px-4',
        sm: 'h-8 px-3 text-sm',
        xs: 'h-8 px-2.5 text-xs',
        lg: 'h-12 px-5',
        icon: "size-10 [&_svg:not([class*='size-'])]:size-5",
        'icon-sm': "size-9 [&_svg:not([class*='size-'])]:size-5",
        'icon-xs': "size-7 [&_svg:not([class*='size-'])]:size-4",
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<'button'> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : 'button';
  return <Comp data-slot="button" className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}

export { Button, buttonVariants };
