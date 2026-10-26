'use client';

/** Adapted from https://registry.ai-sdk.dev/confirmation.json (vercel/ai-elements).
 * Copyright 2023 Vercel, Inc. Apache-2.0; see docs/licenses/.
 * Installed AI SDK approval states; local shadcn Alert/Button and brand tokens.
 * Presentation only: callbacks must obtain a canonical backend decision.
 */
import { createContext,useContext,type ComponentProps,type ReactNode } from 'react';
import type { ToolUIPart } from 'ai';
import { Alert } from '@/components/ui/shadcn/alert';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type Approval={id:string;approved?:boolean;reason?:string};
const Context=createContext<{approval:Approval;state:ToolUIPart['state']}|null>(null);
function useConfirmation(){const value=useContext(Context);if(!value)throw new Error('Confirmation requires a parent');return value}

export function Confirmation({approval,state,className,...props}:ComponentProps<typeof Alert>&{approval:Approval;state:ToolUIPart['state']}){
  if(state==='input-streaming'||state==='input-available')return null;
  return <Context.Provider value={{approval,state}}><Alert className={cn('flex flex-col items-stretch gap-2 border-warning/40 bg-warning-soft text-foreground',className)} {...props}/></Context.Provider>;
}
export function ConfirmationRequest({children}:{children:ReactNode}){
  return useConfirmation().state==='approval-requested'?children:null;
}
export function ConfirmationActions({className,...props}:ComponentProps<'div'>){
  return useConfirmation().state==='approval-requested'?<div className={cn('flex flex-wrap items-center gap-2',className)} {...props}/>:null;
}
export function ConfirmationAction(props:ComponentProps<typeof Button>){return <Button type="button" size="sm" {...props}/>}
