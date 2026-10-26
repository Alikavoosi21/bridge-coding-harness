const { app, BrowserWindow, Menu, dialog, ipcMain, nativeTheme, protocol, session, shell } = require('electron');
const fs = require('node:fs');
const path = require('node:path');

const engine = require('./backend.cjs');

// Dev: the Next dev server. Packaged: the static export served over app://.
const DEV_URL = process.env.DESKTOP_DEV_URL;
const OUT_DIR = path.join(__dirname, '..', 'out');
const APP_ID = 'ir.bridge.codingharness';
app.setName('Bridge Coding Harness');
// An explicit profile is useful for isolated desktop verification; normal
// launches always use Bridge's own profile, never the upstream app's data.
const desktopData = app.commandLine.getSwitchValue('user-data-dir') || path.join(app.getPath('appData'), 'BridgeCodingHarness', 'desktop');
fs.mkdirSync(desktopData, { recursive: true });
app.setPath('userData', desktopData);
const APP_ORIGIN = 'app://harness';

// Matches --sidebar in globals.css so the native window controls sit on the same tone.
const CHROME = {
  light: { color: '#010a04', symbolColor: '#ffffff' },
  dark: { color: '#010a04', symbolColor: '#ffffff' },
};

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.map': 'application/json',
};

// The page may load only its own files, and talk only to the local backend.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'", // Next's static export bootstraps with inline scripts
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self' http://127.0.0.1:* http://localhost:*",
  "media-src 'self' http://127.0.0.1:*", // sound and video are played straight from the engine
  "frame-src 'self' blob: http://127.0.0.1:*", // output frames are sandboxed and have no desktop bridge
  "object-src 'none'",
  "base-uri 'self'",
].join('; ');

protocol.registerSchemesAsPrivileged([{ scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true } }]);

// One window per user: a second launch focuses the first instead of opening another.
if (!app.requestSingleInstanceLock()) app.quit();

function resolveExport(requestUrl) {
  const pathname = decodeURIComponent(new URL(requestUrl).pathname);
  const base = path.join(OUT_DIR, pathname);
  // Refuse anything that climbs out of the export folder.
  if (base !== OUT_DIR && !base.startsWith(OUT_DIR + path.sep)) return null;
  const candidates = [base, `${base}.html`, path.join(base, 'index.html')];
  return candidates.find((file) => fs.existsSync(file) && fs.statSync(file).isFile()) ?? null;
}

async function serveExport(request) {
  const file = resolveExport(request.url) ?? path.join(OUT_DIR, '404.html');
  try {
    // Read through fs (not file://) so it also works when the app is packed in an asar archive.
    const body = await fs.promises.readFile(file);
    return new Response(body, {
      status: file.endsWith('404.html') ? 404 : 200,
      headers: { 'content-type': MIME[path.extname(file).toLowerCase()] ?? 'application/octet-stream', 'content-security-policy': CSP },
    });
  } catch {
    return new Response('Not found', { status: 404 });
  }
}

// Files that run when opened. An agent can write one into the workspace, so a click in
// the files screen must never start it: these are shown in their folder instead.
const RUNNABLE = new Set([
  '.exe', '.com', '.scr', '.pif', '.cpl', '.msi', '.msp', '.msc', '.bat', '.cmd', '.ps1', '.psm1', '.vbs', '.vbe', '.js', '.jse', '.wsf', '.wsh', '.hta',
  '.lnk', '.url', '.reg', '.jar', '.py', '.pyw', '.sh', '.command', '.app', '.desktop', '.appimage', '.dll', '.sys',
]);

/** The open workspace folder, asked from the engine: the page is not trusted to say where it is. */
async function workspaceRoot() {
  const { url, token } = engine.connection;
  if (!url) return null;
  try {
    const response = await fetch(`${url}/workspace`, { headers: { Authorization: `Bearer ${token}` } });
    const { path: root } = await response.json();
    return root ? fs.realpathSync(root) : null;
  } catch {
    return null;
  }
}

/** Open a workspace file with its own program. Returns '' when opened, otherwise why it was not. */
async function openInWorkspace(target) {
  const root = await workspaceRoot();
  let file;
  try {
    file = fs.realpathSync(path.resolve(String(target)));
  } catch {
    return 'missing';
  }
  const inside = root && (file === root || (!path.relative(root, file).startsWith('..') && !path.isAbsolute(path.relative(root, file))));
  if (!inside) return 'outside';
  if (fs.statSync(file).isFile() && RUNNABLE.has(path.extname(file).toLowerCase())) {
    shell.showItemInFolder(file);
    return 'runnable';
  }
  return (await shell.openPath(file)) ? 'failed' : '';
}

