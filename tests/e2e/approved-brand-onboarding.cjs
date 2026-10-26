// Verify approved artwork, actual Windows executable icon, and the coding setup flow.
const {_electron:electron}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),sharp=require('sharp');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..');
const output=path.join(root,'checks/brand-onboarding');fs.mkdirSync(output,{recursive:true});
const temporary=fs.mkdtempSync(path.join(root,'.test-runs/brand-flow-'));
const env={...process.env,HARNESS_HOME:path.join(temporary,'home'),TEMP:temporary,TMP:temporary};delete env.ELECTRON_RUN_AS_NODE;
const report={checks:[],errors:[],scope:'Actual Windows packaged icon and UI; real setup API, demo explicitly selected, no real provider claim'};
const check=(name,value)=>{report.checks.push({name,passed:!!value});if(!value)throw Error(name)};
(async()=>{
 let app,page;
 try{
  const executable=process.env.HARNESS_TEST_EXE||path.join(root,'release/dist/win-unpacked/Bridge Coding Harness.exe');
  report.executable=executable;
  app=await electron.launch({executablePath:executable,args:['--user-data-dir='+path.join(temporary,'desktop')],env,timeout:45000});
  report.version=await app.evaluate(({app})=>app.getVersion());
  check('actual product version 0.2.1',report.version==='0.2.1');
  // The fixture alone may close on an unexpected assertion; never leave a
  // native close-confirmation dialog waiting in an automated test.
  await app.evaluate(({dialog})=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});});
  // Extract the actual PE icon through Windows. Electron getFileIcon may
  // return the generic .exe file-association icon instead of the embedded mark.
  const preview=path.join(output,'actual-windows-exe-icon.png');
  const extracted=spawnSync('powershell.exe',['-NoProfile','-Command',"Add-Type -AssemblyName System.Drawing; $icon=[System.Drawing.Icon]::ExtractAssociatedIcon($env:BRIDGE_ICON_TARGET); $icon.ToBitmap().Save($env:BRIDGE_ICON_PREVIEW)"],{env:{...env,BRIDGE_ICON_TARGET:executable,BRIDGE_ICON_PREVIEW:preview},encoding:'utf8',windowsHide:true});
  if(extracted.status!==0)throw Error(extracted.stderr);
  const iconBytes=fs.readFileSync(preview);
  const {data,info}=await sharp(iconBytes).ensureAlpha().raw().toBuffer({resolveWithObject:true});let green=0,blue=0;
  for(let i=0;i<data.length;i+=info.channels){if(data[i+3]<100)continue;if(data[i+1]>data[i]*1.25&&data[i+1]>data[i+2]*1.25&&data[i+1]>100)green++;if(data[i+2]>data[i+1]*1.3&&data[i+2]>100)blue++;}
  check('Windows executable icon is green, not blue',green>8&&blue===0);
  const approved=fs.readFileSync(path.join(root,'docs/design-reference/brand/bridge-symbol-brand.svg'),'utf8');
  const used=fs.readFileSync(path.join(root,'public/brand/approved-bridge.svg'),'utf8');
  check('logo geometry exactly matches approved design system',approved.match(/d="M40[^\"]+"/)[0]===used.match(/d="M40[^\"]+"/)[0]);
  for(const state of ['loading','executing','approval','correcting','success'])check('approved '+state+' GIF preserved',fs.readFileSync(path.join(root,'public/motion/bridge-'+state+'.gif')).equals(fs.readFileSync(path.join(root,'docs/design-reference/motion/'+state+'.gif'))));
  page=await app.firstWindow();page.on('pageerror',error=>report.errors.push(String(error)));
  let started=0;page.on('request',request=>{if(request.method()==='POST'&&/\/tasks(?:$|\/.*(?:executions|continuations))/.test(new URL(request.url()).pathname))started++});
  await page.getByRole('heading',{name:'تسک را بسپار. تغییر را خودت تأیید کن.'}).waitFor();
  await page.evaluate(()=>localStorage.setItem('onboarding-seen','1'));await page.reload();
  await page.getByRole('heading',{name:'تسک را بسپار. تغییر را خودت تأیید کن.'}).waitFor();
  check('upstream introduction flag cannot hide product onboarding',true);
  const titles=['تسک را بسپار. تغییر را خودت تأیید کن.','اول برنامه، بعد تغییر.','پروژه‌ات را برای اولین تسک آماده کن.'];
  for(let index=0;index<3;index++){
   await page.getByRole('heading',{name:titles[index],exact:true}).waitFor();
   for(const size of [{width:1440,height:900},{width:1024,height:640}]){
    await app.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows()[0].setContentSize(size.width,size.height),size);
    await page.waitForTimeout(100);
    check('onboarding '+index+' RTL and no overflow '+size.width,await page.evaluate(()=>document.documentElement.dir==='rtl'&&document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(output,`intro-${index+1}-${size.width}.png`)});
   }
   if(index<2)await page.getByRole('button',{name:'بعدی',exact:true}).click();
  }
  await page.getByRole('button',{name:'راه‌اندازی پروژه',exact:true}).click();
  await page.getByRole('heading',{name:'مخزن کدت را باز کن',exact:true}).waitFor();
  check('product intro completion persisted',await page.evaluate(()=>localStorage.getItem('bridge-coding-intro-v2')==='1'));
  const folder=path.join(temporary,'coding-project');fs.mkdirSync(folder);fs.writeFileSync(path.join(folder,'main.py'),'print("fixture only")');
  await app.evaluate(({dialog},folder)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[folder]});},folder);
  await page.getByRole('button',{name:'انتخاب پوشه',exact:true}).click();
  await page.getByRole('heading',{name:'مدل کدنویسی را وصل کن',exact:true}).waitFor();
  check('model setup has its own add-model action',await page.getByRole('button',{name:'تعریف مدل تازه',exact:true}).isVisible());
  await page.getByRole('button',{name:'محیط و بررسی',exact:true}).click();
  await page.getByRole('heading',{name:'محیط اجرا و تست را آماده کن',exact:true}).waitFor();
  await page.getByRole('button',{name:'بازبینی',exact:true}).click();
  await page.getByRole('heading',{name:'پروژه، مدل و دسترسی‌ها را مرور کن',exact:true}).waitFor();
  check('no legacy business/runner copy in review',!(/اجراکنندهٔ قدیمی|T006|Onboard Harness|مارکتینگ|حسابداری/.test(await page.locator('body').innerText())));
  const acknowledgements=page.getByRole('checkbox');check('four explicit disclosures',await acknowledgements.count()===4);
  for(let i=0;i<4;i++)await acknowledgements.nth(i).check();
  await page.getByRole('button',{name:'پایان راه‌اندازی',exact:true}).click();
  await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟',exact:true}).waitFor();
  check('setup reaches actual coding workspace',true);
  check('onboarding and setup never execute a task',started===0);
  await page.screenshot({path:path.join(output,'coding-workspace.png')});
  check('no renderer errors',report.errors.length===0);
 }catch(error){report.errors.push(String(error));if(page)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});throw error;}
 finally{if(app)await app.close();report.passed=report.checks.length>0&&report.checks.every(row=>row.passed)&&report.errors.length===0;fs.writeFileSync(path.join(output,'smoke.json'),JSON.stringify(report,null,2));}
 console.log(JSON.stringify(report));
})().catch(error=>{console.error(error);process.exitCode=1});
