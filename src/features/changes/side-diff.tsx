'use client';

import { useEffect,useRef } from 'react';
import { MergeView } from '@codemirror/merge';
import { EditorState } from '@codemirror/state';
import { EditorView,lineNumbers } from '@codemirror/view';

/** Read-only comparison: no hunk/revert controls can mutate either document. */
export function SideDiff({before,after,wrap}:{before:string;after:string;wrap:boolean}){
  const parent=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!parent.current)return;
    const theme=EditorView.theme({
      '&':{backgroundColor:'var(--surface)',color:'var(--foreground)'},
      '.cm-scroller':{fontFamily:'var(--font-mono), monospace',fontSize:'12px'},
      '.cm-gutters':{backgroundColor:'var(--panel)',color:'var(--muted-foreground)',border:'none'},
      '.cm-deletedLine':{backgroundColor:'var(--danger-soft)'},
      '.cm-insertedLine':{backgroundColor:'var(--success-soft)'},
      '.cm-deletedText':{backgroundColor:'var(--danger-soft)',textDecoration:'underline'},
      '.cm-insertedText':{backgroundColor:'var(--success-soft)',textDecoration:'underline'},
    });
    const extensions=[EditorState.readOnly.of(true),EditorView.editable.of(false),EditorView.contentAttributes.of({'aria-label':'مقایسهٔ فقط‌خواندنی'}),lineNumbers(),theme,...(wrap?[EditorView.lineWrapping]:[])];
    const view=new MergeView({parent:parent.current,a:{doc:before,extensions},b:{doc:after,extensions},highlightChanges:true,gutter:true});
    return()=>view.destroy();
  },[before,after,wrap]);
  return <div className="flex min-h-full flex-col" dir="ltr">
    <div className="grid grid-cols-2 border-b text-xs text-muted-foreground"><span className="p-2">Baseline</span><span className="p-2">Working copy</span></div>
    <div ref={parent} className="min-h-0 flex-1 [&_.cm-mergeView]:min-h-full [&_.cm-mergeView]:overflow-auto"/>
  </div>;
}
