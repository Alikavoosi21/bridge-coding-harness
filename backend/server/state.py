"""What the API holds in memory: the open workspace and its run manager."""

from __future__ import annotations

import secrets
import time
import asyncio
import hashlib
import json
import uuid
from pathlib import Path

from fastapi import HTTPException

from harness import Workspace
from harness.task_controller import TaskController

from . import settings
from .runs import RunManager
from .storage import Store


def _workspace_folder(path: str) -> Path:
    """The folder to open, refused when it is too broad to hand to an agent.

    Agents may read and change everything under the workspace, so it must be a
    folder chosen for that - not a whole drive, and not the user's home folder
    with their keys, browser profile and every other project in it.
    """
    folder = Path(path.strip()).expanduser()
    if not folder.is_absolute():
        raise HTTPException(status_code=400, detail="Give the full path of the folder.")
    folder = folder.resolve()
    home = Path.home().resolve()
    if folder == home or folder in home.parents or folder == Path(folder.anchor):
        raise HTTPException(status_code=400, detail="This folder is too broad for a workspace. Choose or create a folder just for this work.")
    if folder.exists() and not folder.is_dir():
        raise HTTPException(status_code=400, detail="This path is a file, not a folder.")
    return folder


class AppState:
    def __init__(self) -> None:
        self._manager: RunManager | None = None
        self._managers:dict[str,RunManager]={}
        self._queue_task=None
        self.closing=False
        from harness.outputs import OutputSessions
        self.outputs=OutputSessions()
        self._tickets: dict[str, tuple[Path, float]] = {}
        current = settings.load()["current_workspace"]
        if current:
            try:
                self.open(current)
            except (HTTPException, OSError):
                pass  # the folder is gone (moved, unplugged drive): start with no workspace open
        if self._manager is None:
            self.open(str(settings.home()/'projects'/'scratch'),'فضای ساخت برنامه')

    def open(self, path: str, name: str | None = None) -> Workspace:
        """Open (and, the first time, set up) a workspace folder. `name` is what the user calls it."""
        try:
            workspace = Workspace.at(_workspace_folder(path)).scaffold()
        except OSError as error:
            raise HTTPException(status_code=400, detail=f"This folder cannot be opened: {error.strerror or error}") from error
        self._manager = self._managers.setdefault(str(workspace.root),RunManager(workspace))
        data = settings.load()
        if str(workspace.root) not in data["workspaces"]:
            data["workspaces"].append(str(workspace.root))
        data["current_workspace"] = str(workspace.root)
        if name and name.strip():
            data["workspace_names"][str(workspace.root)] = name.strip()[:60]
        settings.save(data)
        return workspace

    def issue_ticket(self, file: Path, seconds: int = 4 * 3600) -> str:
        """A random, expiring pass for reading one file without the token (see the media routes)."""
        now = time.time()
        self._tickets = {ticket: entry for ticket, entry in self._tickets.items() if entry[1] > now}
        ticket = secrets.token_urlsafe(32)
        self._tickets[ticket] = (file, now + seconds)
        return ticket

    def ticket_file(self, ticket: str) -> Path | None:
        entry = self._tickets.get(ticket)
        return entry[0] if entry and entry[1] > time.time() else None

    def rename(self, name: str) -> str:
        """Give the open workspace a name. The folder itself is not renamed."""
        root = str(self.workspace.root)
        data = settings.load()
        data["workspace_names"][root] = name.strip()[:60]
        settings.save(data)
        return settings.workspace_name(data, root)

    @property
    def manager(self) -> RunManager:
        if self._manager is None:
            raise HTTPException(status_code=409, detail="No workspace is open. Create or open one first.")
        return self._manager

    @property
    def workspace(self) -> Workspace:
        return self.manager.workspace

    @property
    def controller(self) -> TaskController:
        """Plan/execute over the open workspace, using the configured default model.

        The controller is rebuilt per call: it is a thin view over the same
        RunManager and the product store, so settings never go stale and a new
        workspace does not keep an old runner.
        """
        return TaskController(self.manager, Store(), model_resolver=lambda: settings.model_spec(None))

    def is_running(self,thread_id):
        return any(manager.is_running(thread_id) for manager in self._managers.values())

    def controller_for(self,task_id):
        store=Store();task=store.task(task_id);root=store.workspace(task['workspace_id'])['root']
        manager=self._managers.get(root)
        if manager is None:
            manager=RunManager(Workspace.at(root));self._managers[root]=manager
        return TaskController(manager,store,model_resolver=lambda:settings.model_spec(None))

    def submit(self,phase,task_id,instruction=None):
        """FIFO for explicit user requests; waiting for HITL never holds a slot."""
        from .errors import ApiError
        store=Store();task=store.task(task_id)
        if self.closing:raise ApiError('workspace_busy','The engine is shutting down.',status_code=409)
        if task['status'] in {'recovery_required','closed','failed','cancelled'}:raise ApiError('conflict','This task cannot be queued.',status_code=409)
        if self.is_running(task['thread_id']):raise ApiError('workspace_busy','This task is already running.',status_code=409)
        plan=store.plan(task_id)
        if phase in {'execute','resume'} and (not plan or plan['approved_revision']!=plan['revision']):raise ApiError('action_not_approved','Approve the current plan first.',status_code=409)
        with store.db.read() as db:
            if db.execute("SELECT 1 FROM actions WHERE task_id=? AND invocation_key LIKE 'queue:%' AND state='pending'",(task_id,)).fetchone():raise ApiError('workspace_busy','This task already has a queued request.',status_code=409)
            queued=db.execute("SELECT 1 FROM actions WHERE invocation_key LIKE 'queue:%' AND state='pending' LIMIT 1").fetchone()
        busy=queued or store.worker_lease() or any(any(not task.done() for task in manager._tasks.values()) for manager in self._managers.values())
        if not busy:return self._dispatch(phase,task_id,instruction)
        payload={'phase':phase,'instruction':instruction,'plan_revision':plan['revision'] if plan else None}
        encoded=json.dumps(payload,sort_keys=True)
        action=store.ensure_action(task_id,'queue:'+uuid.uuid4().hex,hashlib.sha256(encoded.encode()).hexdigest())
        store.set_action_state(action['operation_id'],'pending',result_ref=encoded)
        store.set_task_status(task_id,'queued',reason='waiting_for_shared_worker')
        if self._queue_task is None or self._queue_task.done():self._queue_task=asyncio.create_task(self._drain())
        return store.task(task_id)

    def _dispatch(self,phase,task_id,instruction):
        store=Store();task=store.task(task_id)
        root=store.workspace(task['workspace_id'])['root']
        manager=self._managers.get(root)
        if manager is None:
            manager=RunManager(Workspace.at(root));self._managers[root]=manager
        controller=TaskController(manager,store,model_resolver=lambda:settings.model_spec(None))
        if phase=='plan':return controller.propose(task_id,instruction)
        if phase=='execute':return controller.execute(task_id)
        return controller.resume(task_id,[])

    async def _drain(self):
        store=Store()
        while not self.closing:
            with store.db.read() as db:
                row=db.execute("SELECT * FROM actions WHERE invocation_key LIKE 'queue:%' AND state='pending' ORDER BY rowid LIMIT 1").fetchone()
            if not row:return
            if store.worker_lease() or any(any(not task.done() for task in manager._tasks.values()) for manager in self._managers.values()):
                await asyncio.sleep(.15);continue
            task=store.task(row['task_id']);payload=json.loads(row['result_ref']);plan=store.plan(task['id'])
            if task['status']!='queued':store.set_action_state(row['operation_id'],'denied');continue
            if payload['phase']!='plan' and (not plan or plan['revision']!=payload['plan_revision'] or plan['approved_revision']!=plan['revision']):
                store.set_action_state(row['operation_id'],'denied');store.set_task_status(task['id'],'awaiting_plan',reason='queued_plan_changed');continue
            try:
                self._dispatch(payload['phase'],task['id'],payload['instruction'])
                store.set_action_state(row['operation_id'],'succeeded',result_ref=json.dumps({'dispatched':True}))
            except Exception as error:
                if getattr(error,'code',None)=='workspace_busy':await asyncio.sleep(.15);continue
                store.set_action_state(row['operation_id'],'failed',error='Queued request was refused; nothing was replayed.')
                store.set_task_status(task['id'],'paused',reason='queue_dispatch_refused')

    def activity(self):
        return {'running':[thread for manager in self._managers.values() for thread in manager._tasks if manager.is_running(thread)]+['output:'+s['id'] for s in self.outputs.sessions.values() if s['kind']!='html' and s['state'] in {'starting','installing','running','ready','stopping','unknown'}],'queued':bool(self._queue_task and not self._queue_task.done()),'worker_held':Store().worker_lease() is not None}

    async def shutdown(self,timeout=8):
        self.closing=True
        await asyncio.to_thread(self.outputs.close_all)
        if self._queue_task and not self._queue_task.done():
            self._queue_task.cancel()
            await asyncio.gather(self._queue_task,return_exceptions=True)
        store=Store()
        with store.db.read() as db:
            rows=db.execute("SELECT id,thread_id FROM tasks WHERE status IN ('queued','planning','executing','verifying','repairing','stopping','awaiting_action','awaiting_plan')").fetchall()
        for row in rows:
            manager=next((manager for manager in self._managers.values() if manager.is_running(row['thread_id'])),None)
            if manager:
                try:TaskController(manager,store,model_resolver=lambda:None).stop(row['id'])
                except Exception:store.set_task_status(row['id'],'recovery_required',reason='shutdown_stop_unconfirmed')
            elif store.task(row['id'])['status']=='queued':
                with store.db.write() as db:db.execute("UPDATE actions SET state='denied' WHERE task_id=? AND invocation_key LIKE 'queue:%' AND state='pending'",(row['id'],))
                store.set_task_status(row['id'],'paused',reason='shutdown_queue_paused')
        from harness.worktrees.candidate_checks import stop_candidate
        for row in rows:stop_candidate(store,row['id'])
        pending=[task for manager in self._managers.values() for task in manager._tasks.values() if not task.done()]
        if pending:await asyncio.wait(pending,timeout=timeout)
        result=self.activity()
        result['stopped']=not result['running'] and not result['worker_held']
        # A renderer may veto closing to preserve an unsaved draft. Stopped
        # queues stay paused; a later explicit user request may run normally.
        self.closing=False
        return result
