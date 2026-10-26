'use client';

/** Adapted from https://registry.ai-sdk.dev/tool.json (vercel/ai-elements).
 * Copyright 2023 Vercel, Inc. Apache-2.0; see docs/licenses/.
 * Local shadcn Collapsible, Phosphor, Persian labels and bounded plain output;
 * no syntax-highlighter dependency or tool execution in the renderer.
 */
import type { ComponentProps } from 'react';
import type { ToolUIPart } from 'ai';
import { CaretDownIcon,TerminalWindowIcon } from '@phosphor-icons/react';
import { Collapsible,CollapsibleContent,CollapsibleTrigger } from '@/components/ui/shadcn/collapsible';
import { cn } from '@/lib/utils';

export function Tool({className,...props}:ComponentProps<typeof Collapsible>){
  return <Collapsible className={cn('not-prose group w-full rounded-md border',className)} {...props}/>;
}
export function ToolHeader({title,state,statusLabel,...props}:ComponentProps<typeof CollapsibleTrigger>&{title:string;state:ToolUIPart['state'];statusLabel?:string}){
  const labels:Record<ToolUIPart['state'],string>={
    'input-streaming':'در انتظار','input-available':'در حال اجرا','approval-requested':'منتظر تأیید',
    'approval-responded':'تصمیم ثبت شد','output-available':'انجام شد','output-error':'ناموفق','output-denied':'رد شد',
  };
  return <CollapsibleTrigger className="flex w-full items-center gap-2 p-2 text-start text-xs focus-visible:outline-2 focus-visible:outline-ring" {...props}>
    <TerminalWindowIcon className="size-4 shrink-0"/><span>{title}</span><span className="text-muted-foreground ms-auto text-[11px]">{statusLabel??labels[state]}</span><CaretDownIcon className="size-3 motion-safe:transition-transform group-data-[state=open]:rotate-180"/>
  </CollapsibleTrigger>;
}
export function ToolContent({className,...props}:ComponentProps<typeof CollapsibleContent>){return <CollapsibleContent className={cn('p-2 pt-0',className)} {...props}/>}
export function ToolOutput({output,errorText}:{output?:string|null;errorText?:string|null}){
  if(!output&&!errorText)return null;
  return <div className="flex flex-col gap-2">
    {output&&<pre dir="ltr" className="bg-background scrollbar-minimal max-h-56 overflow-auto rounded-md border p-2.5 font-mono text-[11px] leading-5 whitespace-pre-wrap">{output}</pre>}
    {errorText&&<pre dir="ltr" className="bg-danger-soft text-danger scrollbar-minimal max-h-40 overflow-auto rounded-md p-2.5 font-mono text-[11px] leading-5 whitespace-pre-wrap">{errorText}</pre>}
  </div>;
}
