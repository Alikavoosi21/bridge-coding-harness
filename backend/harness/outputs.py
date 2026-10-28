"""User-requested output previews and runs, always on a separate captured copy."""
import atexit
import http.client
import json
import mimetypes
import re
import secrets
import shlex
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote,urlsplit

from server.errors import ApiError
from .preflight import analyze_workspace
from .runtime.docker import DockerRuntime,RuntimeUnavailable,build_run_args
from .runtime.local import LocalRuntime
from .task_runtime import task_directory
from .worktrees.diff import changes,review_context
from .worktrees.guard import locked_copy
from .worktrees.snapshot import build,sync,validate_relative,excluded,_is_link_path,UnsafePath

BUSY={'queued','planning','executing','verifying','repairing','stopping','recovery_required'}
ACTIVE={'starting','installing','running','ready','stopping','unknown'}
WEB_EXT={'.html','.htm','.css','.js','.mjs','.json','.svg','.png','.jpg','.jpeg','.gif','.webp','.ico','.woff','.woff2','.ttf','.map','.wasm'}


def output_info(store,task_id):
    task,_,working,_,_=review_context(store,task_id)
    report=changes(store,task_id);snapshot=build(working)
    files={item.path for item in snapshot.files}
    html=sorted((p for p in files if Path(p).suffix.lower() in {'.html','.htm'}),key=lambda p:(Path(p).name!='index.html',p))[:40]
    analysis=analyze_workspace(working);suggestions=[]
    if 'package.json' in files:
        try:data=json.loads((working/'package.json').read_text(encoding='utf-8-sig'))
        except (ValueError,OSError):data={}
        scripts=data.get('scripts',{}) if isinstance(data,dict) else {}
        manager=analysis['detected'].get('node_manager') or 'npm'
        deps={}
        for group in ('dependencies','devDependencies'):
            if isinstance(data,dict) and isinstance(data.get(group),dict):deps.update(data[group])
        if isinstance(scripts,dict):
            for name in ('dev','start','build','test'):
                if name not in scripts:continue
                command=f'{manager} run {name}'
                if name=='dev' and 'next' in deps:command+=' -- --hostname 0.0.0.0 --port 3000'
                elif name=='dev' and 'vite' in deps:command+=' -- --host 0.0.0.0 --port 3000'
                suggestions.append({'command':command,'kind':'server' if name in {'dev','start'} else 'command','port':3000})
    for name in ('server.js','app.js','index.js','main.py','app.py'):
        if name in files:suggestions.append({'command':('python ' if name.endswith('.py') else 'node ')+shlex.quote(name),'kind':'server' if name=='server.js' else 'command','port':3000})
    return {'html_files':html,'commands':suggestions,'install':analysis['profile'].get('install'),'read_only':task['read_only'],
            'can_run':not task['read_only'] and task['status'] not in BUSY,'busy':task['status'] in BUSY,
            'working_revision':report['working_revision'],'working_manifest_hash':report['working_manifest_hash']}


