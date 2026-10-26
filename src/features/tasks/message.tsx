'use client';

import { PaperclipIcon } from '@phosphor-icons/react';

import { MarkdownView } from '@/components/shared/file-viewers';
import { Message as MessageFrame } from '@/components/ai-elements/message';
import { PathText } from '@/components/ui/primitives';
import type { HarnessChatMessage } from '@/lib/harness/projection';
import { cn } from '@/lib/utils';

function textOf(message: HarnessChatMessage): string {
  return message.parts
    .filter((part) => part.type === 'text')
    .map((part) => part.text)
    .join('');
}

/**
 * One transcript entry.
 *
 * Only text parts are drawn. Canonical domain facts travel as `data-harness`
 * parts and belong to the activity timeline and the inspector; rendering them
 * as chat text would let the model's plan look like a second source of truth.
 */
export function Message({ message, active }: { message: HarnessChatMessage; active: boolean }) {
  const text = textOf(message);
  const references = message.metadata?.references ?? [];
  const waiting = message.role === 'user' && active && message.metadata?.delivered_at == null;

  if (message.role === 'user') {
    return (
      <MessageFrame from="user" className="ms-0 max-w-full items-end gap-1.5">
        <div
          dir="auto"
          className="bg-primary-soft text-foreground max-w-[85%] rounded-2xl rounded-te-md px-4 py-2.5 text-[15px] leading-7 whitespace-pre-wrap"
        >
          {text}
        </div>
        {references.length > 0 && (
          <div className="flex max-w-[85%] flex-wrap items-center justify-end gap-1.5">
            {references.map((path) => (
              <span key={path} className="text-faint flex items-center gap-1 text-[11px]">
                <PaperclipIcon className="size-3 shrink-0" />
                <PathText path={path} />
              </span>
            ))}
          </div>
        )}
        {waiting && (
          <span className="text-warning text-[11px] leading-5">پس از پایان اقدام جاری به ایجنت می‌رسد.</span>
        )}
      </MessageFrame>
    );
  }

  if (!text) {
    return active ? (
      <div className="text-muted-foreground flex items-center gap-1 py-1 text-sm" aria-label="در حال نوشتن">
        <span className="bg-muted-foreground/60 size-1.5 animate-pulse rounded-full" />
        <span className="bg-muted-foreground/60 size-1.5 animate-pulse rounded-full [animation-delay:120ms]" />
        <span className="bg-muted-foreground/60 size-1.5 animate-pulse rounded-full [animation-delay:240ms]" />
      </div>
    ) : null;
  }

  return (
    <MessageFrame from={message.role} className={cn('max-w-full text-[15px] leading-7')} dir="auto">
      <MarkdownView text={text} className="chat-prose" />
    </MessageFrame>
  );
}
