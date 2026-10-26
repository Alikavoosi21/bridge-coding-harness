import type { Metadata } from 'next';

import { AppShell } from '@/features/shell/app-shell';
import { Providers } from './providers';
import './globals.css';

export const metadata: Metadata = {
  title: 'Bridge — هارنس کدنویسی',
  description: 'هارنس کدنویسی محلی؛ برنامه‌ریزی، اجرا و اصلاح کد با کنترل شما',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl" suppressHydrationWarning>
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