function createWindow() {
  const theme = nativeTheme.shouldUseDarkColors ? 'dark' : 'light';
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 640,
    show: false,
    title: app.getName(),
    icon: path.join(__dirname, process.platform === 'win32' ? 'bridge-icon.ico' : 'bridge-icon.png'), // dev and Linux; on Windows the packaged exe carries its own
    backgroundColor: CHROME[theme].color,
    titleBarStyle: 'hidden',
    titleBarOverlay: { ...CHROME[theme], height: 36 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      plugins: true, // Chromium's built-in PDF viewer, for the files screen
      devTools: !app.isPackaged,
    },
  });

  win.once('ready-to-show', () => win.show());
  let closing = false;
  let reviewingClose = false;
  win.webContents.on('will-prevent-unload', () => { closing=false; });
  win.on('close', async event => {
    if (closing) return;
    event.preventDefault();
    if (reviewingClose) return;
    reviewingClose = true;
    try {
      let activity;
      try { activity = await engine.activity(); } catch { activity = null; }
      if (!activity || activity.running.length || activity.queued || activity.worker_held) {
        const answer = await dialog.showMessageBox(win,{type:'question',title:'بستن Bridge Coding Harness',message:'کار در حال اجرا یا منتظر توقف است.',detail:'با خروج، سرویس پس‌زمینه‌ای باقی نمی‌ماند. ابتدا درخواست توقف ثبت می‌شود؛ نتیجهٔ نامعلوم در بازکردن بعدی نیازمند بازیابی است.',buttons:['ماندن','توقف و خروج'],defaultId:0,cancelId:0,noLink:true});
        if (answer.response!==1) return;
        let result;
        try { result=await engine.prepareShutdown(); } catch { result=null; }
        if (!result?.stopped) {
          const unresolved=await dialog.showMessageBox(win,{type:'warning',title:'توقف تأیید نشده است',message:'پایان همهٔ عملیات تأیید نشد.',detail:'می‌توانید بمانید و بازیابی را بررسی کنید، یا با حفظ وضعیت نامعلوم خارج شوید. هیچ عملیات نامعلومی خودکار تکرار نمی‌شود.',buttons:['ماندن','خروج با وضعیت نامعلوم'],defaultId:0,cancelId:0,noLink:true});
          if (unresolved.response!==1) return;
        }
      }
      closing=true;win.close();
    } finally { reviewingClose=false; }
  });

  // Links to the outside world open in the user's browser; the window itself never leaves the app.
  const isInternal = (url) => url.startsWith(APP_ORIGIN) || (DEV_URL && url.startsWith(DEV_URL));
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-attach-webview', (event) => event.preventDefault());
  win.webContents.on('will-navigate', (event, url) => {
    if (isInternal(url)) return;
    event.preventDefault();
    if (/^https?:/.test(url)) shell.openExternal(url);
  });

  win.loadURL(DEV_URL ?? `${APP_ORIGIN}/`);
  return win;
}

app.setAppUserModelId(APP_ID); // taskbar grouping and notifications on Windows

app.on('second-instance', () => {
  const [win] = BrowserWindow.getAllWindows();
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.focus();
});

app.whenReady().then(async () => {
  // The app draws its own chrome; the default File/Edit/View menu has no place in it.
  if (app.isPackaged) Menu.setApplicationMenu(null);

  protocol.handle('app', serveExport);

  // The app needs no camera, microphone, location or notifications; nothing is granted.
  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  // Preview frames have their own loopback origin; they cannot contact the app API or external services.
  session.defaultSession.webRequest.onBeforeRequest((details,callback)=>{
    try{
      const frame=details.frame;
      if(frame?.parent&&frame.url.startsWith('http://127.0.0.1:')){
        const source=new URL(frame.url),destination=new URL(details.url);
        return callback({cancel:!['data:','blob:'].includes(destination.protocol)&&destination.origin!==source.origin&&!(destination.protocol==='ws:'&&destination.host===source.host)});
      }
    }catch{return callback({cancel:true});}
    callback({cancel:false});
  });

  // The engine starts first so the page knows its address; the page waits for it to answer.
  await engine.start();
  ipcMain.on('desktop:api', (event) => {
    event.returnValue = engine.connection.url ? { ...engine.connection } : null;
  });
  ipcMain.handle('desktop:pick-folder', async (event) => {
    const result = await dialog.showOpenDialog(BrowserWindow.fromWebContents(event.sender), {
      title: 'انتخاب پوشهٔ فضای کاری',
      properties: ['openDirectory', 'createDirectory'],
    });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle('desktop:open-path', (_event, target) => openInWorkspace(target));
  ipcMain.handle('desktop:open-preview', async (event, taskId, outputId) => {
    if(typeof taskId!=='string'||!/^task_[a-zA-Z0-9]+$/.test(taskId)||typeof outputId!=='string'||!/^output_[a-f0-9]{32}$/.test(outputId))return false;
    const {url,token}=engine.connection;
    try{
      const response=await fetch(`${url}/tasks/${taskId}/outputs/${outputId}`,{headers:{Authorization:`Bearer ${token}`}});
      if(!response.ok)return false;
      const output=await response.json();const address=new URL(output.url);
      if(output.state!=='ready'||address.protocol!=='http:'||address.hostname!=='127.0.0.1'||!address.port)return false;
      const parent=BrowserWindow.fromWebContents(event.sender);
      const preview=new BrowserWindow({parent,width:1100,height:760,title:'پیش‌نمایش خروجی — Bridge',autoHideMenuBar:true,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,partition:'bridge-output-'+outputId}});
      const previewSession=preview.webContents.session;
      previewSession.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));
      previewSession.setPermissionCheckHandler(()=>false);
      previewSession.on('will-download',event=>event.preventDefault());
      previewSession.webRequest.onBeforeRequest((details,callback)=>{try{const destination=new URL(details.url);callback({cancel:!['data:','blob:'].includes(destination.protocol)&&destination.origin!==address.origin&&!(destination.protocol==='ws:'&&destination.host===address.host)});}catch{callback({cancel:true});}});
      preview.webContents.setWindowOpenHandler(()=>({action:'deny'}));
      preview.webContents.on('will-navigate',(event,url)=>{try{if(new URL(url).origin!==address.origin)event.preventDefault();}catch{event.preventDefault();}});
      parent?.once('closed',()=>{if(!preview.isDestroyed())preview.destroy();});
      await preview.loadURL(address.toString());return true;
    }catch{return false;}
  });

  ipcMain.on('desktop:set-theme', (event, theme) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (!win || !CHROME[theme]) return;
    nativeTheme.themeSource = theme;
    if (process.platform === 'win32') win.setTitleBarOverlay({ ...CHROME[theme], height: 36 });
    win.setBackgroundColor(CHROME[theme].color);
  });

  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('will-quit', () => engine.stop());

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
