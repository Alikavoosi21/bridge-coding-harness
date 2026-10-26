// Read/render real frontend against an isolated real FastAPI/SQLite fixture.
// No Docker, no provider keys, no modification of user settings or projects.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {spawn,spawnSync}=require('node:child_process');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../..');
const t010=process.argv.includes('--t010');
const data=process.argv.includes('--data');
const apply=process.argv.includes('--apply');
const repin=process.argv.includes('--repin');
const skills=process.argv.includes('--skills')||repin;
const partial=process.argv.includes('--partial');
const recovery=process.argv.includes('--recovery')||partial;
const changes=process.argv.includes('--changes')||apply||recovery;
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'onboard-t008-'));
const backend=path.join(root,'backend'),python=path.join(backend,'.venv/Scripts/python.exe');
const env={...process.env,HARNESS_HOME:path.join(tmp,'home'),HARNESS_TOKEN:'fixture-t008',PYTHONIOENCODING:'utf-8',PYTHONPATH:backend};
if(data)env.HARNESS_DATA_FIXTURE='1';
if(changes)env.HARNESS_CHANGES_FIXTURE='1';
if(apply||recovery)env.HARNESS_APPLY_FIXTURE='1';
if(recovery)env.HARNESS_RECOVERY_FIXTURE='1';
if(partial)env.HARNESS_PARTIAL_FIXTURE='1';
if(skills)env.HARNESS_SKILLS_FIXTURE='1';
if(repin)env.HARNESS_REPIN_FIXTURE='1';
if(t010){env.HARNESS_T010_FIXTURE='1';env.PYTHONPATH=backend+path.delimiter+__dirname;}
const output=path.resolve(root,'checks/phase-1/'+(t010?'t010':data?'data':repin?'repin':skills?'skills':partial?'partial':recovery?'recovery':apply?'apply':changes?'changes':'t008'));fs.mkdirSync(output,{recursive:true});
const seed=spawnSync(python,[path.join(__dirname,t010?'seed-t010.py':'seed-t008.py')],{cwd:backend,env,encoding:'utf8',windowsHide:true});
if(seed.status!==0)throw new Error(seed.stderr);
const fixture=JSON.parse(seed.stdout.trim());
if(t010)env.T010_TASKS=JSON.stringify(fixture);
const api='http://127.0.0.1:18766',origin='http://localhost:3211';
let server,frontend,browser,page,apiLog='';
const report={checks:[],errors:[],scope:'Real local API and fixture data; no real model/Docker confinement',screenshots:[]};
function check(name,ok){report.checks.push({name,passed:!!ok});if(!ok)throw new Error(name)}
async function waitApi(){for(let i=0;i<60;i++){try{const r=await fetch(api+'/health',{headers:{Authorization:'Bearer fixture-t008'}});if(r.ok)return}catch{}await new Promise(r=>setTimeout(r,250))}throw new Error('fixture backend startup failed')}
(async()=>{
 try{
  try { await fetch(origin); } catch {
   // Run the existing production build; never rebuild under a running dev server.
   frontend=spawn(process.execPath,[path.join(root,'scripts/serve-export.cjs'),'3211'],{cwd:root,env,windowsHide:true,stdio:'ignore'});
   for(let n=0;n<40;n++){try{if((await fetch(origin)).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  }
  try{await fetch(api+'/health');throw new Error('Test port 18766 already in use')}catch(e){if(e.message.includes('already'))throw e}
  server=spawn(python,['-m','uvicorn',t010?'t010_fixture:create_app':'server.app:create_app','--factory','--host','127.0.0.1','--port','18766','--log-level','error'],{cwd:backend,env,windowsHide:true,stdio:['ignore','ignore','pipe']});
  server.stderr.on('data',b=>apiLog+=b.toString());await waitApi().catch(error=>{throw new Error(error.message+'\n'+apiLog.slice(-4500))});
  if(!t010){
   // Startup correctly recovers orphaned executions. This UI-only live journal
   // must therefore be staged AFTER startup; it is not an actual running model.
   const staged=spawnSync(python,['-c',"import sys; from server.storage import Store; Store().set_task_status(sys.argv[1], 'executing', reason='UI-only live journal fixture after startup')",fixture.live],{cwd:backend,env,encoding:'utf8',windowsHide:true});
   if(staged.status!==0)throw new Error(staged.stderr);
  }
  const executablePath=['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
  browser=await chromium.launch({executablePath,headless:true});
  page=await browser.newPage({viewport:{width:1440,height:900}});
  page.on('pageerror',e=>report.errors.push(String(e)));
  await page.addInitScript(({api})=>{window.desktop={isDesktop:true,platform:'win32',api:{url:api,token:'fixture-t008'},setTheme:()=>{}}},{api});
  // Inspect the selected atlas pages as well as the live implementation.
  await page.goto('file:///'+path.resolve(root,'../docs/coding-harness-design/product-design-atlas.html').replaceAll('\\','/')+(t010?'#P06':'#P04'));
  await page.getByRole('heading',{name:t010?/P06.*درخواست تأیید/:/P.*برنامه/}).waitFor();
  await page.screenshot({path:path.join(output,t010?'reference-P06.png':'reference-P04.png')});
  if(data){await require('./data-walkthrough.cjs')({page,fixture,api,origin,output,env,check});}else if(repin){await require('./repin-walkthrough.cjs')({page,fixture,api,origin,output,check});}else if(skills){await require('./skills-walkthrough.cjs')({page,fixture,api,origin,output,check});}else if(recovery){await require('./recovery-walkthrough.cjs')({page,fixture,api,origin,output,check});}else if(apply){await require('./apply-walkthrough.cjs')({page,fixture,api,origin,output,env,check});}else if(changes){await require('./changes-walkthrough.cjs')({page,fixture,origin,output,check});}else if(t010){await require('./t010-walkthrough.cjs')({page,fixture,api,origin,output,env,check,report});}else{
  for(const viewport of [{width:1440,height:900},{width:1024,height:640}]){
   await page.setViewportSize(viewport);
   await page.goto(origin);
   if(viewport.width===1440)await page.getByRole('button',{name:'رد کردن',exact:true}).click();
   await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor({timeout:15000});
   const styles=await page.evaluate(()=>({rtl:document.documentElement.dir,font:getComputedStyle(document.body).fontFamily,bg:getComputedStyle(document.body).backgroundColor,overflow:document.documentElement.scrollWidth>innerWidth}));
   report.checks.push({name:'home styles '+viewport.width,passed:styles.rtl==='rtl'&&!styles.overflow,styles});
   await page.screenshot({path:path.join(output,`P02-${viewport.width}.png`)});
   await page.goto(origin+'/tasks');await page.getByRole('heading',{name:'کارها',exact:true}).waitFor();
   await page.locator('main').getByRole('button',{name:/بررسی ساختار پروژه/}).click();
   await page.getByRole('tab',{name:'گفتگو',exact:true}).waitFor();
   await page.getByText('برنامه آمادهٔ بازبینی است. فقط فایل‌های پروژه خوانده می‌شوند.',{exact:true}).waitFor();
   check('task no page overflow '+viewport.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:path.join(output,`P04-${viewport.width}.png`)});
   await page.getByRole('tab',{name:'فعالیت',exact:true}).click();
   await page.getByRole('tab',{name:'برنامهٔ کار',exact:true}).click();
   check('plan accessible '+viewport.width,await page.getByText('خواندن فایل راهنما',{exact:true}).first().isVisible());
   await page.reload();await page.getByRole('tab',{name:'گفتگو',exact:true}).waitFor();
   await page.getByText('برنامه آمادهٔ بازبینی است. فقط فایل‌های پروژه خوانده می‌شوند.',{exact:true}).waitFor();
   check('reload transcript once '+viewport.width,await page.getByText('برنامه آمادهٔ بازبینی است. فقط فایل‌های پروژه خوانده می‌شوند.',{exact:true}).count()===1);
  }
  // SDK resolves failed POSTs via onError: the draft must survive that path.
  await page.goto(origin+'/tasks?task='+fixture.task);
  const composer=page.getByRole('textbox',{name:'پیام به ایجنت',exact:true});await composer.waitFor();
  const attempts=[];let reject=true;
  await page.route(api+'/tasks/'+fixture.task+'/plan-proposals',async route=>{
   attempts.push(route.request().postDataJSON().idempotency_key);
   if(reject){reject=false;await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{code:'temporarily_unavailable',message:'Fixture rejection',retryable:true}})});}
   else await route.continue();
  });
  await composer.fill('فقط فایل راهنما را بررسی کن');await composer.press('Enter');
  await page.getByRole('alert').filter({hasText:'پیام هنوز تأیید ذخیره ندارد'}).waitFor();
  check('SDK rejected acceptance keeps draft',await composer.inputValue()==='فقط فایل راهنما را بررسی کن');
  await composer.press('Enter');await page.waitForFunction(()=>document.querySelector('main textarea')?.value==='');
  check('retry uses same durable identity',attempts.length===2&&attempts[0]===attempts[1]);
  const headers={Authorization:'Bearer fixture-t008'};
  const accepted=await fetch(api+'/tasks/'+fixture.task,{headers}).then(r=>r.json());
  check('retry stored exactly one correction',accepted.messages.filter(m=>m.parts.some(p=>p.text==='فقط فایل راهنما را بررسی کن')).length===1);
  await page.unroute(api+'/tasks/'+fixture.task+'/plan-proposals');
  // Live journal fixture: streaming must allow steering without another subscriber.
  let subscriptions=0;
  page.on('request',r=>{if(r.url().includes('/tasks/'+fixture.live+'/events')&&r.headers().accept?.includes('text/event-stream'))subscriptions++});
  await page.goto(origin+'/tasks?task='+fixture.live);await composer.waitFor();
  await page.getByText(/گام 39:/).waitFor();
  for(const width of [1440,1024]){await page.setViewportSize({width,height:width===1440?900:640});await page.waitForTimeout(150);await page.screenshot({path:path.join(output,`P05-${width}.png`)});}
  check('stream permits steering',await page.getByRole('button',{name:'ارسال',exact:true}).isDisabled()===true);
  await composer.fill('راهنمای بعدی در حین اجرا');
  check('steering send enabled during stream',await page.getByRole('button',{name:'ارسال',exact:true}).isEnabled());
  await composer.press('Enter');await page.waitForFunction(()=>document.querySelector('main textarea')?.value==='');
  const live=await fetch(api+'/tasks/'+fixture.live,{headers}).then(r=>r.json());
  check('live steering durable once',live.messages.filter(m=>m.parts.some(p=>p.text==='راهنمای بعدی در حین اجرا')).length===1);
  check('one live subscriber during steering',subscriptions===1);
  // Interrupt the browser connection after acceptance; GET reconnect cannot resend POST.
  await page.context().setOffline(true);await page.context().setOffline(false);
  await page.reload();await composer.waitFor();await page.getByText('راهنمای بعدی در حین اجرا',{exact:true}).waitFor();
  check('accepted steering survives disconnect and reload once',await page.getByText('راهنمای بعدی در حین اجرا',{exact:true}).count()===1);
  const scroll=page.locator('main .overflow-y-auto').first();await scroll.evaluate(el=>{el.scrollTop=0;el.dispatchEvent(new Event('scroll'))});
  check('conversation can read earlier content',await scroll.evaluate(el=>el.scrollTop===0));
  const appended=spawnSync(python,['-c',"import sys; from server.storage import Store; Store().record_event(sys.argv[1], 'text_delta', {'message_id':'live-assistant','part_id':'live-assistant:text','offset':int(sys.argv[2]),'delta':'\\n\\nمتن تازه در حین خواندن گذشته'})",fixture.live,String(fixture.live_length)],{cwd:backend,env,encoding:'utf8',windowsHide:true});
  if(appended.status!==0)throw new Error(appended.stderr);
  await page.getByRole('button',{name:'پیام تازه',exact:false}).waitFor();
  check('new stream text preserves earlier scroll',await scroll.evaluate(el=>el.scrollTop===0));
  await page.getByRole('tab',{name:'گفتگو',exact:true}).focus();await page.keyboard.press('ArrowLeft');
  check('RTL tabs keyboard navigation',await page.getByRole('tab',{name:'فعالیت',exact:true}).getAttribute('aria-selected')==='true');
  await page.getByRole('tab',{name:'برنامهٔ کار',exact:true}).click();
  await page.goto(origin+'/tasks?task='+fixture.task);await page.getByRole('tab',{name:'برنامهٔ کار',exact:true}).click();
  await page.getByRole('button',{name:'ویرایش برنامه'}).first().click();
  const step=page.getByRole('textbox',{name:'عنوان گام 1',exact:true}).first();await step.fill('خواندن راهنما با ویرایش دستی');
  await page.getByRole('button',{name:'ذخیره',exact:true}).first().click();
  await page.getByText('خواندن راهنما با ویرایش دستی',{exact:true}).first().waitFor();
  const edited=await fetch(api+'/tasks/'+fixture.task,{headers}).then(r=>r.json());check('plan edited and persisted',edited.plan.steps[0].title==='خواندن راهنما با ویرایش دستی');
  check('paths render LTR',await page.locator('code[dir="ltr"]').count()>0);
  const patch=await fetch(api+'/tasks/'+fixture.task+'/plan',{method:'PATCH',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({expected_revision:edited.plan.revision,steps:[{title:'نسخهٔ تازهٔ برنامه'}],scope:['notes.md'],checks:[]})});
  check('concurrent plan update accepted',patch.ok);
  await page.getByRole('button',{name:'تأیید برنامه و ادامه',exact:true}).first().click();
  await page.getByText('برنامه تغییر کرده؛ بازبینی کنید',{exact:true}).first().waitFor();
  check('stale plan cannot execute',!(await fetch(api+'/tasks/'+fixture.task,{headers}).then(r=>r.json())).plan.approved_revision);
  await page.getByRole('button',{name:'بازبینی برنامه',exact:true}).first().click();
  await page.getByText('نسخهٔ تازهٔ برنامه',{exact:true}).first().waitFor();
  await page.getByRole('button',{name:'رد برنامه',exact:true}).first().click();
  await page.waitForTimeout(250);
  check('plan rejection persists',!(await fetch(api+'/tasks/'+fixture.task,{headers}).then(r=>r.json())).plan.approved_revision);
  await page.setViewportSize({width:1440,height:900});await page.goto(origin);
  await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor();
  const draft=page.locator('main textarea');await draft.fill('پیش‌نویس برای انتقال');
  await page.getByRole('button',{name:'فضای کاری',exact:true}).click();await page.getByRole('menuitem').filter({hasText:'پروژه دوم'}).click();
  await page.getByRole('dialog').waitFor();check('draft switch has three decisions',await page.getByRole('button',{name:'انصراف',exact:true}).isVisible());
  await page.getByRole('button',{name:'انصراف',exact:true}).click();check('cancel keeps draft',await draft.inputValue()==='پیش‌نویس برای انتقال');
  await page.getByRole('button',{name:'افزودن فایل مرجع',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:/notes.md/}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  check('reference selected',await page.getByRole('button',{name:/حذف مرجع/}).count()===1);
  await page.getByRole('button',{name:'فضای کاری',exact:true}).click();await page.getByRole('menuitem').filter({hasText:'پروژه دوم'}).click();await page.getByRole('button',{name:'انتقال متن',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('main textarea')?.value==='پیش‌نویس برای انتقال');check('transfer retains text in destination',true);
  check('reference not transferred',await page.getByRole('button',{name:/حذف مرجع/}).count()===0);
  await page.getByRole('button',{name:'فضای کاری',exact:true}).click();await page.getByRole('menuitem').filter({hasText:'پروژه نمونه'}).click();await page.getByRole('button',{name:'نگه‌داشتن در پروژهٔ فعلی',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('main textarea')?.value==='');check('keep leaves destination empty',true);
  await page.goto(origin+'/tasks?task='+fixture.task);await page.getByRole('tab',{name:'گفتگو',exact:true}).waitFor();
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.waitForFunction(()=>[...document.querySelectorAll('img[src*="/motion/"]')].every(i=>i.src.includes('poster')));check('reduced motion poster',true);
  check('no page errors',report.errors.length===0);
  }
 } catch (error) { report.errors.push(String(error)); if(page){await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});console.error((await page.locator('body').innerText().catch(()=>'' )).slice(0,5000));} throw error; } finally {
  if(browser)await browser.close();
  if(server){server.kill();await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));}
  if(frontend){frontend.kill();await new Promise(r=>frontend.exitCode!==null?r():frontend.once('exit',r));}
  const resolved=path.resolve(tmp);if(path.dirname(resolved)===path.resolve(os.tmpdir())&&path.basename(resolved).startsWith('onboard-t008-'))fs.rmSync(resolved,{recursive:true,force:true});
  report.passed=report.checks.length>0&&report.checks.every(c=>c.passed)&&!report.errors.length;
  fs.writeFileSync(path.join(output,'smoke.json'),JSON.stringify(report,null,2));
 }
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1});
