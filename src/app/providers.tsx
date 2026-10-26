'use client';

import { IconContext } from '@phosphor-icons/react';
import { ThemeProvider, useTheme } from 'next-themes';
import { Direction, Tooltip } from 'radix-ui';
import { useEffect } from 'react';
import { Toaster } from 'sonner';

/** Marks the document when running inside Electron and keeps the native
 *  window-control overlay in step with the app theme. */
function DesktopBridge() {
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    if (window.desktop?.isDesktop) document.documentElement.classList.add('is-desktop');
  }, []);

  useEffect(() => {
    if (resolvedTheme === 'light' || resolvedTheme === 'dark') window.desktop?.setTheme(resolvedTheme);
  }, [resolvedTheme]);

  return null;
}

function ThemedToaster() {
  return <Toaster dir="rtl" position="bottom-left" theme="dark" closeButton />;
}

const ICON_DEFAULTS = { weight: 'bold' as const };

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" forcedTheme="dark" enableSystem={false} disableTransitionOnChange>
      <Direction.Provider dir="rtl">
        {/* Bold strokes by default; an explicit weight (fill, duotone) on an icon still wins. */}
        <IconContext.Provider value={ICON_DEFAULTS}>
          <Tooltip.Provider delayDuration={350}>
            {children}
            <ThemedToaster />
            <DesktopBridge />
          </Tooltip.Provider>
        </IconContext.Provider>
      </Direction.Provider>
    </ThemeProvider>
  );
}
