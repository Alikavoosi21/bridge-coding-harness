// Actual packaged Electron + frozen API. Isolated data; no model key or Docker claims.
const { _electron:electron }=require('playwright');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const root=path.resolve(__dirname,'../..');
const output=path.resolve(root,'checks/phase-2',process.env.HARNESS_TEST_LABEL||'packaged');
fs.mkdirSync(output,{recursive:true});
const temporary=fs.mkdtempSync(path.join(root,'.test-runs','packaged-'));
const report={checks:[],scope:'Actual packaged Electron and PyInstaller API; demo only',errors:[]};
const check=(name,value)=>{report.checks.push({name,passed:!!value});if(!value)throw Error(name)};
(async()=>{
 let app;
 try{
  const executable=process.env.HARNESS_TEST_EXE||path.join(root,'release/dist/win-unpacked/Bridge Coding Harness.exe');
  const env={...process.env,HARNESS_HOME:path.join(temporary,'home'),TEMP:temporary,TMP:temporary};delete env.ELECTRON_RUN_AS_NODE;
  app=await electron.launch({executablePath:executable,args:['--user-data-dir='+path.join(temporary,'electron')],env,timeout:45000});
  const page=await app.firstWindow();page.on('pageerror',error=>report.errors.push(String(error)));
  const identity=await app.evaluate(({app})=>({name:app.getName(),data:app.getPath('userData'),packaged:app.isPackaged}));
  report.identity=identity;
  check('Bridge packaged identity',identity.name==='Bridge Coding Harness'&&identity.packaged);
  check('explicit isolated desktop profile',path.resolve(identity.data)===path.join(temporary,'electron'));
  await page.waitForLoadState('domcontentloaded');
  await page.waitForFunction(()=>Boolean(window.desktop?.api?.url),{timeout:30000});
  const api=await page.evaluate(()=>window.desktop.api);
  const headers={Authorization:'Bearer '+api.token};
  for(let n=0;n<100;n++){try{if((await fetch(api.url+'/health',{headers})).ok)break}catch{}await new Promise(resolve=>setTimeout(resolve,200))}
  check('frozen API health',(await fetch(api.url+'/health',{headers})).ok);
  const workspace=path.join(temporary,'project');fs.mkdirSync(workspace);fs.writeFileSync(path.join(workspace,'notes.md'),'Packaged fixture only.');
  check('frozen workspace API',(await fetch(api.url+'/workspace',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({path:workspace})})).ok);
  const ready=await fetch(api.url+'/readiness',{headers}).then(response=>response.json());
  check('demo is explicitly disclosed',ready.model.demo===true);
  check('frozen backend uses independent Bridge image',ready.runtime.image==='bridge-coding-sandbox:0.2');
  if(process.env.HARNESS_REQUIRE_DOCKER==='1')check('installed backend detects real Docker',ready.runtime.available===true);
  const createdResponse=await fetch(api.url+'/tasks',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({prompt:'Read notes.md and propose a plan without changing files.'})});
  check('frozen task creation',createdResponse.ok);
  const created=(await createdResponse.json()).task;
  check('new task defaults to read-only',created.read_only===true);
  const proposal=await fetch(api.url+'/tasks/'+created.id+'/plan-proposals',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:'{}'});
  check('frozen planning endpoint',proposal.ok);
  let planned;
  for(let n=0;n<150;n++){
   planned=await fetch(api.url+'/tasks/'+created.id,{headers}).then(response=>response.json());
   if(planned.status==='awaiting_plan'||['failed','closed','recovery_required'].includes(planned.status))break;
   await new Promise(resolve=>setTimeout(resolve,100));
  }
  check('frozen Deep Agents produces persisted demo plan',planned.status==='awaiting_plan'&&planned.plan.steps.length>0);
  const preview=await fetch(api.url+'/diagnostics/preview',{headers}).then(response=>response.json());
  check('frozen dependencies and diagnostics',preview.report.packages.deepagents!=='unavailable');
  for(const viewport of [{width:1440,height:900},{width:1024,height:640}]){
   await app.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows()[0].setContentSize(size.width,size.height),viewport);
   await page.waitForTimeout(300);
   check('packaged RTL '+viewport.width,await page.evaluate(()=>document.documentElement.dir==='rtl'));
   check('packaged no horizontal overflow '+viewport.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:path.join(output,'desktop-'+viewport.width+'.png')});
  }
  check('no renderer errors',report.errors.length===0);
  const stopped=await fetch(api.url+'/local/shutdown',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({confirm:true})}).then(response=>response.json());
  check('frozen shutdown confirms idle',stopped.stopped===true);
 }finally{
  if(app)await app.close();
  report.passed=report.checks.length>0&&report.checks.every(row=>row.passed)&&!report.errors.length;
  fs.writeFileSync(path.join(output,'desktop-smoke.json'),JSON.stringify(report,null,2));
 }
 console.log(JSON.stringify(report));
})().catch(error=>{console.error(error);process.exitCode=1});
