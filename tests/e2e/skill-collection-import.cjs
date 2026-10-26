const {_electron:electron}=require('playwright');
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../..'),output=path.join(root,'checks/skill-import');fs.mkdirSync(output,{recursive:true});
const temporary=fs.mkdtempSync(path.join(root,'.test-runs/collection-import-'));
const collection=process.env.BRIDGE_TEST_SKILL_COLLECTION||'C:/Users/msi/Downloads/mattpocock-main/mattpocock-main';
const env={...process.env,HARNESS_HOME:path.join(temporary,'home'),TEMP:temporary,TMP:temporary};delete env.ELECTRON_RUN_AS_NODE;
const report={checks:[],errors:[],scope:'Actual user-provided collection, read-only source, isolated app profile; no skill instructions executed'};
const check=(name,passed)=>{report.checks.push({name,passed:!!passed});if(!passed)throw Error(name)};
(async()=>{
 let app,page;
 try{
  const development=process.env.HARNESS_TEST_DEV==='1',exe=process.env.HARNESS_TEST_EXE||(development?require('electron'):path.join(root,'release/dist/win-unpacked/Bridge Coding Harness.exe'));
  app=await electron.launch({executablePath:exe,args:[...(development?[root]:[]),'--user-data-dir='+path.join(temporary,'desktop')],env,timeout:45000});
  report.identity=await app.evaluate(({app})=>({version:app.getVersion(),packaged:app.isPackaged}));
  await app.evaluate(({dialog},collection)=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});dialog.showOpenDialog=async()=>({canceled:false,filePaths:[collection]});},collection);
  page=await app.firstWindow();page.on('pageerror',error=>report.errors.push(String(error)));
  await page.getByRole('button',{name:'رد کردن',exact:true}).click();await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor();
  const api=await page.evaluate(()=>window.desktop.api),project=path.join(temporary,'project');fs.mkdirSync(project);
  const workspace=await fetch(api.url+'/workspace',{method:'POST',headers:{Authorization:'Bearer '+api.token,'Content-Type':'application/json'},body:JSON.stringify({path:project})});
  if(!workspace.ok)throw Error('Fixture workspace failed');
  await page.reload();await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor();
  await page.getByRole('button',{name:'مهارت',exact:true}).click();await page.getByRole('button',{name:'انتخاب پوشهٔ Skill',exact:true}).click();
  await page.getByRole('textbox',{name:'جستجوی مهارت‌های مجموعه',exact:true}).waitFor();
  check('parent collection discovers nested skills',await page.getByText(/37 مهارت پیدا شد/).isVisible());
  await page.getByRole('textbox',{name:'جستجوی مهارت‌های مجموعه',exact:true}).fill('grilling');
  await page.getByRole('button',{name:/^grilling/}).click();
  const body=await page.getByRole('textbox',{name:'دستور مهارت',exact:true}).inputValue();
  const source=fs.readFileSync(path.join(collection,'skills/productivity/grilling/SKILL.md'),'utf8');
  check('full actual skill body appears in preview',body===source.split('---').slice(2).join('---').trim());
  check('name and description were parsed',await page.getByRole('textbox',{name:'نام مهارت',exact:true}).inputValue()==='grilling'&&(await page.getByRole('textbox',{name:'کاربرد مهارت',exact:true}).inputValue()).length>0);
  check('activation requires explicit trust',await page.getByRole('button',{name:'ذخیره و فعال‌سازی'}).isDisabled());
  await page.screenshot({path:path.join(output,'actual-skill-preview.png')});
  await page.getByRole('checkbox').check();await page.getByRole('button',{name:'ذخیره و فعال‌سازی'}).click();await page.getByRole('dialog').waitFor({state:'hidden'});
  check('selected real skill can be mentioned from composer',(await page.getByRole('textbox',{name:'پیام به ایجنت',exact:true}).inputValue()).includes('/grilling'));
  check('original skill content unchanged',source===fs.readFileSync(path.join(collection,'skills/productivity/grilling/SKILL.md'),'utf8'));
  await page.getByRole('button',{name:'مهارت',exact:true}).click();
  const standalone=path.join(temporary,'SKILL.md');fs.writeFileSync(standalone,'---\nname: standalone-test\ndescription: Test import only.\n---\n\nSTANDALONE_FILE_BODY');
  await page.getByLabel('واردکردن فایل مهارت',{exact:true}).setInputFiles(standalone);
  await page.getByRole('textbox',{name:'دستور مهارت',exact:true}).waitFor();
  check('SKILL.md file directly loads its body',await page.getByRole('textbox',{name:'دستور مهارت',exact:true}).inputValue()==='STANDALONE_FILE_BODY');
  await page.getByRole('textbox',{name:'دستور مهارت',exact:true}).fill('Edited file import body');
  check('standalone imported text can be edited',true);
  check('no renderer errors',report.errors.length===0);
 }catch(e){report.errors.push(String(e));if(page)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});throw e;}
 finally{if(app)await app.close();report.passed=report.checks.length>0&&report.checks.every(c=>c.passed)&&!report.errors.length;fs.writeFileSync(path.join(output,'smoke.json'),JSON.stringify(report,null,2));}
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1});
