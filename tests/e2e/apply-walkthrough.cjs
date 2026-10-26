const fs=require('node:fs'),path=require('node:path');
module.exports=async({page,fixture,api,origin,output,env,check})=>{
 let applies=0,restores=0;
 page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/apply'))applies++;if(request.method()==='POST'&&request.url().endsWith('/restores'))restores++});
 await page.goto(origin);await page.getByRole('button',{name:'رد کردن',exact:true}).click();
 await page.goto(origin+'/tasks?task='+fixture.task+'&view=changes');
 await page.getByRole('checkbox',{name:/انتخاب notes.md/}).check();
 await page.getByRole('button',{name:/پیش‌نمایش 1 فایل منتخب/}).click();
 await page.getByRole('button',{name:'اعمال انتخاب روی اصل',exact:true}).click();
 const dialog=page.getByRole('dialog');await dialog.waitFor();
 const confirm=page.getByRole('button',{name:'تأیید و اعمال روی پروژهٔ اصلی',exact:true});
 check('unverified apply requires explicit acknowledgement',await confirm.isDisabled());
 check('opening apply dialog does not apply',applies===0);
 for(const viewport of [{width:1440,height:900},{width:1024,height:640}]){await page.setViewportSize(viewport);await page.screenshot({path:path.join(output,`P09-${viewport.width}.png`)})}
 await dialog.getByRole('checkbox').check();await confirm.click();
 await page.getByRole('heading',{name:'نتیجهٔ اعمال روی پروژهٔ اصلی',exact:true}).waitFor();
 await page.getByText('اصل فعلی با candidate یکسان است.',{exact:true}).waitFor();
 check('apply changes real fixture original once',applies===1&&fs.readFileSync(path.join(fixture.workspace,'notes.md'),'utf8')==='Changed working fixture.');
 check('unverified result does not invent successful checks',await page.getByText('بررسی موفق معتبر ندارد',{exact:true}).count()>0);
 await page.reload();await page.getByRole('heading',{name:'نتیجهٔ اعمال روی پروژهٔ اصلی',exact:true}).waitFor();
 check('result reload does not repeat apply',applies===1);
 for(const viewport of [{width:1440,height:900},{width:1024,height:640}]){await page.setViewportSize(viewport);await page.screenshot({path:path.join(output,`P10-${viewport.width}.png`)});check('result fits '+viewport.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))}
 await page.getByRole('button',{name:'پیش‌نمایش بازگردانی همین عملیات',exact:true}).click();
 const restore=page.getByRole('checkbox',{name:'بازگردانی notes.md',exact:true});await restore.waitFor();
 check('restore has no implicit selected file',!await restore.isChecked());
 await restore.check();await page.getByRole('button',{name:'تأیید بازگردانی 1 فایل',exact:true}).click();
 await page.getByRole('status').filter({hasText:'نتیجهٔ بازگردانی: بازگردانده شد'}).waitFor();
 check('restore returns exact original bytes once',restores===1&&fs.readFileSync(path.join(fixture.workspace,'notes.md'),'utf8')==='Local fixture. No secrets.');
 await page.screenshot({path:path.join(output,'P10-restored-1024.png')});
 await page.reload();await page.getByRole('heading',{name:'نتیجهٔ اعمال روی پروژهٔ اصلی',exact:true}).waitFor();
 check('reload never repeats restore',restores===1&&applies===1);
 await page.getByText('نتیجهٔ بازگردانی ثبت‌شده: بازگردانده شد',{exact:true}).waitFor();
 check('restore receipt survives reload',restores===1);
 fs.writeFileSync(path.join(fixture.workspace,'notes.md'),'User concurrent edit.','utf8');
 await page.goto(origin+'/tasks?task='+fixture.task+'&view=changes&file=notes.md');
 await page.getByRole('region',{name:'سه نسخهٔ فایل متعارض'}).waitFor();
 await page.getByText('User concurrent edit.',{exact:true}).waitFor();
 check('conflict cannot be selected for apply',await page.getByRole('checkbox',{name:/انتخاب notes.md/}).isDisabled());
 check('three conflict versions are readonly',await page.locator('.cm-editor').count()===3&&await page.locator('.cm-editor [contenteditable="true"]').count()===0);
 check('conflict editors use dark readable surface',await page.locator('.cm-editor').evaluateAll(editors=>editors.every(editor=>{const styles=getComputedStyle(editor);const rgb=value=>(value.match(/\d+/g)||[]).slice(0,3).map(Number).reduce((sum,n)=>sum+n,0);return rgb(styles.backgroundColor)<240&&rgb(styles.color)>360})));
 for(const viewport of [{width:1440,height:900},{width:1024,height:640}]){await page.setViewportSize(viewport);await page.screenshot({path:path.join(output,`P08-conflict-${viewport.width}.png`)});check('conflict fits '+viewport.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))}
 check('conflict viewing preserves user bytes',fs.readFileSync(path.join(fixture.workspace,'notes.md'),'utf8')==='User concurrent edit.');
 await page.goto(origin+'/tasks');
 await page.getByRole('listitem').filter({hasText:'بررسی ساختار پروژه بدون تغییر فایل'}).getByRole('button',{name:'تاریخچه و نسخهٔ کاری',exact:true}).click();
 await page.getByRole('region',{name:'نسخه‌ها و نتایج کار'}).waitFor();
 await page.getByRole('link',{name:'بازکردن نسخهٔ کاری و تغییرها',exact:true}).waitFor();
 check('history discovers working copy without execution',await page.getByRole('link',{name:'بازکردن نسخهٔ کاری و تغییرها',exact:true}).count()>0);
 const {spawnSync}=require('node:child_process');
 const python=path.resolve(__dirname,'../../backend/.venv/Scripts/python.exe');
 const seed=spawnSync(python,['-c',[
  'import sys',
  'from server.storage import Store',
  'from harness.worktrees.diff import working_file',
  'from harness.worktrees.edit import save_working_file',
  'from harness.task_runtime import task_directory',
  'store=Store(); task_id=sys.argv[1]',
  "opened=working_file(store,task_id,'notes.md')",
  'original=store.set_action_state',
  'def interrupt(identifier,state,**kwargs):',
  " if state=='succeeded':raise OSError('browser fixture interrupted edit')",
  ' return original(identifier,state,**kwargs)',
  'store.set_action_state=interrupt',
  'try:',
  " save_working_file(store,task_id,path='notes.md',content='Requested interrupted edit.',expected_revision=opened['working_revision'],expected_manifest_hash=opened['working_manifest_hash'],expected_file_hash=opened['hash'],key='browser-interrupted')",
  'except OSError:pass',
  "(task_directory(store,task_id)/'working'/'notes.md').write_text('Later user working bytes.',encoding='utf8')"
 ].join('\n'),fixture.task],{cwd:path.resolve(__dirname,'../../backend'),env,encoding:'utf8',windowsHide:true});
 if(seed.status!==0)throw new Error(seed.stderr||String(seed.error));
 await page.goto(origin+'/tasks?task='+fixture.task);
 const recovery=page.getByRole('region',{name:'بازیابی ویرایش دستی'});await recovery.waitFor();
 await recovery.getByText('Later user working bytes.',{exact:true}).waitFor();
 const keep=recovery.getByRole('button',{name:'پذیرش نسخهٔ فعلی ویرایش دستی',exact:true});
 check('manual recovery requires explicit consent',await keep.isDisabled());
 for(const viewport of [{width:1440,height:900},{width:1024,height:640}]){
  await page.setViewportSize(viewport);await page.emulateMedia({reducedMotion:'reduce'});
  await recovery.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'P11-manual-recovery-'+viewport.width+'.png')});
  check('manual recovery fits '+viewport.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await keep.scrollIntoViewIfNeeded();
  check('recovery decision reachable '+viewport.width,await keep.evaluate(element=>element.getBoundingClientRect().bottom<=innerHeight));
  const composer=page.getByRole('textbox',{name:'پیام به ایجنت',exact:true});
  await composer.scrollIntoViewIfNeeded();
  check('composer reachable during recovery '+viewport.width,await composer.evaluate(element=>element.getBoundingClientRect().bottom<=innerHeight));
 }
 await recovery.getByRole('checkbox').check();await keep.focus();await page.keyboard.press('Enter');
 await recovery.waitFor({state:'detached'});
 check('manual recovery preserves later working and original bytes',fs.readFileSync(path.join(env.HARNESS_HOME,'tasks',fixture.task,'working','notes.md'),'utf8')==='Later user working bytes.'&&fs.readFileSync(path.join(fixture.workspace,'notes.md'),'utf8')==='User concurrent edit.');
 await page.reload();check('recovery reload never repeats apply or restore',applies===1&&restores===1);

};
