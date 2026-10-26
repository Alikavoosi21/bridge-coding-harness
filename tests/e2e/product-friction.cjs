const {_electron:electron}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'checks/product-friction');fs.mkdirSync(out,{recursive:true});
const tmp=fs.mkdtempSync(path.join(root,'.test-runs/product-friction-'));
const env={...process.env,HARNESS_HOME:path.join(tmp,'home'),TEMP:tmp,TMP:tmp};delete env.ELECTRON_RUN_AS_NODE;
const baseline=process.env.BRIDGE_BASELINE==='1';
const report={checks:[],errors:[],scope:'Real Electron, API, Deep Agents and Docker; controlled local model, isolated project/profile.'};
const check=(name,passed)=>{report.checks.push({name,passed:!!passed});if(!passed)throw Error(name)};
const title='ساخت login.html با تم آبی و سبک قدیمی';
const html='<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>ورود</title><style>body{background:#164b85;color:#fff;font:18px Tahoma;display:grid;place-items:center;min-height:95vh}form{background:#d9e6f2;color:#123;padding:32px;border:6px ridge #80b4df;box-shadow:8px 8px #092c50}label{display:block;margin:14px 0}input,button{font:inherit;padding:8px;max-width:100%;box-sizing:border-box}button{background:#1965ac;color:white;border:4px outset #78b5e5}</style><form><h1>ورود به حساب</h1><label>نام کاربری <input required autocomplete="username"></label><label>رمز عبور <input required type="password" autocomplete="current-password"></label><button>ورود</button></form></html>';
(async()=>{
 let app,page,provider,calls=0,written=false,completed=false,model;
 try{
  provider=http.createServer((req,res)=>{let raw='';req.on('data',c=>raw+=c);req.on('end',()=>{try{
   const body=JSON.parse(raw),probe=body.tools?.some(t=>t.function?.name==='report_capability');
   const tool=(name,args)=>({role:'assistant',content:'',tool_calls:[{id:'fixture-'+Date.now(),type:'function',function:{name,arguments:JSON.stringify(args)}}]});
   let message;
   if(probe)message=tool('report_capability',{ok:true});
   else{
    calls++;const executing=JSON.stringify(body.messages).includes('phase: execute_approved_plan');
    if(!executing){
     const planned=body.messages.some(m=>m.role==='tool'&&m.name==='write_todos');
     // Providers may omit tool name on tool messages; the assistant call remains durable.
     const hasPlan=planned||body.messages.some(m=>m.role==='assistant'&&m.tool_calls?.some(t=>t.function.name==='write_todos'));
     message=hasPlan?{role:'assistant',content:'یک فایل مستقل login.html با تم آبی و ظاهر قدیمی می‌سازم.'}:tool('write_todos',{todos:[{content:title,status:'pending'}]});
    }else if(!written){written=true;message=tool('write_file',{file_path:'/login.html',content:html});}
    else if(!completed){completed=true;message=tool('write_todos',{todos:[{content:title,status:'completed'}]});}
    else message={role:'assistant',content:'login.html آماده است. تغییرها را بازبینی و در پوشهٔ پروژه ذخیره کن.'};
   }
   res.setHeader('Content-Type','application/json');res.end(JSON.stringify({id:'fixture',object:'chat.completion',created:1,model:body.model,choices:[{index:0,message,finish_reason:message.tool_calls?'tool_calls':'stop'}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}}));
  }catch(e){res.statusCode=500;res.end(String(e));}})});await new Promise(r=>provider.listen(0,'127.0.0.1',r));
  const dev=process.env.HARNESS_TEST_DEV==='1';const exe=process.env.HARNESS_TEST_EXE||(dev?require('electron'):path.join(root,'release/dist/win-unpacked/Bridge Coding Harness.exe'));
  app=await electron.launch({executablePath:exe,args:[...(dev?[root]:[]),'--user-data-dir='+path.join(tmp,'desktop')],env,timeout:45000});
  await app.evaluate(({dialog})=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});});
  report.identity=await app.evaluate(({app})=>({version:app.getVersion(),packaged:app.isPackaged}));
  page=await app.firstWindow();page.on('pageerror',e=>report.errors.push(String(e)));
  await page.getByRole('button',{name:'رد کردن',exact:true}).click();await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor();const homeUrl=page.url();
  const api=await page.evaluate(()=>window.desktop.api),headers={Authorization:'Bearer '+api.token,'Content-Type':'application/json'};
  const request=async(route,method='GET',body)=>{const r=await fetch(api.url+route,{method,headers,...(body?{body:JSON.stringify(body)}:{})});if(!r.ok)throw Error(route+' '+await r.text());return r.json()};
  const project=path.join(tmp,'project');fs.mkdirSync(project);fs.writeFileSync(path.join(project,'unrelated.pdf'),'Do not read for a standalone HTML request.');
  await request('/workspace','POST',{path:project});model=await request('/models','POST',{model:'fixture-login',base_url:'http://127.0.0.1:'+provider.address().port+'/v1',api_key:'fixture-only',streaming:false});
  const probe=await request('/models/probe','POST',{id:model.id});check('model has real tool probe receipt',probe.tools===true||probe.capabilities?.tools===true);
  await request('/models/'+model.id+'/default','POST',{});await page.reload();await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor();
  await page.getByRole('button',{name:'شروع کار',exact:true}).waitFor();
  await page.screenshot({path:path.join(out,baseline?'01-before-home.png':'02-after-home.png')});
  if(baseline){check('reproduces read-only default despite ready environment',await page.getByRole('switch',{name:'فقط خواندن',exact:true}).isChecked());return;}
  check('ready environment starts with editing enabled',!await page.getByRole('switch',{name:'فقط خواندن',exact:true}).isChecked());
  const composer=page.getByRole('textbox',{name:'پیام به ایجنت',exact:true});await composer.fill('یک Html برای login طراحی کن که تم آبی و سبک قدیمی داشته باشد');await page.getByRole('button',{name:'شروع کار',exact:true}).click();
  await page.getByRole('button',{name:'تأیید برنامه و ادامه',exact:true}).waitFor({timeout:45000});
  check('waiting status explicitly says execution stopped',await page.getByText(/اجرا متوقف است/).isVisible());
  await page.getByRole('button',{name:'تأیید برنامه و ادامه',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'03-plan.png')});
  await page.getByRole('button',{name:'تأیید برنامه و ادامه',exact:true}).click();
  const tid=new URL(page.url()).searchParams.get('task');let task;
  for(let i=0;i<120;i++){task=await request('/tasks/'+tid);if(['closed','failed','awaiting_decision','awaiting_action'].includes(task.status))break;await new Promise(r=>setTimeout(r,500));}
  check('one plan approval completes actual file creation',task.status==='closed'&&written&&completed);
  check('finished runs have durable end timestamps',task.runs.every(r=>!['queued','active'].includes(r.state)&&r.ended_at));
  const events=await request('/tasks/'+tid+'/events?limit=2000');
  check('permission does not cause a repair loop',!events.items.some(e=>e.type==='repair_started'));
  check('no unrelated resource reads',!events.items.some(e=>e.type==='action_started'&&e.payload.tool==='read_file'&&String(e.payload.summary).includes('unrelated.pdf')));
  check('no repeated model loop',calls<=5);
  await page.getByText('login.html آماده است.',{exact:false}).waitFor();await page.screenshot({path:path.join(out,'04-result.png')});
  await page.getByRole('button',{name:'بازبینی تغییرها',exact:true}).click();await page.getByText('login.html',{exact:false}).first().waitFor();await page.screenshot({path:path.join(out,'05-review.png')});
  check('single output opens its diff without another selection',await page.getByLabel('تفاوت فایل',{exact:true}).isVisible());
  const actual=fs.readFileSync(path.join(env.HARNESS_HOME,'tasks',tid,'working','login.html'),'utf8');check('complete HTML exists in the real task working copy',actual===html);
  check('original project is unchanged until human apply',!fs.existsSync(path.join(project,'login.html')));
  // Inspect the real generated artifact with a separate browser window; never execute a user skill.
  const preview=await app.evaluate(({BrowserWindow},file)=>{const w=new BrowserWindow({show:true,width:1024,height:640,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});return w.loadFile(file).then(()=>w.id);},path.join(env.HARNESS_HOME,'tasks',tid,'working','login.html'));
  const artifact=app.windows().find(p=>p.url().startsWith('file:'));if(!artifact)throw Error('Artifact preview unavailable');
  await artifact.screenshot({path:path.join(out,'06-generated-login.png')});check('generated form renders',await artifact.getByRole('button',{name:'ورود',exact:true}).isVisible());
  await app.evaluate(({BrowserWindow},id)=>BrowserWindow.fromId(id)?.destroy(),preview);
  for(const size of [{width:1440,height:900},{width:1024,height:640}]){await app.evaluate(({BrowserWindow},s)=>BrowserWindow.getAllWindows()[0].setContentSize(s.width,s.height),size);await page.screenshot({path:path.join(out,'07-review-'+size.width+'.png')});check('no horizontal overflow at '+size.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  await page.getByRole('button',{name:'پیش‌نمایش 1 فایل منتخب',exact:true}).click();
  await page.getByRole('button',{name:'اعمال انتخاب روی اصل',exact:true}).click();
  await page.getByRole('dialog').getByRole('checkbox').check();
  await page.getByRole('button',{name:'تأیید و اعمال روی پروژهٔ اصلی',exact:true}).click();
  for(let i=0;i<40&&!fs.existsSync(path.join(project,'login.html'));i++)await new Promise(r=>setTimeout(r,200));
  check('human apply actually delivers HTML into selected project',fs.readFileSync(path.join(project,'login.html'),'utf8')===html);
  await page.getByRole('heading',{name:'نتیجهٔ اعمال روی پروژهٔ اصلی',exact:true}).waitFor();
  await page.getByText('اعمال شد',{exact:true}).first().waitFor();await page.screenshot({path:path.join(out,'08-delivered.png')});
  await page.goto(new URL('/tasks?task='+tid,homeUrl).toString());
  await page.getByRole('textbox',{name:'پیام به ایجنت',exact:true}).fill('پیش‌نویس ذخیره‌نشدهٔ آزمایشی');await page.reload();
  check('unsent chat draft survives reload',await page.getByRole('textbox',{name:'پیام به ایجنت',exact:true}).inputValue()==='پیش‌نویس ذخیره‌نشدهٔ آزمایشی');
  // Recover an existing read-only conversation without recreating it or bypassing capability checks.
  const old=await request('/tasks','POST',{prompt:'Create login.html',read_only:true});await page.goto(new URL('/tasks?task='+old.task.id,homeUrl).toString());
  if(!page.url().includes(old.task.id))throw Error('Read-only navigation failed');
  await page.getByRole('button',{name:'فعال‌کردن ویرایش در نسخهٔ کاری',exact:true}).waitFor();await page.screenshot({path:path.join(out,'09-read-only-recovery.png')});
  await page.getByRole('button',{name:'فعال‌کردن ویرایش در نسخهٔ کاری',exact:true}).click();
  for(let i=0;i<20;i++){const state=await request('/tasks/'+old.task.id);if(!state.read_only){check('existing conversation can enable editing in place',true);break;}await new Promise(r=>setTimeout(r,100));if(i===19)throw Error('Editing access did not change');}
  check('no renderer errors',report.errors.length===0);
  await request('/models/'+model.id,'DELETE');
 }catch(e){report.errors.push(String(e));if(page)await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});throw e;}
 finally{if(app)await app.close();if(provider)await new Promise(r=>provider.close(r));report.model_calls=calls;report.passed=report.checks.length>0&&report.checks.every(c=>c.passed)&&!report.errors.length;fs.writeFileSync(path.join(out,baseline?'baseline.json':'smoke.json'),JSON.stringify(report,null,2));}
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1});
