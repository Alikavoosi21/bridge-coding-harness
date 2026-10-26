const {_electron:electron}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'checks/performance');fs.mkdirSync(out,{recursive:true});
const tmp=fs.mkdtempSync(path.join(root,'.test-runs/performance-ui-'));
const env={...process.env,HARNESS_HOME:path.join(tmp,'home'),TEMP:tmp,TMP:tmp};delete env.ELECTRON_RUN_AS_NODE;
const report={checks:[],errors:[],scope:'Isolated desktop, actual API/LangGraph persistence, controlled burst streaming model; no paid-provider speed claim.'};
const baseline=process.env.BRIDGE_PERF_BASELINE==='1';
const check=(name,ok)=>{report.checks.push({name,passed:!!ok});if(!ok)throw Error(name)};
(async()=>{
 let app,page,provider,readinessReturned=false;
 try{
  const text='word '.repeat(1000);
  provider=http.createServer((req,res)=>{let raw='';req.on('data',c=>raw+=c);req.on('end',()=>{
   const input=JSON.parse(raw);res.setHeader('Content-Type','text/event-stream');
   const chunk=(delta,finish_reason=null)=>res.write('data: '+JSON.stringify({id:'perf-stream',object:'chat.completion.chunk',created:1,model:input.model,choices:[{index:0,delta,finish_reason}]})+'\n\n');
   chunk({role:'assistant',content:''});for(let i=0;i<1000;i++)chunk({content:'word '});chunk({},'stop');res.end('data: [DONE]\n\n');
  })});await new Promise(r=>provider.listen(0,'127.0.0.1',r));
  const start=performance.now(),dev=process.env.HARNESS_TEST_DEV==='1';
  app=await electron.launch({executablePath:process.env.HARNESS_TEST_EXE||(dev?require('electron'):path.join(root,'release/dist/win-unpacked/Bridge Coding Harness.exe')),args:[...(dev?[root]:[]),'--user-data-dir='+path.join(tmp,'desktop')],env,timeout:45000});
  await app.evaluate(({dialog})=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});});
  report.identity=await app.evaluate(({app})=>({version:app.getVersion(),packaged:app.isPackaged}));page=await app.firstWindow();page.on('pageerror',e=>report.errors.push(String(e)));
  await page.getByRole('button',{name:'رد کردن',exact:true}).click();await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor();report.cold_launch_ms=Math.round(performance.now()-start);
  const api=await page.evaluate(()=>window.desktop.api),headers={Authorization:'Bearer '+api.token,'Content-Type':'application/json'};
  const request=async(route,method='GET',body)=>{const r=await fetch(api.url+route,{method,headers,...(body?{body:JSON.stringify(body)}:{})});if(!r.ok)throw Error(route+' '+await r.text());return r.json()};
  const project=path.join(tmp,'project');fs.mkdirSync(project);await request('/workspace','POST',{path:project});
  const model=await request('/models','POST',{model:'perf-stream',base_url:'http://127.0.0.1:'+provider.address().port+'/v1',api_key:'fixture-key',streaming:true});await request('/models/'+model.id+'/default','POST',{});
  await page.route('**/readiness',async route=>{await new Promise(r=>setTimeout(r,3000));await route.continue();readinessReturned=true;});
  const reloadStart=performance.now();await page.reload();await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor();report.shell_with_slow_readiness_ms=Math.round(performance.now()-reloadStart);
  if(!baseline)check('shell is usable before slow Docker readiness finishes',!readinessReturned);
  await page.getByRole('textbox',{name:'پیام به ایجنت',exact:true}).fill('فقط یک پاسخ متنی بده؛ برنامه یا ابزار لازم نیست.');
  if(!baseline)check('draft editable while readiness is pending',await page.getByRole('button',{name:'در حال بررسی محیط…',exact:true}).isDisabled());
  await page.screenshot({path:path.join(out,baseline?'baseline-shell.png':'shell-before-readiness.png')});
  await page.getByRole('button',{name:'شروع کار',exact:true}).waitFor({timeout:20000});
  const runStart=performance.now();await page.getByRole('button',{name:'شروع کار',exact:true}).click();
  await page.waitForURL(/task=task_/);const taskId=new URL(page.url()).searchParams.get('task');let task;
  for(let i=0;i<150;i++){task=await request('/tasks/'+taskId);if(['closed','failed'].includes(task.status))break;await new Promise(r=>setTimeout(r,100));}
  report.streaming_complete_ms=Math.round(performance.now()-runStart);check('burst response completes successfully',task.status==='closed');
  const events=(await request('/tasks/'+taskId+'/events?limit=2000')).items;const deltas=events.filter(e=>e.type==='text_delta');
  check('all 1000 chunks are preserved exactly',deltas.map(e=>e.payload.delta).join('')===text);
  report.persisted_text_frames=deltas.length;if(!baseline)check('text commits reduced without dropping content',deltas.length<100);
  check('stream completes within a generous local regression budget',report.streaming_complete_ms<(baseline?60000:15000));
  await page.getByRole('button',{name:'بازبینی تغییرها',exact:true}).waitFor();
  for(const size of [{width:1440,height:900},{width:1024,height:640}]){await app.evaluate(({BrowserWindow},s)=>BrowserWindow.getAllWindows()[0].setContentSize(s.width,s.height),size);await page.screenshot({path:path.join(out,(baseline?'baseline-':'')+'stream-'+size.width+'.png')});check('responsive stream view '+size.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  check('no renderer errors',!report.errors.length);await request('/models/'+model.id,'DELETE');
 }catch(e){report.errors.push(String(e));if(page)await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});throw e;}
 finally{if(app)await app.close();if(provider)await new Promise(r=>provider.close(r));report.passed=report.checks.length>0&&report.checks.every(c=>c.passed)&&!report.errors.length;fs.writeFileSync(path.join(out,baseline?'desktop-before.json':'desktop.json'),JSON.stringify(report,null,2));}
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1});
