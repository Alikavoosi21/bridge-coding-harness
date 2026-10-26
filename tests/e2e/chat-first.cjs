const {_electron:electron}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'../..'),output=path.join(root,'checks/chat-first');fs.mkdirSync(output,{recursive:true});
const tmp=fs.mkdtempSync(path.join(root,'.test-runs/chat-first-'));
const env={...process.env,HARNESS_HOME:path.join(tmp,'home'),TEMP:tmp,TMP:tmp};delete env.ELECTRON_RUN_AS_NODE;
const report={checks:[],errors:[],scope:'Actual desktop/API/Deep Agents with local controlled provider; no paid-model quality claim'};
const check=(name,passed)=>{report.checks.push({name,passed:!!passed});if(!passed)throw Error(name)};
(async()=>{
 let app,page,provider;let scenario='answer',calls=0,skillRead=false,skillLoaded=false,planMade=false;const toolNames=[];
 try{
  provider=http.createServer((req,res)=>{let body='';req.on('data',c=>body+=c);req.on('end',()=>{
   const input=JSON.parse(body);calls++;let message={role:'assistant',content:scenario==='followup'?'پاسخ دوم در همین گفتگو.':scenario==='skill'?'مهارت خوانده شد.':'سلام؛ چه کمکی نیاز داری؟'};
   if(scenario==='skill'&&!skillRead){skillRead=true;message={role:'assistant',content:'',tool_calls:[{id:'read-skill-'+calls,type:'function',function:{name:'read_file',arguments:JSON.stringify({file_path:'/.harness/skills/brief-helper/SKILL.md'})}}]};toolNames.push('read_file');}
   else if(scenario==='skill')skillLoaded=input.messages.some(m=>m.role==='tool'&&String(m.content).includes('SKILL_BODY_FOR_ACTUAL_LOAD'));
   if(scenario==='plan'&&!planMade){planMade=true;message={role:'assistant',content:'',tool_calls:[{id:'plan-'+calls,type:'function',function:{name:'write_todos',arguments:JSON.stringify({todos:[{content:'اصلاح تابع نمونه',status:'pending'}]})}}]};toolNames.push('write_todos');}
   else if(scenario==='plan')message={role:'assistant',content:'برنامه برای بررسی آماده است.'};
   res.setHeader('Content-Type','application/json');res.end(JSON.stringify({id:'fixture-'+calls,object:'chat.completion',created:1,model:input.model,choices:[{index:0,message,finish_reason:message.tool_calls?'tool_calls':'stop'}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}}));
  })});await new Promise(r=>provider.listen(0,'127.0.0.1',r));
  const development=process.env.HARNESS_TEST_DEV==='1';const exe=process.env.HARNESS_TEST_EXE||(development?require('electron'):path.join(root,'release/dist/win-unpacked/Bridge Coding Harness.exe'));
  app=await electron.launch({executablePath:exe,args:[...(development?[root]:[]),'--user-data-dir='+path.join(tmp,'desktop')],env,timeout:45000});
  await app.evaluate(({dialog})=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});});
  report.identity=await app.evaluate(({app})=>({version:app.getVersion(),packaged:app.isPackaged}));
  page=await app.firstWindow();page.on('pageerror',e=>report.errors.push(String(e)));
  await page.getByRole('button',{name:'رد کردن',exact:true}).click();await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor();
  const api=await page.evaluate(()=>window.desktop.api),headers={Authorization:'Bearer '+api.token,'Content-Type':'application/json'};
  const post=async(route,body)=>{const res=await fetch(api.url+route,{method:'POST',headers,body:JSON.stringify(body)});if(!res.ok)throw Error(route+' '+await res.text());return res.json();};
  const folder=path.join(tmp,'project');fs.mkdirSync(folder);fs.writeFileSync(path.join(folder,'main.py'),'print("fixture")');fs.writeFileSync(path.join(folder,'private-unrelated.txt'),'Must not read this for a greeting.');
  await post('/workspace',{path:folder});const model=await post('/models',{model:'fixture-chat',base_url:'http://127.0.0.1:'+provider.address().port+'/v1',api_key:'fixture-key',streaming:false});
  await fetch(api.url+'/settings',{method:'PUT',headers,body:JSON.stringify({default_model:model.id})});await page.reload();await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor();
  await page.getByRole('button',{name:'مهارت',exact:true}).click();await page.getByRole('button',{name:'افزودن مهارت',exact:true}).click();
  await page.getByRole('textbox',{name:'نام مهارت',exact:true}).fill('brief-helper');await page.getByRole('textbox',{name:'کاربرد مهارت',exact:true}).fill('Use when explicitly requested.');await page.getByRole('textbox',{name:'دستور مهارت',exact:true}).fill('SKILL_BODY_FOR_ACTUAL_LOAD: answer briefly.');
  await page.getByRole('checkbox').check();await page.getByRole('button',{name:'ذخیره و فعال‌سازی',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});
  const composer=()=>page.getByRole('textbox',{name:'پیام به ایجنت',exact:true});
  check('create skill inserts callable mention without sending', (await composer().inputValue()).includes('/brief-helper')&&calls===0);
  await composer().fill('سلام');await page.getByRole('button',{name:'شروع کار',exact:true}).click();
  await page.getByText('سلام؛ چه کمکی نیاز داری؟',{exact:true}).waitFor({timeout:45000});
  check('direct answer without reading project resources',calls===1&&toolNames.length===0);
  check('no task inspector column',await page.getByRole('complementary',{name:'جزئیات کار'}).count()===0);
  const taskId=new URL(page.url()).searchParams.get('task');
  scenario='followup';await composer().fill('ساده‌تر توضیح بده');await composer().press('Enter');await page.getByText('پاسخ دوم در همین گفتگو.',{exact:true}).waitFor({timeout:45000});
  check('followup stays in the same conversation',new URL(page.url()).searchParams.get('task')===taskId);
  scenario='skill';await page.getByRole('button',{name:'مهارت',exact:true}).click();await page.getByRole('button',{name:'/brief-helper',exact:false}).click();await composer().press('Enter');
  await page.getByText('مهارت خوانده شد.',{exact:true}).waitFor({timeout:45000});check('skill is invoked through real file tool',skillRead&&skillLoaded);
  scenario='plan';await composer().fill('یک برنامه برای اصلاح کد بده');await composer().press('Enter');await page.getByText('برنامه برای بررسی آماده است.',{exact:true}).waitFor({timeout:45000});
  check('plan review appears inside conversation',await page.locator('#panel-conversation').getByRole('button',{name:'تأیید برنامه و ادامه',exact:true}).isVisible());
  for(const size of [{width:1440,height:900},{width:1024,height:640}]){
   await app.evaluate(({BrowserWindow},s)=>BrowserWindow.getAllWindows()[0].setContentSize(s.width,s.height),size);
   await page.waitForTimeout(100);
   check('single chat fits '+size.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.locator('#panel-conversation').getByRole('button',{name:'تأیید برنامه و ادامه',exact:true}).scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(output,'chat-'+size.width+'.png')});
  }
  await page.screenshot({path:path.join(output,'inline-plan.png')});
  const attachment=path.join(tmp,'provided.txt');fs.writeFileSync(attachment,'Explicitly attached by user.');
  await page.getByLabel('بارگذاری پیوست',{exact:true}).setInputFiles(attachment);await page.getByText(/provided.txt/).first().waitFor();
  await page.getByRole('link',{name:'پیوست‌ها',exact:true}).click();await page.getByText(/provided.txt/).first().waitFor();
  check('attachments page excludes existing repository resources',!((await page.locator('main').innerText()).includes('private-unrelated.txt')));
  check('no renderer errors',report.errors.length===0);
  await fetch(api.url+'/models/'+model.id,{method:'DELETE',headers});
 }catch(e){report.errors.push(String(e));if(page)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});throw e;}
 finally{if(app)await app.close();if(provider)await new Promise(r=>provider.close(r));report.passed=report.checks.length>0&&report.checks.every(c=>c.passed)&&!report.errors.length;fs.writeFileSync(path.join(output,'smoke.json'),JSON.stringify(report,null,2));}
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1});
