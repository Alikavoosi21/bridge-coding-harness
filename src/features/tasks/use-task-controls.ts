'use client';
import { useCallback,useEffect,useMemo,useRef,useState } from 'react';
import { createBrowserClient } from '@/lib/harness/browser';
import { HarnessRequestError,type HarnessApproval,type HarnessGrant,type HarnessTaskSnapshot } from '@/lib/harness/client';
import type { TaskChat } from './use-task-chat';

export function useTaskControls(chat: TaskChat,taskId: string) {
  const client=useMemo(()=>createBrowserClient(),[]);
  const [approvals,setApprovals]=useState<HarnessApproval[]>([]);
  const [grants,setGrants]=useState<HarnessGrant[]>([]);
  const [busy,setBusy]=useState<string|null>(null);
  const [error,setError]=useState<string|null>(null);
  const stopKey=useRef<string|null>(null);
  const resumeKey=useRef<string|null>(null);
  const mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
  const refresh=useCallback(async()=>{
    const [result,permissions]=await Promise.all([client.approvals(taskId),client.grants(taskId)]);
    if(mounted.current){setApprovals(result.items);setGrants(permissions.items)}
    return result.items;
  },[client,taskId]);
  const status=chat.status;
  const approvalSignal=Object.keys(chat.domain.approvals).join('|');
  useEffect(()=>{
    if(chat.phase!=='ready')return;
    let disposed=false;
    const read=()=>void refresh().catch(()=>{if(!disposed)setError('خواندن درخواست‌های تأیید ممکن نشد.');});
    read();
    const timer=status==='awaiting_action'?setInterval(read,2000):undefined;
    return()=>{disposed=true;clearInterval(timer)};
  },[refresh,status,chat.phase,approvalSignal]);
  const action=async(name:string,work:()=>Promise<void>)=>{
    if(busy)return false;
    setBusy(name);setError(null);
    try{await work();return true}catch(error){
      if(mounted.current)setError(error instanceof HarnessRequestError && error.code==='selection_stale'?'درخواست تغییر کرده؛ نسخهٔ تازه را بازبینی کنید.':error instanceof Error?error.message:'انجام درخواست ممکن نشد.');
      await refresh().catch(()=>{});return false;
    }finally{if(mounted.current)setBusy(null)}
  };
  const continueIfReady=async()=>{
    const rows=await refresh();
    if(rows.some(row=>row.state==='pending'))return;
    resumeKey.current??=`resume:${taskId}:${crypto.randomUUID()}`;
    const result=await client.resumeApprovals(taskId,resumeKey.current);
    chat.acceptTask(result.task);resumeKey.current=null;
  };
  return {approvals,grants,busy,error,refresh:()=>void refresh().then(()=>setError(null)).catch(()=>setError('خواندن درخواست‌ها ممکن نشد.')),
    decide:(approval:HarnessApproval,decision:'approve'|'reject',grant=false,reason='')=>action(approval.id,async()=>{
      const result=await client.decideAction(taskId,approval.id,{decision,fingerprint:approval.action_hash,revision:approval.revision,grant,reason});
      chat.acceptTask(result.task);await continueIfReady();
    }),
    edit:(approval:HarnessApproval,args:Record<string,unknown>)=>action(approval.id,async()=>{
      const result=await client.editAction(taskId,approval,args);chat.acceptTask(result.task);await refresh();
    }),
    resume:()=>action('resume',continueIfReady),
    mode:(mode:'ask'|'grant'|'auto')=>action('mode',async()=>{
      const result=await client.changeAccess(taskId,mode,chat.snapshot?.revision??0);chat.acceptTask(result.task);await refresh();
    }),
    enableEditing:()=>action('editing',async()=>{
      const result=await client.changeAccess(taskId,'auto',chat.snapshot?.revision??0,false);chat.acceptTask(result.task);await chat.reload();await refresh();
    }),
    revoke:()=>action('revoke',async()=>{await client.revokeGrants(taskId);await refresh();}),
    stop:()=>action('stop',async()=>{
      stopKey.current??=`stop:${taskId}:${crypto.randomUUID()}`;
      const result=await client.stopTask(taskId,stopKey.current) as {task:HarnessTaskSnapshot};
      chat.acceptTask(result.task);await refresh();stopKey.current=null;
    }),
  };
}
export type TaskControls=ReturnType<typeof useTaskControls>;
