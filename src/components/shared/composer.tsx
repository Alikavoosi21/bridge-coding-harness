'use client';

import { ArrowUpIcon, CaretDownIcon, CheckIcon, CpuIcon, GearSixIcon, RobotIcon, ShieldCheckIcon, StopIcon } from '@phosphor-icons/react';
import Link from 'next/link';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from '@/components/ui/overlays';
import { Hint } from '@/components/ui/primitives';
import type { Mode } from '@/lib/api';
import { modeLabel, useBackend } from '@/lib/backend';
import { useUi } from '@/lib/store';
import { cn } from '@/lib/utils';

const toolbarButton =
  'text-muted-foreground hover:bg-hover hover:text-foreground data-[state=open]:bg-hover border-border flex h-8 max-w-56 items-center gap-1.5 rounded-lg border bg-panel px-2.5 text-xs outline-none [&_svg]:size-3.5';

/** The message box. Under it, the three choices that shape a run: who leads it,
 *  which model answers, and how much it may do without asking. */
export function Composer({
  onSend,
  onStop,
  busy = false,
  placeholder = 'کاری را در این پروژه بسپارید…',
  autoFocus,
  large,
  className,
  value,
  onValueChange,
}: {
  onSend: (text: string) => void;
  onStop?: () => void;
  busy?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
  large?: boolean;
  className?: string;
  /** Controlled draft, so a suggestion can seed the box without sending it. */
  value?: string;
  onValueChange?: (value: string) => void;
}) {
  const [internal, setInternal] = useState('');
  const text = value ?? internal;
  const setText = (next: string) => {
    if (value === undefined) setInternal(next);
    onValueChange?.(next);
  };
  const models = useBackend((s) => s.models);
  const agents = useBackend((s) => s.agents);
  const options = useUi((s) => s.runOptions);
  const setOptions = useUi((s) => s.setRunOptions);
  const setSettingsTab = useUi((s) => s.setSettingsTab);

  const model = models.find((m) => m.id === options.modelId) ?? models.find((m) => m.is_default) ?? models[0];
  const agent = agents.find((a) => a.id === options.agentId);

  const send = () => {
    const value = text.trim();
    if (!value || busy) return;
    onSend(value);
    setText('');
  };

  return (
    <div
      className={cn(
        'bg-surface border-input focus-within:border-ring flex flex-col gap-3 rounded-xl border p-4 transition-colors',
        className,
      )}
    >
      <textarea
        value={text}
        autoFocus={autoFocus}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          // Enter during a Persian/IME composition confirms the composition, not the message.
          if (e.nativeEvent.isComposing) return;
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        rows={large ? 3 : 2}
        placeholder={placeholder}
        className="scrollbar-minimal placeholder:text-muted-foreground block max-h-52 min-h-[72px] w-full resize-none bg-transparent text-[15px] leading-7 outline-none"
      />
      <div className="flex flex-wrap items-center gap-1.5">
        <Menu>
          <MenuTrigger className={toolbarButton}>
            <RobotIcon />
            <span className="truncate">{agent ? agent.title : 'هماهنگ‌کننده'}</span>
            <CaretDownIcon className="size-3! shrink-0" />
          </MenuTrigger>
          <MenuContent align="start" side="top" className="w-72">
            <MenuLabel>چه کسی این کار را پیش ببرد؟</MenuLabel>
            <MenuItem onSelect={() => setOptions({ agentId: null })}>
              <span className="flex-1">هماهنگ‌کننده (پیش‌فرض)</span>
              {!agent && <CheckIcon className="text-primary!" />}
            </MenuItem>
            {agents.map((a) => (
              <MenuItem key={a.id} onSelect={() => setOptions({ agentId: a.id })} className="h-auto py-1.5">
                <span className="min-w-0 flex-1 leading-tight">
                  <span className="block">{a.title}</span>
                  <span className="text-muted-foreground block truncate text-[11px]">{a.description}</span>
                </span>
                {agent?.id === a.id && <CheckIcon className="text-primary!" />}
              </MenuItem>
            ))}
          </MenuContent>
        </Menu>

        <Menu>
          <MenuTrigger className={toolbarButton}>
            <CpuIcon />
            <span className="truncate">{model ? model.name : 'بدون مدل'}</span>
            <CaretDownIcon className="size-3! shrink-0" />
          </MenuTrigger>
          <MenuContent align="start" side="top" className="w-72">
            <MenuLabel>مدل این پیام</MenuLabel>
            {models.map((m) => (
              <MenuItem key={m.id} onSelect={() => setOptions({ modelId: m.id })} className="h-auto py-1.5">
                <span className="min-w-0 flex-1 leading-tight">
                  <span className="block">{m.name}</span>
                  <span className="text-muted-foreground ltr-nums block truncate text-end font-mono text-[11px]">{m.model}</span>
                </span>
                {model?.id === m.id && <CheckIcon className="text-primary!" />}
              </MenuItem>
            ))}
            <MenuSeparator />
            <MenuItem asChild>
              <Link href="/settings" onClick={() => setSettingsTab('models')}>
                <GearSixIcon />
                تعریف و مدیریت مدل‌ها
              </Link>
            </MenuItem>
          </MenuContent>
        </Menu>

        <Menu>
          <MenuTrigger className={toolbarButton}>
            <ShieldCheckIcon />
            <span className="truncate">{modeLabel[options.mode].label}</span>
            <CaretDownIcon className="size-3! shrink-0" />
          </MenuTrigger>
          <MenuContent align="start" side="top" className="w-80">
            <MenuLabel>چقدر بدون پرسیدن پیش برود؟</MenuLabel>
            {(Object.keys(modeLabel) as Mode[]).map((key) => (
              <MenuItem key={key} onSelect={() => setOptions({ mode: key })} className="h-auto py-2">
                <span className="flex-1 leading-tight">
                  <span className="block">{modeLabel[key].label}</span>
                  <span className="text-muted-foreground block text-[11px]">{modeLabel[key].hint}</span>
                </span>
                {options.mode === key && <CheckIcon className="text-primary!" />}
              </MenuItem>
            ))}
          </MenuContent>
        </Menu>

        <div className="flex-1" />

        {busy ? (
          <Hint label="توقف" side="top">
            <Button size="icon" variant="secondary" onClick={onStop} aria-label="توقف">
              <StopIcon weight="fill" />
            </Button>
          </Hint>
        ) : (
          <Button size="icon" disabled={!text.trim()} onClick={send} aria-label="ارسال">
            <ArrowUpIcon weight="bold" />
          </Button>
        )}
      </div>
    </div>
  );
}
