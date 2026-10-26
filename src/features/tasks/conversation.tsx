'use client';

import { ArrowDownIcon, ChatsCircleIcon } from '@phosphor-icons/react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { EmptyNote } from '@/components/ui/patterns';
import type { HarnessChatMessage } from '@/lib/harness/projection';
import { cn } from '@/lib/utils';

import { Message } from './message';

function textLength(message: HarnessChatMessage | undefined): number {
  if (message === undefined) return 0;
  return message.parts.reduce((total, part) => (part.type === 'text' ? total + part.text.length : total), 0);
}

/**
 * The conversation column.
 *
 * It sticks to the bottom while the reader is at the bottom. Scrolling up is a
 * deliberate act: new tokens no longer move the page, and a "new message"
 * button says what happened. That is how P05 keeps an old message readable
 * during a long run.
 */
export function Conversation({
  messages,
  active,
  summary,
  footer,
  loading = false,
}: {
  messages: HarnessChatMessage[];
  active: boolean;
  summary?: React.ReactNode;
  footer?: React.ReactNode;
  loading?: boolean;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [hasNew, setHasNew] = useState(false);
  const lastSignal = useRef('');

  // Steering can be the final visible user message while an earlier assistant
  // response is still growing. Observe the whole transcript, not only its tail.
  const signal = `${messages.length}:${messages.reduce((total, message) => total + textLength(message), 0)}`;

  const scrollToBottom = useCallback((smooth: boolean) => {
    const node = scroller.current;
    if (node === null) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    node.scrollTo({ top: node.scrollHeight, behavior: smooth && !reduce ? 'smooth' : 'auto' });
  }, []);

  useEffect(() => {
    if (lastSignal.current === signal) return;
    if (lastSignal.current !== '' && !atBottom) setHasNew(true);
    lastSignal.current = signal;
    if (atBottom) scrollToBottom(true);
  }, [atBottom, scrollToBottom, signal]);

  useEffect(() => {
    // A task that arrives already written starts at its newest line.
    scrollToBottom(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onScroll = () => {
    const node = scroller.current;
    if (node === null) return;
    const near = node.scrollHeight - node.scrollTop - node.clientHeight < 120;
    setAtBottom(near);
    if (near) setHasNew(false);
  };

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div ref={scroller} onScroll={onScroll} className="scrollbar-minimal min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[880px] space-y-5 px-6 py-6">
          {summary}
          {loading ? (
            <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
              <ChatsCircleIcon className="size-5" /> در حال خواندن گفتگو…
            </div>
          ) : messages.length === 0 ? (
            <EmptyNote title="هنوز گفتگویی نیست">
              پیام اول را بفرستید تا ایجنت هدف را بخواند و برنامه پیشنهاد کند.
            </EmptyNote>
          ) : (
            messages.map((message) => <Message key={message.id} message={message} active={active} />)
          )}
          {footer}
          <div className="h-1" />
        </div>
      </div>

      {hasNew && (
        <button
          type="button"
          onClick={() => {
            scrollToBottom(true);
            setAtBottom(true);
            setHasNew(false);
          }}
          className={cn(
            'bg-raised border-border hover:bg-hover absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs shadow-float',
          )}
        >
          <ArrowDownIcon className="size-3.5" />
          پیام تازه
        </button>
      )}
    </div>
  );
}
