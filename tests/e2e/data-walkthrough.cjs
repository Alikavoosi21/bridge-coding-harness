const fs=require('node:fs'),path=require('node:path');
module.exports=async({page,fixture,api,origin,output,env,check})=>{
 const headers={Authorization:'Bearer fixture-t008'};
 await page.goto(origin);await page.getByRole('button',{name:'رد کردن',exact:true}).click();
 await page.goto(origin+'/settings?tab=data');
 const region=page.getByRole('region',{name:'داده‌ها و عیب‌یابی'});
 // The component is a named container, so locate its visible contents directly.
 await page.getByText('داده‌های محلی محصول',{exact:true}).waitFor();
 await page.getByRole('button',{name:'تازه‌سازی پیش‌نمایش پاک‌سازی',exact:true}).waitFor();
 const cache=path.join(env.HARNESS_HOME,'tasks',fixture.cache_task,'working','.pytest_cache');
 check('opening data preview deletes nothing',fs.existsSync(cache));
 const storage=await fetch(api+'/storage/preview',{headers}).then(response=>response.json());
 check('preview exposes only terminal old cache',storage.items.length===1&&storage.items[0].task_id===fixture.cache_task&&storage.protected_tasks>=1);
 await page.getByRole('spinbutton',{name:'حداقل سن cache (روز)'}).fill('20');
 await page.getByRole('button',{name:'ذخیرهٔ سیاست',exact:true}).click();
 await page.getByText('سیاست ذخیره شد؛ پاک‌سازی خودکار اجرا نمی‌شود.',{exact:true}).waitFor();
 check('saving policy does not clean',fs.existsSync(cache));
 for(const viewport of [{width:1440,height:900},{width:1024,height:640}]){
  await page.setViewportSize(viewport);await page.emulateMedia({reducedMotion:'reduce'});
  check('P14 no horizontal overflow '+viewport.width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(output,'P14-data-'+viewport.width+'.png')});
 }
 await page.getByRole('checkbox').check();await page.getByRole('button',{name:'بازبینی پاک‌سازی انتخاب‌ها',exact:true}).click();
 check('cleanup dialog alone has no effect',fs.existsSync(cache));
 await page.getByRole('button',{name:'انصراف',exact:true}).click();check('cancel retains cache',fs.existsSync(cache));
 await page.getByRole('button',{name:'بازبینی پاک‌سازی انتخاب‌ها',exact:true}).click();
 const clean=page.getByRole('button',{name:'تأیید و پاک‌سازی همین cacheها',exact:true});await clean.focus();await page.keyboard.press('Enter');
 await page.getByText('cache قدیمیِ مجاز برای پاک‌سازی وجود ندارد.',{exact:true}).waitFor();
 check('explicit cleanup deletes selected cache only',!fs.existsSync(cache)&&fs.readFileSync(path.join(path.dirname(cache),'kept.py'),'utf8')==='PRIVATE SOURCE KEPT');
 check('original project is untouched',fs.readFileSync(path.join(fixture.workspace,'notes.md'),'utf8')==='Local fixture. No secrets.');
 await page.getByRole('button',{name:'پیش‌نمایش بستهٔ عیب‌یابی',exact:true}).click();
 const dialog=page.getByRole('dialog');await dialog.waitFor();
 const text=await dialog.locator('pre').textContent();
 check('diagnostic preview has no source prompt or private path',!text.includes('PRIVATE SOURCE')&&!text.includes('PRIVATE DIAGNOSTIC')&&!text.includes(fixture.workspace)&&!text.includes(env.HARNESS_HOME));
 await page.getByRole('button',{name:'تأیید و ساخت ZIP محلی',exact:true}).click();
 await page.getByText('بسته فقط روی همین دستگاه ساخته شد؛ چیزی ارسال نشد.',{exact:true}).waitFor();
 const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'دریافت ZIP محلی',exact:true}).click();
 const download=await downloadPromise;const target=path.join(path.dirname(env.HARNESS_HOME),'diagnostics-download.zip');await download.saveAs(target);
 check('authenticated local ZIP download succeeds',fs.readFileSync(target).subarray(0,2).toString()==='PK');
 await page.reload();await page.getByRole('button',{name:'تازه‌سازی پیش‌نمایش پاک‌سازی',exact:true}).waitFor();
 check('policy survives reload',await page.getByRole('spinbutton',{name:'حداقل سن cache (روز)'}).inputValue()==='20');
};
