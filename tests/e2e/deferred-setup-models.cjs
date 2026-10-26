const {_electron:electron}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'../..'),output=path.join(root,'checks/deferred-models');fs.mkdirSync(output,{recursive:true});
const temp=fs.mkdtempSync(path.join(root,'.test-runs/deferred-'));
const env={...process.env,HARNESS_HOME:path.join(temp,'home'),TEMP:temp,TMP:temp};delete env.ELECTRON_RUN_AS_NODE;
const report={checks:[],errors:[],scope:'Installed UI and real backend, local fixture provider/catalog and fake test key; no paid provider claim'};
const check=(name,value)=>{report.checks.push({name,passed:!!value});if(!value)throw Error(name)};
(async()=>{
 let app,page,provider;let catalogCalls=0,modelCalls=0;
 try{
  provider=http.createServer((req,res)=>{
   if(req.url==='/v1/chat/completions'&&req.headers.authorization==='Bearer fixture-key'){
    let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{
     const input=JSON.parse(body);if(input.model==='coding-model-two')modelCalls++;
     res.setHeader('Content-Type','application/json');res.end(JSON.stringify({id:'fixture-completion',object:'chat.completion',created:1,model:input.model,choices:[{index:0,message:{role:'assistant',content:'Fixture provider invoked through the selected model.'},finish_reason:'stop'}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}}));
    });return;
   }
   if(req.url==='/v1/models'&&req.headers.authorization==='Bearer fixture-key'){
    catalogCalls++;res.setHeader('Content-Type','application/json');res.end(JSON.stringify({data:[{id:'coding-model-one'},{id:'coding-model-two'}]}));
   }else {res.writeHead(401);res.end('rejected fixture key');}
  });await new Promise(resolve=>provider.listen(0,'127.0.0.1',resolve));
  const endpoint='http://127.0.0.1:'+provider.address().port+'/v1';
  const development=process.env.HARNESS_TEST_DEV==='1';
  const executable=process.env.HARNESS_TEST_EXE||(development?require('electron'):path.join(root,'release/dist/win-unpacked/Bridge Coding Harness.exe'));
  app=await electron.launch({executablePath:executable,args:[...(development?[root]:[]),'--user-data-dir='+path.join(temp,'desktop')],env,timeout:45000});
  report.identity=await app.evaluate(({app})=>({version:app.getVersion(),packaged:app.isPackaged,source:app.getAppPath()}));
  await app.evaluate(({dialog})=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false})});
  page=await app.firstWindow();page.on('pageerror',error=>report.errors.push(String(error)));
  await page.getByRole('button',{name:'رد کردن',exact:true}).click();
  await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟',exact:true}).waitFor();
  check('skip introduction enters app without folder',true);
  check('cannot start coding without folder',await page.getByRole('button',{name:'شروع کار',exact:true}).isDisabled());
  await page.reload();await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟',exact:true}).waitFor();
  check('deferred setup survives reload',true);
  await page.getByRole('button',{name:'ادامهٔ راه‌اندازی',exact:true}).click();
  await page.getByRole('heading',{name:'مخزن کدت را باز کن',exact:true}).waitFor();
  await page.getByRole('button',{name:'بعداً تنظیم می‌کنم',exact:true}).click();
  await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟',exact:true}).waitFor();
  check('folder step can be skipped without fake completion',true);
  const api=await page.evaluate(()=>window.desktop.api),headers={Authorization:'Bearer '+api.token};
  const setup=await fetch(api.url+'/settings',{headers}).then(r=>r.json());
  check('defer does not invent setup completion or disclosure consent',setup.setup.deferred&&!setup.setup.completed&&!setup.workspace.open&&Object.values(setup.setup.acknowledgements).every(v=>v===false));
  await page.getByRole('link',{name:'اتصال مدل',exact:true}).click();
  await page.getByRole('button',{name:'تعریف مدل',exact:true}).click();
  await page.getByRole('textbox',{name:'Base URL',exact:true}).fill(endpoint);
  await page.getByRole('textbox',{name:'API Key',exact:true}).fill('fixture-key');
  await page.getByRole('button',{name:'دریافت مدل‌های سرویس',exact:true}).click();
  await page.getByRole('listbox',{name:'مدل‌های سرویس',exact:true}).selectOption('coding-model-two');
  check('key retrieves models from chosen provider',catalogCalls===1);
  check('selected catalog id populates actual model field',await page.getByRole('textbox',{name:'Model Name',exact:true}).inputValue()==='coding-model-two');
  await page.screenshot({path:path.join(output,'provider-model-picker.png')});
  await page.getByRole('button',{name:'ذخیره',exact:true}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  const models=await fetch(api.url+'/models',{headers}).then(r=>r.json());
  const saved=models.find(m=>m.model==='coding-model-two');
  check('selected model and key saved and defaulted',saved?.has_key&&saved?.is_default&&saved?.base_url===endpoint);
  check('key never returned in public models API',!JSON.stringify(models).includes('fixture-key'));
  check('key absent from settings file',!fs.readFileSync(path.join(temp,'home/settings.json'),'utf8').includes('fixture-key'));
  // Nonstreaming fixture tests the actual selected-provider call, not only UI state.
  await fetch(api.url+'/models',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({...saved,streaming:false})});
  const folder=path.join(temp,'sample-project');fs.mkdirSync(folder);fs.writeFileSync(path.join(folder,'main.py'),'print("fixture")');
  await fetch(api.url+'/workspace',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({path:folder})});
  const created=await fetch(api.url+'/tasks',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({prompt:'Say hello without using tools.',read_only:true})}).then(r=>r.json());
  const proposed=await fetch(api.url+'/tasks/'+created.task.id+'/plan-proposals',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:'{}'});
  check('selected provider enters real harness',proposed.ok);
  let settled;
  for(let n=0;n<200;n++){
   settled=await fetch(api.url+'/tasks/'+created.task.id,{headers}).then(r=>r.json());
   if(['closed','failed','awaiting_plan'].includes(settled.status))break;
   await new Promise(resolve=>setTimeout(resolve,100));
  }
  check('harness invokes selected model with entered key',modelCalls>0&&settled.status==='closed'&&settled.outcome==='completed');
  for(const size of [{width:1440,height:900},{width:1024,height:640}]){
   await app.evaluate(({BrowserWindow},s)=>BrowserWindow.getAllWindows()[0].setContentSize(s.width,s.height),size);
   check('no overflow '+size.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
  check('no renderer errors',report.errors.length===0);
  await fetch(api.url+'/models/'+saved.id,{method:'DELETE',headers});
 }catch(e){report.errors.push(String(e));if(page)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});throw e;}
 finally{if(app)await app.close();if(provider)await new Promise(resolve=>provider.close(resolve));report.passed=report.checks.length>0&&report.checks.every(c=>c.passed)&&!report.errors.length;fs.writeFileSync(path.join(output,'smoke.json'),JSON.stringify(report,null,2));}
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1});
