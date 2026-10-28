"""Explicit local execution in a task copy. This is not an OS sandbox."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .docker import Capability,ContainerConfig,ExecResult,RuntimeUnavailable


class LocalRuntime:
    local=True

    def __init__(self,config=None):
        self.config=ContainerConfig(image='bridge-local-v1')
        self.processes={};self.cancelled=set();self.lock=threading.RLock();self.lease=None

    def set_lease(self,lease):self.lease=lease

    def capability(self):
        return Capability(True,'Local execution in the task copy; commands have your Windows permissions.',server_version='local',image=self.config.image,image_present=True)

    def pin_image(self):return self.config.image

    @staticmethod
    def toolchain():
        configured=os.environ.get('BRIDGE_TOOLCHAIN')
        return Path(configured) if configured else Path(__file__).resolve().parents[3]/'build'/'toolchain'

    def environment(self,root,extra=None):
        allowed={'SYSTEMROOT','SYSTEMDRIVE','COMSPEC','WINDIR','PATHEXT','PATH'}
        env={k:v for k,v in os.environ.items() if k.upper() in allowed}
        toolchain=self.toolchain()
        if toolchain:
            env['PATH']=os.pathsep.join([str(toolchain/'node'),str(toolchain/'python'),env.get('PATH','')])
        private=Path(root).parent/'local-runtime';private.mkdir(exist_ok=True)
        for key in ('TEMP','TMP','HOME','USERPROFILE','APPDATA','LOCALAPPDATA'):env[key]=str(private)
        env.update(PYTHONIOENCODING='utf-8',PYTHONUTF8='1',PIP_DISABLE_PIP_VERSION_CHECK='1',NPM_CONFIG_CACHE=str(private/'npm-cache'),NPM_CONFIG_USERCONFIG=str(private/'npmrc'),PIP_CONFIG_FILE=os.devnull)
        if extra:env.update(extra)
        return env

    def start(self,command,*,snapshot,exec_id,skills=None,extra=None):
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}',exec_id):raise ValueError('Invalid execution identity')
        root=Path(snapshot).resolve()
        if not root.is_dir() or root==Path(root.anchor):raise RuntimeUnavailable('Invalid task directory')
        if self.lease:self.lease.check('execute')
        # Virtual file-tool paths are translated only at this execution boundary.
        command=command.replace('/workspace/',str(root)+os.sep).replace('/workspace',str(root))
        if skills:command=command.replace('/skills/',str(Path(skills).resolve())+os.sep)
        log=tempfile.NamedTemporaryFile(dir=root.parent,prefix='execution-',suffix='.log',delete=False)
        env=self.environment(root,extra)
        argv='"'+env.get('COMSPEC','C:\\Windows\\System32\\cmd.exe')+'" /d /s /c "'+command+'"' if os.name=='nt' else ['/bin/sh','-lc',command]
        with self.lock:
            if exec_id in self.cancelled:log.close();raise RuntimeUnavailable('Execution was cancelled')
            if exec_id in self.processes:log.close();raise RuntimeUnavailable('Execution already exists')
            process=subprocess.Popen(argv,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,start_new_session=os.name!='nt')
            entry={'process':process,'log':log};self.processes[exec_id]=entry
            if os.name=='nt':
                from .job import bind
                try:entry['job']=bind(process)
                except BaseException:
                    log.close();Path(log.name).unlink(missing_ok=True);self.processes.pop(exec_id,None)
                    raise
            return entry

    def output(self,exec_id,max_output=1_000_000):
        with self.lock:
            entry=self.processes.get(exec_id)
            if not entry:return ''
            with open(entry['log'].name,'rb') as reader:data=reader.read(max_output+1)
            return data[:max_output].decode('utf8',errors='replace')

    def cancel(self,exec_id):
        with self.lock:self.cancelled.add(exec_id);entry=self.processes.get(exec_id)
        if not entry:return True
        process=entry['process']
        if entry.get('job'):
            from .job import close
            close(entry.pop('job'))
        if process.poll() is None:
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                import signal
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:return False
        return True

    def cancel_all(self):
        for identifier in list(self.processes):self.cancel(identifier)

    def execute(self,command,*,snapshot,exec_id,timeout=120,skills=None,max_output=1_000_000,network_until=None):
        entry=self.start(command,snapshot=snapshot,exec_id=exec_id,skills=skills)
        process=entry['process'];deadline=time.monotonic()+timeout;timed_out=False
        try:
            while process.poll() is None:
                if self.lease:self.lease.check('execute')
                if time.monotonic()>=deadline:timed_out=True;self.cancel(exec_id);break
                if Path(entry['log'].name).stat().st_size>max_output*4:self.cancel(exec_id);break
                time.sleep(.05)
        except BaseException:
            self.cancel(exec_id);entry['log'].close();Path(entry['log'].name).unlink(missing_ok=True)
            with self.lock:self.processes.pop(exec_id,None)
            raise
        text=self.output(exec_id,max_output)
        if entry.get('job'):
            from .job import close
            close(entry.pop('job'))
        stopped=exec_id in self.cancelled and not timed_out
        result=ExecResult(exec_id,process.returncode if process.returncode is not None else -1,text,truncated=Path(entry['log'].name).stat().st_size>max_output,timed_out=timed_out,stopped=stopped,unknown=process.poll() is None,operation_id=exec_id)
        entry['log'].close()
        Path(entry['log'].name).unlink(missing_ok=True)
        with self.lock:self.processes.pop(exec_id,None)
        return result

    def reconcile(self,identifiers):
        running=[identifier for identifier in identifiers if identifier in self.processes and self.processes[identifier]['process'].poll() is None]
        return {'resolved':[identifier for identifier in identifiers if identifier not in running],'unresolved':running}


def runtime_for(descriptor=None):
    return LocalRuntime()
