const fs=require('node:fs'),path=require('node:path');
module.exports=async({page,fixture,api,origin,output,check})=>{
 let acknowledgements=0,writeRequests=0;
 page.on('request',request=>{if(request.method()==='POST'&&request.url().includes('/reconciliations'))acknowledgements++;if(request.method()==='POST'&&/\/(apply|restores)$/.test(request.url()))writeRequests++});
 await page.goto(origin);await page.getByRole('button',{name:'رد کردن',exact:true}).click();
 await page.goto(origin+'/tasks?task='+fixture.task+'&view=result&operation='+fixture.recovery_operation);
 await page.getByRole('heading',{name:'نتیجهٔ اعمال روی پروژهٔ اصلی',exact:true}).waitFor();
 await page.getByText(fixture.recovery_state==='partial'?'اعمال ناقص':'نتیجه نامعلوم',{exact:true}).first().waitFor();
 if(fixture.recovery_state==='partial'){
  const snapshot=await fetch(api+'/tasks/'+fixture.task+'/apply-operations/'+fixture.recovery_operation,{headers:{Authorization:'Bearer fixture-t008'}}).then(response=>response.json());
  check('partial keeps separate applied and conflicting files',snapshot.files.some(file=>file.state==='applied')&&snapshot.files.some(file=>file.state==='conflict'));
 }
 check('unknown does not offer premature restore',await page.getByRole('button',{name:'پیش‌نمایش بازگردانی همین عملیات',exact:true}).count()===0);
 check('loading unknown does not repeat effects',writeRequests===0&&acknowledgements===0);
 for(const viewport of [{width:1440,height:900},{width:1024,height:640}]){
  await page.setViewportSize(viewport);await page.emulateMedia({reducedMotion:'reduce'});
  await page.screenshot({path:path.join(output,`P10-${fixture.recovery_state??'unknown'}-${viewport.width}.png`)});
  check('unknown result fits '+viewport.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 }
 const keep=page.getByRole('button',{name:'نسخهٔ فعلیِ مشاهده‌شده را می‌پذیرم؛ ادامهٔ اعمال نده',exact:true});
 await keep.focus();check('recovery decision is keyboard focusable',await keep.evaluate(element=>element===document.activeElement));
 await page.keyboard.press('Enter');
 await page.getByText('نسخهٔ فعلی پذیرفته شد',{exact:true}).waitFor();
 check('explicit current acceptance does not write or retry',acknowledgements===1&&writeRequests===0&&fs.readFileSync(path.join(fixture.workspace,fixture.recovery_path??'notes.md'),'utf8')==='User kept after interruption.');
 const task=await fetch(api+'/tasks/'+fixture.task,{headers:{Authorization:'Bearer fixture-t008'}}).then(response=>response.json());
 check('reconciled task remains idle, not automatically resumed',['paused','awaiting_plan'].includes(task.status));
 await page.reload();await page.getByText('نسخهٔ فعلی پذیرفته شد',{exact:true}).waitFor();
 check('reconcile survives reload without another POST',acknowledgements===1&&writeRequests===0);
 await page.screenshot({path:path.join(output,'P10-reconciled-1024.png')});
};
