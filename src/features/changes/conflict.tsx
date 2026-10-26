'use client';

import CodeMirror from '@uiw/react-codemirror';
import { EditorView } from '@codemirror/view';

const theme=EditorView.theme({'&':{backgroundColor:'var(--surface)',color:'var(--foreground)'},'.cm-scroller':{fontFamily:'var(--font-mono), monospace',fontSize:'12px'},'.cm-gutters':{backgroundColor:'var(--panel)',color:'var(--muted-foreground)',border:'none'}});

export function ConflictVersions({before,current,after,currentSupported,wrap}:{before:string;current?:string|null;after:string;currentSupported:boolean;wrap:boolean}){
  return <section dir="rtl" aria-label="سه نسخهٔ فایل متعارض" className="flex flex-col gap-3 p-3">
    <p className="rounded border border-warning bg-warning-soft p-3 text-xs leading-6 text-warning">اصل پروژه پس از شروع کار تغییر کرده است. این فایل برای اعمال انتخاب‌پذیر نیست؛ سه نسخه را مقایسه کنید. ویرایش نسخهٔ کاری به‌تنهایی مجوز بازنویسی اصل نیست.</p>
    <div className="grid gap-3 xl:grid-cols-3">{[{name:'مبنا؛ پیش از شروع کار',value:before,supported:true},{name:'اصل فعلی؛ تغییر کاربر',value:current??'',supported:currentSupported},{name:'نسخهٔ کاری ایجنت',value:after,supported:true}].map(version=><section key={version.name} className="min-w-0 rounded-lg border"><h2 className="border-b bg-panel p-2 text-xs">{version.name}</h2>{version.supported?<div dir="ltr"><CodeMirror theme="dark" value={version.value} height="240px" readOnly editable={false} extensions={[theme,...(wrap?[EditorView.lineWrapping]:[])]} aria-label={version.name}/></div>:<p className="p-3 text-xs text-muted-foreground">اصل فعلی قابل نمایش متنی نیست یا حین خواندن تغییر کرده است؛ نسخه‌ای حدس زده نمی‌شود.</p>}</section>)}</div>
  </section>;
}
