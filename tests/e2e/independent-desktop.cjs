// Native Electron, independent source tree, real API and isolated fixture data.
const { _electron: electron } = require('playwright');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs'), path = require('node:path');
const root = path.resolve(__dirname, '../..');
const output = path.join(root, 'checks/phase-1/native');
fs.mkdirSync(output, { recursive:true });
const temporary = fs.mkdtempSync(path.join(root, '.test-runs/native-'));
const env = {...process.env, HARNESS_HOME:path.join(temporary, 'home'), TEMP:temporary, TMP:temporary, PYTHONIOENCODING:'utf-8', PYTHONPATH:path.join(root,'backend')};
delete env.ELECTRON_RUN_AS_NODE;
const report = {checks:[], errors:[], scope:'Native independent development desktop; real API, seeded demo data; no provider claim'};
const check = (name, value) => { report.checks.push({name,passed:!!value}); if(!value)throw Error(name); };
(async () => {
  let app;
  try {
    const seed = spawnSync(path.join(root,'backend/.venv/Scripts/python.exe'), [path.join(__dirname,'seed-t008.py')], {cwd:path.join(root,'backend'),env,encoding:'utf8',windowsHide:true});
    if(seed.status!==0)throw Error(seed.stderr);
    const fixture = JSON.parse(seed.stdout.trim());
    app = await electron.launch({executablePath:require('electron'),args:[root],env,timeout:45000});
    const identity = await app.evaluate(({app})=>({name:app.getName(),source:app.getAppPath(),data:app.getPath('userData')}));
    report.identity = identity;
    check('independent product name',identity.name==='Bridge Coding Harness');
    check('independent source tree',path.resolve(identity.source)===root);
    check('independent Electron profile',identity.data.endsWith(path.join('BridgeCodingHarness','desktop')));
    const page = await app.firstWindow();
    page.on('pageerror',error=>report.errors.push(String(error)));
    await page.waitForLoadState('domcontentloaded');
    await page.getByRole('button',{name:'رد کردن',exact:true}).click();
    await page.getByRole('heading',{name:'روی چه چیزی کار کنیم؟'}).waitFor({timeout:30000});
    const api = await page.evaluate(()=>window.desktop.api);
    check('native API health',(await fetch(api.url+'/health',{headers:{Authorization:'Bearer '+api.token}})).ok);
    for (const size of [{width:1440,height:900},{width:1024,height:640}]) {
      await app.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows()[0].setContentSize(size.width,size.height),size);
      await page.waitForTimeout(200);
      check('RTL and no overflow '+size.width,await page.evaluate(()=>document.documentElement.dir==='rtl'&&document.documentElement.scrollWidth<=innerWidth));
      await page.screenshot({path:path.join(output,'home-'+size.width+'.png')});
    }
    await page.goto('app://harness/tasks?task='+fixture.task);
    await page.getByRole('tab',{name:'گفتگو',exact:true}).waitFor();
    await page.getByRole('tab',{name:'برنامهٔ کار',exact:true}).click();
    check('real persisted plan visible',await page.getByText('خواندن فایل راهنما',{exact:true}).first().isVisible());
    await page.screenshot({path:path.join(output,'plan-1024.png')});
    check('no native renderer errors',report.errors.length===0);
  } finally {
    if(app)await app.close();
    report.passed=report.checks.length>0&&report.checks.every(row=>row.passed)&&report.errors.length===0;
    fs.writeFileSync(path.join(output,'smoke.json'),JSON.stringify(report,null,2));
  }
  console.log(JSON.stringify(report));
})().catch(error=>{console.error(error);process.exitCode=1});