class OutputSessions:
    def __init__(self,runtime_factory=LocalRuntime):
        self.sessions={};self.runtime_factory=runtime_factory;self.lock=threading.RLock();self.closing=False
        atexit.register(self.close_all)

    @staticmethod
    def public(session):
        keys=('id','task_id','kind','state','url','command','output','exit_code','path','created_at','expires_at','install_command')
        return {key:session.get(key) for key in keys}

    def _save(self,s):
        with self.lock:
            directory=s['directory'];temporary=directory/'session.tmp'
            temporary.write_text(json.dumps(self.public(s)|{'container':s.get('container'),'network':s.get('network')},ensure_ascii=False),encoding='utf8')
            temporary.replace(directory/'session.json')

    def list(self,task_id):return [self.public(s) for s in list(self.sessions.values()) if s['task_id']==task_id]

    def start(self,store,task_id,*,kind,path,command,port,confirm,install_command,install_consent,expected_revision,expected_hash,key,network_consent=False):
        if not confirm:raise ApiError('consent_required','اجرای خروجی باید با انتخاب صریح تو باشد.',status_code=409)
        if install_command and not install_consent:raise ApiError('consent_required','نصب وابستگی‌ها و دسترسی شبکه را جدا تأیید کن.',status_code=409)
        if kind=='server' and not network_consent:raise ApiError('consent_required','دسترسی شبکهٔ همین اجرای وب را تأیید کن.',status_code=409)
        identity=(task_id,key);payload=(kind,path,command,port,install_command,expected_revision,expected_hash,network_consent)
        with self.lock:
            if self.closing:raise ApiError('workspace_busy','برنامه در حال بستن اجراهاست.',status_code=409)
            for existing in self.sessions.values():
                if existing['request_key']==identity:
                    if existing['payload']!=payload:raise ApiError('idempotency_conflict','شناسهٔ درخواست با محتوای دیگری استفاده شده است.',status_code=409)
                    return self.public(existing)
            if sum(s['state'] in ACTIVE for s in self.sessions.values())>=4:raise ApiError('workspace_busy','ابتدا یکی از اجراهای باز را متوقف کن.',status_code=409)
            task,directory,working,_,_=review_context(store,task_id)
            if task['status'] in BUSY:raise ApiError('workspace_busy','ابتدا منتظر پایان کار بمان یا آن را متوقف کن.',status_code=409)
            if kind!='html' and task['read_only']:raise ApiError('runtime_unavailable','ابتدا ویرایش و محیط ایزوله را برای این گفتگو فعال کن.',status_code=409)
            identifier='output_'+uuid.uuid4().hex;folder=directory/'outputs'/identifier
            if any(p.exists() and _is_link_path(p) for p in (folder,folder.parent)):raise ApiError('recovery_required','مسیر خروجی لینک است.',status_code=409)
            runtime=None
            if kind!='html':
                runtime=self.runtime_factory();runtime.pin_image()
            if kind=='html':
                selected=validate_relative(path)
                if selected.suffix.lower() not in {'.html','.htm'} or excluded(selected):raise UnsafePath('Only a project HTML file can be previewed.')
                snapshot=build(working)
                if path not in snapshot.by_path():raise UnsafePath('The HTML file is missing or excluded.')
                folder.mkdir(parents=True);sync(snapshot,folder/'project',write_manifest_file=False)
            else:
                with locked_copy(store,task_id,expected_revision=expected_revision,expected_manifest_hash=expected_hash,kind='output_capture') as held:
                    folder.mkdir(parents=True);sync(build(held['working']),folder/'project',write_manifest_file=False)
            s={'id':identifier,'task_id':task_id,'kind':kind,'state':'starting','url':None,'command':command,'path':path,
               'output':'','exit_code':None,'created_at':time.time(),'expires_at':time.time()+1200,'install_command':install_command,
               'directory':folder,'runtime':runtime,'request_key':identity,'payload':payload,'stop':threading.Event(),'server':None,'network':None,'container':None,'last_poll':0}
            self.sessions[identifier]=s;self._save(s)
            if kind=='html':self._html(s)
            else:
                thread=threading.Thread(target=self._run,args=(s,port),daemon=True);s['thread']=thread;thread.start()
            timer=threading.Timer(1200,lambda:self.stop(task_id,identifier));timer.daemon=True;timer.start();s['timer']=timer
            return self.public(s)

    def _html(self,s):
        root=s['directory']/'project';ticket=secrets.token_hex(24)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                try:
                    if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}':raise UnsafePath('Invalid host')
                    route=unquote(urlsplit(self.path).path)
                    if not route.startswith('/'+ticket+'/'):raise UnsafePath('Invalid preview ticket')
                    relative=validate_relative(route[len(ticket)+2:]);file=root.joinpath(*relative.parts)
                    if excluded(relative) or relative.suffix.lower() not in WEB_EXT or not file.is_file() or file.stat().st_size>8_000_000 or any(_is_link_path(p) for p in [file,*file.parents] if p==root or root in p.parents):raise UnsafePath('Unsupported preview asset')
                    body=file.read_bytes();self.send_response(200)
                    self.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
                    self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                    self.send_header('Access-Control-Allow-Origin','*')
                    self.send_header('Content-Security-Policy',"default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'none'; object-src 'none'; base-uri 'self'; form-action 'none'")
                    self.end_headers();self.wfile.write(body)
                except (OSError,ValueError):self.send_error(404)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;s['server']=server
        from urllib.parse import quote
        s.update(state='ready',url=f'http://127.0.0.1:{server.server_port}/{ticket}/'+quote(s['path']))
        threading.Thread(target=server.serve_forever,daemon=True).start();self._save(s)

    @staticmethod
    def _docker(s,args,timeout=20):
        runtime=s['runtime']
        result=runtime._run(['docker',*args],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,env=runtime._host_env(),check=False)
        if result.returncode:raise RuntimeUnavailable((result.stderr or result.stdout or 'Docker operation failed')[-4000:])
        return (result.stdout+('\n'+result.stderr if args[0]=='logs' else '')).strip()

    def _run(self,s,port):
        runtime=s['runtime'];root=s['directory']/'project'
        if getattr(runtime,'local',False):
            return self._run_local(s,port)
        try:
            if s['install_command']:
                s['state']='installing';self._save(s)
                result=runtime.execute(s['install_command'],snapshot=root,exec_id=s['id']+'-install',timeout=300,network_until=time.time()+300)
                s['output']=result.output[-64000:]
                if result.exit_code or result.unknown:raise RuntimeUnavailable('نصب وابستگی‌ها موفق نشد.\n'+s['output'])
            if s['stop'].is_set():return
            if s['kind']=='command':
                s['state']='running';self._save(s)
                result=runtime.execute(s['command'],snapshot=root,exec_id=s['id'],timeout=120)
                s.update(state='stopped' if result.stopped else 'failed' if result.exit_code or result.unknown else 'finished',exit_code=result.exit_code,output=result.output[-64000:])
            else:
                s['container']='harness-'+s['id'];self._save(s)
                if s['stop'].is_set():return
                argv=build_run_args(runtime.config,root,s['id'],f'PORT={port} HOST=0.0.0.0 timeout --signal=TERM 1200 sh -lc '+shlex.quote(s['command']),network=True)
                argv[2:2]=['--detach','--publish',f'127.0.0.1::{port}']
                with self.lock:
                    if s['stop'].is_set():return
                    self._docker(s,argv[1:])
                binding=self._docker(s,['port',s['container'],f'{port}/tcp'])
                match=re.fullmatch(r'127\.0\.0\.1:(\d+)',binding)
                if not match:raise RuntimeUnavailable('Docker did not publish a loopback-only port.')
                host_port=int(match[1]);deadline=time.monotonic()+35
                while time.monotonic()<deadline and not s['stop'].is_set():
                    try:
                        connection=http.client.HTTPConnection('127.0.0.1',host_port,timeout=0.5)
                        try:connection.request('GET','/');connection.getresponse()
                        finally:connection.close()
                        s.update(state='ready',url=f'http://127.0.0.1:{host_port}/');break
                    except (OSError,http.client.HTTPException):time.sleep(0.2)
                if s['state']!='ready' and not s['stop'].is_set():
                    raise RuntimeUnavailable('برنامه روی پورت انتخابی آماده نشد؛ باید روی 0.0.0.0 گوش کند.\n'+self._docker(s,['logs','--tail','100',s['container']]))
        except Exception as error:
            detail=str(error)
            if s.get('container'):
                try:detail+='\n'+self._docker(s,['logs','--tail','100',s['container']])
                except Exception:pass
            s.update(state='stopped' if s['stop'].is_set() else 'failed',output=detail[-64000:],url=None)
        finally:
            if s['stop'].is_set() or s['state']=='failed':
                gone=self._cleanup(s)
                if not gone:s.update(state='unknown',url=None)
                if s['stop'].is_set():
                    try:gone=not self._docker(s,['ps','-a','--filter','name=^harness-'+s['id']+'(-install)?$','--format','{{.ID}}'])
                    except Exception:gone=False
                    s.update(state='stopped' if gone else 'unknown',url=None)
            self._save(s)

    def get(self,task_id,identifier):
        s=self.sessions.get(identifier)
        if not s or s['task_id']!=task_id:raise ApiError('not_found','اجرای خروجی پیدا نشد؛ بعد از بازشدن مجدد برنامه دوباره اجرا کن.',status_code=404)
        if s['kind']=='server' and s['state']=='ready' and getattr(s['runtime'],'local',False):
            s['output']=s['runtime'].output(s['id'],64000)
            entry=s['runtime'].processes.get(s['id'])
            if not entry or entry['process'].poll() is not None:s.update(state='finished',url=None)
        elif s['kind']=='server' and s['state']=='ready' and time.monotonic()-s['last_poll']>2:
            s['last_poll']=time.monotonic()
            try:s['output']=self._docker(s,['logs','--tail','150',s['container']])[-64000:]
            except RuntimeUnavailable as error:s.update(state='failed',url=None,output=str(error));self._cleanup(s)
        return self.public(s)

    def _cleanup(self,s):
        if getattr(s['runtime'],'local',False):
            return s['runtime'].cancel(s['id']) and s['runtime'].cancel(s['id']+'-install')
        if s['runtime']:
            for suffix in ('','-install'):
                try:self._docker(s,['rm','--force','harness-'+s['id']+suffix],timeout=3)
                except Exception:pass
            try:return not self._docker(s,['ps','-a','--filter','name=^harness-'+s['id']+'(-install)?$','--format','{{.ID}}'],timeout=3)
            except Exception:pass
            return False
        return True

    def stop(self,task_id,identifier):
        with self.lock:
            s=self.sessions.get(identifier)
            if not s or s['task_id']!=task_id:raise ApiError('not_found','اجرای خروجی پیدا نشد.',status_code=404)
            s['stop'].set();s['state']='stopping';self._save(s)
            if s.get('timer'):s['timer'].cancel()
        if s['server']:s['server'].shutdown();s['server'].server_close()
        if s['runtime']:
            s['runtime'].cancel(s['id']);s['runtime'].cancel(s['id']+'-install');self._cleanup(s)
        thread=s.get('thread')
        if thread and thread.is_alive() and thread is not threading.current_thread():thread.join(timeout=1)
        confirmed=True
        if s['runtime']:
            try:confirmed=self._cleanup(s) if getattr(s['runtime'],'local',False) else not self._docker(s,['ps','-a','--filter','name=^harness-'+s['id']+'(-install)?$','--format','{{.ID}}'])
            except Exception:confirmed=False
        s.update(state='stopping' if thread and thread.is_alive() else 'stopped' if confirmed else 'unknown',url=None);self._save(s);return self.public(s)

    def close_all(self):
        self.closing=True
        for s in list(self.sessions.values()):
            if s['state'] in ACTIVE:
                try:self.stop(s['task_id'],s['id'])
                except Exception:pass
        self.closing=False

    def _run_local(self,s,port):
        import socket
        runtime=s['runtime'];root=s['directory']/'project'
        try:
            if s['install_command']:
                s['state']='installing';self._save(s)
                result=runtime.execute(s['install_command'],snapshot=root,exec_id=s['id']+'-install',timeout=300)
                s['output']=result.output[-64000:]
                if result.exit_code:raise RuntimeUnavailable('نصب موفق نشد.\n'+s['output'])
            if s['stop'].is_set():return
            s['state']='running';self._save(s)
            if s['kind']=='command':
                result=runtime.execute(s['command'],snapshot=root,exec_id=s['id'],timeout=120)
                s.update(state='stopped' if result.stopped else 'failed' if result.exit_code else 'finished',exit_code=result.exit_code,output=result.output[-64000:])
            else:
                with socket.socket() as probe:probe.bind(('127.0.0.1',0));chosen=probe.getsockname()[1]
                command=s['command']
                if command.endswith(' -- --hostname 0.0.0.0 --port 3000'):command=command.replace(' -- --hostname 0.0.0.0 --port 3000',f' -- --hostname 127.0.0.1 --port {chosen}')
                elif command.endswith(' -- --host 0.0.0.0 --port 3000'):command=command.replace(' -- --host 0.0.0.0 --port 3000',f' -- --host 127.0.0.1 --port {chosen}')
                # A fresh port prevents displaying an unrelated process already on 3000.
                entry=runtime.start(command,snapshot=root,exec_id=s['id'],extra={'PORT':str(chosen),'HOST':'127.0.0.1','FLASK_RUN_PORT':str(chosen)})
                deadline=time.monotonic()+45
                while not s['stop'].is_set() and time.monotonic()<deadline:
                    if entry['process'].poll() is not None:raise RuntimeUnavailable(runtime.output(s['id']) or 'توقف سرور پیش از آماده‌شدن')
                    try:
                        connection=http.client.HTTPConnection('127.0.0.1',chosen,timeout=1);connection.request('GET','/');response=connection.getresponse();response.read(1024);connection.close()
                        if response.status<500:break
                    except OSError:pass
                    time.sleep(.15)
                else:raise RuntimeUnavailable('برنامه در مهلت آماده نشد؛ خروجی اجرا را بررسی کن.')
                if s['stop'].is_set():return
                s.update(state='ready',url=f'http://127.0.0.1:{chosen}/',output=runtime.output(s['id'],64000))
        except Exception as error:
            s.update(state='stopped' if s['stop'].is_set() else 'failed',url=None,output=(str(error)+'\n'+runtime.output(s['id'],64000))[-64000:]);self._cleanup(s)
        finally:self._save(s)
