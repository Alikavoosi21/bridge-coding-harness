const path=require('node:path');
module.exports=async({page,fixture,origin,output,check})=>{
 await page.goto(origin);
 await page.getByRole('button',{name:'رد کردن',exact:true}).click();
 await page.goto(origin+'/tasks?task='+fixture.task+'&view=changes');
 await page.getByRole('heading',{name:/بازبینی تغییرها/}).waitFor();
 const file=page.getByRole('button',{name:/notes.md/});await file.click();
 await page.getByText(/Changed working fixture/).waitFor();
 check('file navigation does not select apply',!await page.getByRole('checkbox',{name:/انتخاب notes.md/}).isChecked());
 for(const viewport of [{width:1440,height:900},{width:1024,height:640}]){
  await page.setViewportSize(viewport);await page.screenshot({path:path.join(output,`P08-${viewport.width}.png`)});
  check('review fits '+viewport.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 }
 await page.getByRole('checkbox',{name:'دوستونه',exact:true}).check();
 await page.locator('.cm-mergeView').waitFor();
 check('aligned diff has two readonly editors',await page.locator('.cm-mergeView .cm-editor').count()===2&&await page.locator('.cm-mergeView [contenteditable="true"]').count()===0);
 check('aligned diff highlights real changes',await page.locator('.cm-insertedLine,.cm-deletedLine').count()>0);
 await page.screenshot({path:path.join(output,'P08-side-1024.png')});
 await page.getByRole('checkbox',{name:'دوستونه',exact:true}).uncheck();
 await page.getByRole('button',{name:'ویرایش نسخهٔ کاری',exact:true}).click();
 const editor=page.locator('.cm-content');await editor.click();await page.keyboard.press('Control+a');await page.keyboard.type('Human fixture edit.');
 await page.getByRole('button',{name:'بازگشت به گفتگو'}).click();
 await page.getByRole('dialog').waitFor();await page.getByRole('button',{name:'ماندن',exact:true}).click();
 check('dirty exit retains text',await editor.innerText()==='Human fixture edit.');
 await page.getByRole('button',{name:'ذخیره',exact:true}).click();
 await page.getByText(/Human fixture edit/).waitFor();
 check('real API manual save shown in diff',await page.locator('pre').innerText().then(value=>value.includes('+Human fixture edit.')));
 await page.getByRole('checkbox',{name:/انتخاب notes.md/}).check();
 await page.getByRole('button',{name:/پیش‌نمایش 1 فایل منتخب/}).click();
 // The readonly fixture has no canonical verification profile: no invented quality.
 await page.getByRole('alert').filter({hasText:/پروفایل بررسی/}).waitFor();
 check('preview missing profile is not success',await page.getByRole('alert').count()>0);
 // Consent UI against controlled candidate responses. Actual Docker remains unverified.
 const selectionUrl='/tasks/'+fixture.task+'/apply-previews';
 let checkRequests=0,quality='not_verified';
 await page.route('**'+selectionUrl,route=>route.fulfill({json:{id:'selection-ui-fixture',quality_status:'not_verified',file_ids:['fixture-file']}}));
 await page.route('**'+selectionUrl+'/selection-ui-fixture',route=>route.fulfill({json:{id:'selection-ui-fixture',quality_status:quality,check_refs:[],candidate_manifest_hash:'a'.repeat(64),required_commands:[{id:'tests',command:'python check.py'}]}}));
 await page.route('**'+selectionUrl+'/selection-ui-fixture/checks',async route=>{
  checkRequests++;const body=route.request().postDataJSON();
  check('candidate consent sends exact command list',body.confirm===true&&body.approved_commands.length===1&&body.approved_commands[0]==='python check.py');
  quality='failed';await route.fulfill({json:{selection_id:'selection-ui-fixture',quality_status:'failed',check_refs:[]}});
 });
 await page.getByRole('button',{name:/پیش‌نمایش 1 فایل منتخب/}).click();
 await page.getByRole('button',{name:'بررسی همین انتخاب',exact:true}).click();
 await page.getByRole('dialog').getByText('python check.py').waitFor();
 check('opening consent does not execute',checkRequests===0);
 await page.getByRole('button',{name:'انصراف',exact:true}).click();
 check('canceling consent does not execute',checkRequests===0);
 await page.getByRole('button',{name:'بررسی همین انتخاب',exact:true}).click();
 await page.getByRole('button',{name:'تأیید و اجرای همین فرمان‌ها',exact:true}).click();
 await page.getByText('بررسی این نسخه ناموفق بود',{exact:true}).waitFor();
 await page.getByRole('dialog').waitFor({state:'hidden'});
 check('failed candidate never becomes success',checkRequests===1);
 await page.screenshot({path:path.join(output,'P08-candidate-failed-1024.png')});
 // UI-only status projection cases; no fake claim of a real runtime stop.
 let simulated={status:'executing',read_only:false};
 const taskUrl=new RegExp('/tasks/'+fixture.task+'$');
 await page.route(taskUrl,async route=>{
  const response=await route.fetch();const data=await response.json();
  await route.fulfill({response,json:{...data,...simulated}});
 });
 await page.reload();await page.getByRole('button',{name:/notes.md/}).click();
 await page.getByRole('button',{name:'توقف برای ویرایش',exact:true}).waitFor();
 check('active task editor is disabled',await page.getByRole('button',{name:'ویرایش نسخهٔ کاری',exact:true}).isDisabled());
 simulated={status:'stopping',read_only:false};
 await page.getByText('در انتظار تأیید توقف محیط؛ ویرایش هنوز بسته است.').waitFor();
 check('stopping is not editable',await page.getByRole('button',{name:'ویرایش نسخهٔ کاری',exact:true}).isDisabled());
 simulated={status:'paused',read_only:true};
 await page.getByText('این کار فقط‌خواندنی است؛ ویرایش فعال نیست.').waitFor();
 check('readonly does not offer manual mutation',await page.getByRole('button',{name:'ویرایش نسخهٔ کاری',exact:true}).isDisabled());
 await page.unroute(taskUrl);
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.screenshot({path:path.join(output,'P08-edited-1024.png')});
};
