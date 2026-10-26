const {_electron:electron}=require('playwright');
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'checks/slash-skills');fs.mkdirSync(out,{recursive:true});
const tmp=fs.mkdtempSync(path.join(root,'.test-runs/slash-skills-'));
const env={...process.env,HARNESS_HOME:path.join(tmp,'home'),TEMP:tmp,TMP:tmp};delete env.ELECTRON_RUN_AS_NODE;
const report={checks:[],errors:[],scope:'Actual Electron/API, isolated profile; slash selection does not execute skill instructions.'};
const check=(name,ok)=>{report.checks.push({name,passed:!!ok});if(!ok)throw Error(name)};
(async()=>{
 let app,page;
 try{
  const dev=process.env.HARNESS_TEST_DEV==='1',exe=process.env.HARNESS_TEST_EXE||(dev?require('electron'):path.join(root,'release/dist/win-unpacked/Bridge Coding Harness.exe'));
  app=await electron.launch({executablePath:exe,args:[...(dev?[root]:[]),'--user-data-dir='+path.join(tmp,'desktop')],env,timeout:45000});
  await app.evaluate(({dialog})=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});});
  report.identity=await app.evaluate(({app})=>({version:app.getVersion(),packaged:app.isPackaged}));
  page=await app.firstWindow();page.on('pageerror',e=>report.errors.push(String(e)));
  await page.getByRole('button',{name:'رد کردن',exact:true}).click();await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor();const origin=page.url();
  const api=await page.evaluate(()=>window.desktop.api),headers={Authorization:'Bearer '+api.token,'Content-Type':'application/json'};
  const request=async(route,method='GET',data)=>{const r=await fetch(api.url+route,{method,headers,...(data?{body:JSON.stringify(data)}:{})});if(!r.ok)throw Error(route+' '+await r.text());return r.json()};
  const project=path.join(tmp,'project');fs.mkdirSync(project);await request('/workspace','POST',{path:project});
  const create=name=>request('/skills/create','POST',{name,description:'Review only the requested code.',instructions:'SLASH_TEST_ONLY. Do not run commands.',confirm:true});
  await create('alpha-review');await create('beta-check');await page.reload();await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor();
  const composer=()=>page.getByRole('textbox',{name:'پیام به ایجنت',exact:true}),list=()=>page.getByRole('listbox',{name:'مهارت‌های قابل فراخوانی'});
  await composer().fill('/');await list().getByRole('option').first().waitFor();
  check('slash lists enabled skills',await list().getByRole('option').count()===2);
  await page.screenshot({path:path.join(out,'01-home-menu.png')});
  await composer().press('ArrowDown');await composer().press('Enter');
  check('arrows and Enter insert without submitting',await composer().inputValue()==='/beta-check '&&(await request('/tasks')).items.length===0);
  await composer().fill('/alpha');await list().getByRole('option').waitFor();check('typing filters results',await list().getByRole('option').count()===1);
  await composer().press('Tab');check('Tab selects a matching skill',await composer().inputValue()==='/alpha-review ');
  await composer().fill('کمک /be ادامه');await composer().evaluate(el=>el.setSelectionRange(7,7));await composer().dispatchEvent('keyup',{key:'Shift'});
  await list().getByRole('option',{name:/^\/beta-check/}).waitFor();await list().getByRole('option',{name:/^\/beta-check/}).click();
  check('mouse selection preserves Persian request and suffix',await composer().inputValue()==='کمک /beta-check  ادامه');
  await composer().fill('/');await list().waitFor();await composer().press('Escape');check('Escape closes suggestions without clearing text',await list().count()===0&&await composer().inputValue()==='/');
  await composer().fill('src/main');check('paths do not open skill menu',await list().count()===0);
  await composer().fill('/missing');await page.getByText('مهارتی با این نام پیدا نشد.',{exact:true}).waitFor();await composer().press('Enter');
  check('unmatched Enter does not submit by mistake',(await request('/tasks')).items.length===0);
  const task=(await request('/tasks','POST',{prompt:'Create a short plan',read_only:true})).task;
  await request('/tasks/'+task.id+'/plan-proposals','POST',{});
  for(let i=0;i<120;i++){const t=await request('/tasks/'+task.id);if(!['queued','planning'].includes(t.status))break;await new Promise(r=>setTimeout(r,250));}
  await create('later-skill');await page.goto(new URL('/tasks?task='+task.id,origin).toString());
  await composer().fill('/');await list().getByRole('option').first().waitFor();
  check('existing conversation lists pinned skills only',await list().getByRole('option',{name:/alpha-review/}).count()===1&&await list().getByRole('option',{name:/later-skill/}).count()===0);
  await page.screenshot({path:path.join(out,'02-task-menu.png')});
  await composer().fill('/beta');await list().getByRole('option').waitFor();
  await composer().dispatchEvent('keydown',{key:'Enter',code:'Enter',isComposing:true});check('IME confirmation does not select or submit',await composer().inputValue()==='/beta');
  await composer().press('Enter');check('task composer also inserts skill',await composer().inputValue()==='/beta-check ');
  await composer().fill('/alpha');await list().getByRole('option').waitFor();
  for(const size of [{width:1440,height:900},{width:1024,height:640}]){
   await app.evaluate(({BrowserWindow},s)=>BrowserWindow.getAllWindows()[0].setContentSize(s.width,s.height),size);
   await list().getByRole('option').first().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'03-menu-'+size.width+'.png')});
   check('menu visible without horizontal overflow '+size.width,await list().isVisible()&&await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
  check('active descendant references a real option',await composer().evaluate(el=>!!document.getElementById(el.getAttribute('aria-activedescendant'))));
  check('no renderer errors',!report.errors.length);
 }catch(e){report.errors.push(String(e));if(page)await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});throw e;}
 finally{if(app)await app.close();report.passed=report.checks.length>0&&report.checks.every(c=>c.passed)&&!report.errors.length;fs.writeFileSync(path.join(out,'smoke.json'),JSON.stringify(report,null,2));}
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1});
