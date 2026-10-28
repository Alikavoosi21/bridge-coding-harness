const {_electron:electron}=require('playwright');
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'checks/local-outputs');fs.mkdirSync(out,{recursive:true});
const tmp=fs.mkdtempSync(path.join(root,'.test-runs/output-ui-'));
const env={...process.env,HARNESS_HOME:path.join(tmp,'home'),TEMP:tmp,TMP:tmp};delete env.ELECTRON_RUN_AS_NODE;
const report={checks:[],errors:[],scope:'Actual desktop, bundled native Python/Node and preview; Docker is not used. Separate test profile/project; demo planning only.'};
const check=(name,ok)=>{report.checks.push({name,passed:!!ok});if(!ok)throw Error(name)};
(async()=>{
 let app,page,api,headers,taskId;
 try{
  const dev=process.env.HARNESS_TEST_DEV==='1';app=await electron.launch({executablePath:process.env.HARNESS_TEST_EXE||(dev?require('electron'):path.join(root,'release/dist/win-unpacked/Bridge Coding Harness.exe')),args:[...(dev?[root]:[]),'--user-data-dir='+path.join(tmp,'desktop')],env,timeout:45000});
  await app.evaluate(({dialog})=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});});
  report.identity=await app.evaluate(({app})=>({version:app.getVersion(),packaged:app.isPackaged}));page=await app.firstWindow();page.on('pageerror',e=>report.errors.push(String(e)));
  await page.getByRole('button',{name:'رد کردن',exact:true}).click();await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor();const home=page.url();
  api=await page.evaluate(()=>window.desktop.api);headers={Authorization:'Bearer '+api.token,'Content-Type':'application/json'};
  const request=async(route,method='GET',body)=>{const r=await fetch(api.url+route,{method,headers,...(body?{body:JSON.stringify(body)}:{})});if(!r.ok)throw Error(route+' '+await r.text());return r.json()};
  const project=path.join(tmp,'project');fs.mkdirSync(project);
  fs.writeFileSync(path.join(project,'index.html'),'<!doctype html><html><link rel="stylesheet" href="style.css"><h1>HTML_OUTPUT_OK</h1><button onclick="document.querySelector(\'h1\').textContent=\'HTML_JS_OK\'">Test interaction</button><script src="client.js"></script></html>');
  fs.writeFileSync(path.join(project,'style.css'),'body{background:rgb(12,60,120);color:white;font:24px sans-serif;padding:32px}');fs.writeFileSync(path.join(project,'client.js'),'document.title="PREVIEW_SCRIPT_LOADED"');
  fs.writeFileSync(path.join(project,'main.py'),'from pathlib import Path\nPath("run-only.txt").write_text("isolated copy")\nprint("PYTHON_OUTPUT_OK")\n');
  const serverHtml='<html><h1>LIVE_WEB_APP_OK</h1><button onclick="this.textContent=\'SERVER_JS_OK\'">Interactive app</button></html>';
  fs.writeFileSync(path.join(project,'server.js'),`require('http').createServer((q,r)=>{r.setHeader('Content-Type','text/html');r.end(${JSON.stringify(serverHtml)})}).listen(process.env.PORT||3000,'0.0.0.0');console.log('WEB_SERVER_RUNNING');`);
  await request('/workspace','POST',{path:project});await request('/models/probe','POST',{id:'demo'});
  taskId=(await request('/tasks','POST',{prompt:'Inspect the example project and propose a short plan.',read_only:false,mode:'auto'})).task.id;
  await request('/tasks/'+taskId+'/plan-proposals','POST',{});
  for(let i=0;i<150;i++){const t=await request('/tasks/'+taskId);if(!['queued','planning'].includes(t.status))break;await new Promise(r=>setTimeout(r,200));}
  await page.goto(new URL('/tasks?task='+taskId,home).toString());
  await page.getByRole('button',{name:'پیش‌نمایش index.html',exact:true}).first().click();
  const dialog=()=>page.getByRole('dialog'),frame=()=>page.frameLocator('iframe[title="پیش‌نمایش خروجی"]');
  await frame().getByRole('heading',{name:'HTML_OUTPUT_OK',exact:true}).waitFor();
  check('HTML opens directly from the chat',true);
  const ready=await request('/readiness');check('runtime is native and not falsely called a sandbox',ready.runtime.kind==='local'&&ready.runtime.sandboxed===false);
  check('bundled default project exists without choosing a folder',(await request('/workspaces')).items.some(w=>w.name==='فضای ساخت برنامه'));
  check('relative CSS is served',await frame().locator('body').evaluate(el=>getComputedStyle(el).backgroundColor)==='rgb(12, 60, 120)');
  check('relative JavaScript loads',await frame().locator('html').evaluate(()=>document.title)==='PREVIEW_SCRIPT_LOADED');
  await frame().getByRole('button',{name:'Test interaction',exact:true}).click();await frame().getByRole('heading',{name:'HTML_JS_OK',exact:true}).waitFor();
  check('generated JavaScript actually runs',true);
  check('frame has no desktop API or Node access',await frame().locator('html').evaluate(()=>typeof window.desktop==='undefined'&&typeof require==='undefined'));
  await page.screenshot({path:path.join(out,'01-html-preview.png')});
  const windowPromise=app.waitForEvent('window');await dialog().getByRole('button',{name:'پنجرهٔ جدا',exact:true}).click();const popup=await windowPromise;
  await popup.getByRole('heading',{name:'HTML_OUTPUT_OK',exact:true}).waitFor();check('real separate preview window opens',true);
  check('separate window has no privileged preload',await popup.evaluate(()=>typeof window.desktop==='undefined'&&typeof require==='undefined'));
  await popup.screenshot({path:path.join(out,'02-separate-window.png')});const native=await app.browserWindow(popup);await native.evaluate(win=>win.close());
  await dialog().getByRole('button',{name:'توقف خروجی',exact:true}).click();
  await dialog().locator('summary').click();await dialog().getByRole('textbox',{name:'فرمان اجرای خروجی',exact:true}).fill('python main.py');
  await dialog().getByRole('combobox',{name:'نوع اجرای خروجی',exact:true}).selectOption('command');await dialog().getByRole('button',{name:'اجرای فرمان',exact:true}).click();
  await dialog().getByLabel('خروجی اجرای کد',{exact:true}).getByText('PYTHON_OUTPUT_OK',{exact:false}).waitFor({timeout:45000});check('Python runs and its actual output appears',true);
  check('execution cannot write the original project',!fs.existsSync(path.join(project,'run-only.txt')));
  check('execution does not mutate the agent working copy',!fs.existsSync(path.join(env.HARNESS_HOME,'tasks',taskId,'working','run-only.txt')));
  await page.screenshot({path:path.join(out,'03-python-output.png')});
  if(!await dialog().getByRole('textbox',{name:'فرمان اجرای خروجی',exact:true}).isVisible())await dialog().locator('summary').click();
  await dialog().getByRole('textbox',{name:'فرمان اجرای خروجی',exact:true}).fill('node server.js');await dialog().getByRole('combobox',{name:'نوع اجرای خروجی',exact:true}).selectOption('server');
  await dialog().getByRole('button',{name:'اجرا و نمایش برنامه',exact:true}).click();
  await frame().getByRole('heading',{name:'LIVE_WEB_APP_OK',exact:true}).waitFor({timeout:45000});check('web app is genuinely running locally',true);
  const link=await dialog().getByRole('link',{name:'بازکردن در مرورگر ↗',exact:true}).getAttribute('href');check('direct web link is loopback only',/^http:\/\/127\.0\.0\.1:\d+\/$/.test(link));
  check('live URL actually responds',(await fetch(link).then(r=>r.text())).includes('LIVE_WEB_APP_OK'));
  await page.screenshot({path:path.join(out,'04-live-app.png')});
  const activity=await request('/local/activity');check('desktop shutdown tracks live app',activity.running.some(id=>id.startsWith('output:')));
  const deletion=await fetch(api.url+'/tasks/'+taskId+'?consent=true',{method:'DELETE',headers});check('live output prevents destructive conversation deletion',deletion.status===409);
  await dialog().getByRole('button',{name:'توقف خروجی',exact:true}).click();
  for(let i=0;i<30;i++){const state=await request('/local/activity');if(!state.running.some(id=>id.startsWith('output:')))break;await new Promise(r=>setTimeout(r,200));}
  check('Stop confirms the real server has ended',!(await request('/local/activity')).running.some(id=>id.startsWith('output:')));
  let stillOpen=false;try{await fetch(link,{signal:AbortSignal.timeout(1500)});stillOpen=true;}catch{}check('stopped preview URL no longer serves',!stillOpen);
  await page.emulateMedia({reducedMotion:'reduce'});
  for(const size of [{width:1440,height:900},{width:1024,height:640}]){await app.evaluate(({BrowserWindow},s)=>BrowserWindow.getAllWindows()[0].setContentSize(s.width,s.height),size);await page.screenshot({path:path.join(out,'05-controls-'+size.width+'.png')});check('output controls fit '+size.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  check('no renderer errors',!report.errors.length);
 }catch(e){report.errors.push(String(e));if(page)await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});throw e;}
 finally{
  if(api&&taskId)try{const info=await fetch(api.url+'/tasks/'+taskId+'/outputs',{headers}).then(r=>r.json());for(const s of info.sessions??[])await fetch(api.url+'/tasks/'+taskId+'/outputs/'+s.id+'/stop',{method:'POST',headers,body:'{}'});}catch{}
  if(app)await app.close();report.passed=report.checks.length>0&&report.checks.every(c=>c.passed)&&!report.errors.length;fs.writeFileSync(path.join(out,'smoke.json'),JSON.stringify(report,null,2));
 }
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1});
