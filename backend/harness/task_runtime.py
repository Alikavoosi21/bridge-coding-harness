"""One task's copy and one segment's leases; never a mount of the original."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from deepagents.backends import CompositeBackend

from .backends import ReadOnlyBackend
from .runtime.docker import ContainerConfig, DockerRuntime, RuntimeUnavailable
from .sandbox import build_container_backend
from .workspace import Workspace
from .worktrees.lease import WriterLease
from .worktrees.snapshot import UnsafePath, _is_link_path, build, load_manifest, manifest_path, sync,write_manifest


def task_directory(store, task_id: str) -> Path:
    if not re.fullmatch(r'task_[A-Za-z0-9]+',task_id):raise ValueError('Invalid task identity')
    return store.db.path.parent/'tasks'/task_id


def runtime_descriptor(store, task_id: str) -> dict[str, Any] | None:
    file=task_directory(store,task_id)/'runtime.json'
    return json.loads(file.read_text(encoding='utf8')) if file.exists() else None


@dataclass
class TaskRuntime:
    backend: Any
    workspace: Workspace
    runtime_id: str
    store: Any
    task: dict[str,Any]
    worker: Any
    writer: Any = None
    closed: bool = False

    def close(self):
        if self.closed:return
        self.closed=True
        try:
            if self.writer:
                with self.store.db.write() as db:
                    unknown=db.execute("SELECT 1 FROM actions WHERE task_id=? AND state IN ('unknown','dispatching','running') LIMIT 1",(self.task['id'],)).fetchone()
                    if unknown:db.execute("UPDATE workspace_leases SET state='quarantined' WHERE id=?",(self.writer.id,))
                if unknown:self.store.set_task_status(self.task['id'],'recovery_required',reason='operation_result_unknown')
                else:self.store.release_workspace_lease(self.writer.id,self.writer.fencing_token)
        finally:
            self.store.release_worker(self.worker.id,self.worker.fencing_token)


def open_task_runtime(workspace: Workspace, store, task_id: str, *, read_only: bool, max_seconds: int, runtime=None) -> TaskRuntime:
    task=store.task(task_id)
    source=Path(store.workspace(task['workspace_id'])['root']).resolve()
    if source!=workspace.root.resolve():raise RuntimeUnavailable('Open the task workspace before execution.')
    root=task_directory(store,task_id)
    working=root/'working'
    if root.resolve().is_relative_to(source):raise RuntimeUnavailable('Task storage must be outside the original project.')
    worker=store.acquire_worker('task:'+task_id)
    writer=None
    try:
        from .skill_repin import marker as skill_repin_marker
        repin_state=skill_repin_marker(store,task_id)
        if repin_state and repin_state.get('status')!='applied':raise RuntimeUnavailable('Interrupted skill re-pin needs recovery.')
        with store.db.read() as db:
            if db.execute("SELECT 1 FROM actions WHERE task_id=? AND invocation_key LIKE 'skill-repin:%' AND state IN ('dispatching','running','unknown') LIMIT 1",(task_id,)).fetchone():
                raise RuntimeUnavailable('Skill re-pin result is not confirmed; recovery is required.')
        try:
            capture_path=manifest_path(working)
            if capture_path.is_symlink() or (capture_path.exists() and _is_link_path(capture_path)):raise ValueError('linked snapshot manifest')
            snapshot=load_manifest(manifest_path(working))
        except (OSError,ValueError,KeyError,TypeError) as error:
            store.set_task_status(task_id,'recovery_required',reason='snapshot_identity_invalid')
            raise RuntimeUnavailable('The saved snapshot manifest needs explicit recovery.') from error
        if snapshot is None:
            # Existing task bytes without their capture identity are legacy or
            # interrupted state, never permission to overwrite from today's source.
            if working.exists() or (root/'baseline').exists() or (root/'runtime.json').exists():
                store.set_task_status(task_id,'recovery_required',reason='snapshot_identity_missing')
                raise RuntimeUnavailable('Existing task files lack a valid snapshot manifest; review migration before continuing.')
            snapshot=build(source)
            # Keep original bytes outside every agent mount for later diff and
            # restore. Build the working copy from those captured bytes, so a
            # concurrent edit of the source cannot split the two baselines.
            baseline=root/'baseline'
            sync(snapshot,baseline)
            sync(replace(snapshot,root=baseline),working,write_manifest_file=False)
            write_manifest(snapshot,working)
            # Memory is copied once. Skills come only from reviewed, pinned
            # registry copies below, never from a live project source.
            for name in ('memory',):
                knowledge=workspace.harness/name
                target=root/'knowledge'/name
                target.mkdir(parents=True,exist_ok=True)
                if knowledge.exists():
                    if _is_link_path(knowledge) or not knowledge.resolve().is_relative_to(source):raise UnsafePath('Knowledge source must not be a link.')
                    sync(build(knowledge),target)
                    sync(build(target),working/'.harness'/name)
        elif snapshot.root.resolve()!=source or not working.is_dir():
            store.set_task_status(task_id,'recovery_required',reason='snapshot_identity_mismatch')
            raise RuntimeUnavailable('The saved task snapshot needs recovery.')
        from .skills_registry import SkillRegistry
        registry=SkillRegistry(store)
        if not (root/'skill-pins.json').exists():registry.bootstrap(task['workspace_id'])
        registry.pin_task(task_id)
        if not (working/'.harness'/'skills').exists():
            sync(build(root/'knowledge'/'skills'),working/'.harness'/'skills',write_manifest_file=False)
        # Never sync from the original on resume: that would destroy agent edits.
        data_workspace=Workspace.at(working)
        if read_only or task['read_only']:
            backend=CompositeBackend(default=ReadOnlyBackend(root_dir=working,virtual_mode=True),routes={f'/.harness/{name}/':ReadOnlyBackend(root_dir=root/'knowledge'/name,virtual_mode=True) for name in ('skills','memory')})
            return TaskRuntime(backend,data_workspace,'read-only',store,task,worker)
        old=runtime_descriptor(store,task_id)
        from .runtime.local import runtime_for
        runtime=runtime or runtime_for(old)
        identifier=runtime.pin_image()
        runtime_id=hashlib.sha256(json.dumps(asdict(runtime.config),sort_keys=True).encode()).hexdigest()
        descriptor={'image':identifier,'runtime_id':runtime_id}
        if old and old!=descriptor:
            if getattr(runtime,'local',False) and not str(old['image']).startswith('bridge-local'):
                with store.db.write() as db:
                    db.execute('UPDATE plans SET approved_revision=NULL WHERE task_id=?',(task_id,))
                    db.execute('UPDATE grants SET revoked_at=? WHERE task_id=? AND revoked_at IS NULL',(__import__('time').time(),task_id))
                temporary=root/'runtime.tmp';temporary.write_text(json.dumps(descriptor),encoding='utf8');temporary.replace(root/'runtime.json')
                store.set_task_status(task_id,'awaiting_plan',reason='local_runtime_requires_approval')
                raise RuntimeUnavailable('محیط این گفتگو به اجرای محلی تغییر کرد؛ برنامه را دوباره تأیید کن. فایل‌ها حفظ شدند.')
            raise RuntimeUnavailable('The task runtime changed; a fresh review is required.')
        root.mkdir(parents=True,exist_ok=True)
        temporary=root/'runtime.tmp';temporary.write_text(json.dumps(descriptor),encoding='utf8');temporary.replace(root/'runtime.json')
        writer=store.acquire_workspace_lease(task['workspace_id'],task_id,'execute',ttl_s=max_seconds+60)
        lease=WriterLease(task['workspace_id'],writer.id,writer.fencing_token,store.workspace_lease)
        backend=build_container_backend(workspace,replace(snapshot,root=working),runtime,skills=root/'knowledge'/'skills')
        backend.set_lease(lease)
        composite=CompositeBackend(default=backend,routes={f'/.harness/{name}/':ReadOnlyBackend(root_dir=root/'knowledge'/name,virtual_mode=True) for name in ('skills','memory')})
        return TaskRuntime(composite,data_workspace,runtime_id,store,task,worker,writer)
    except BaseException:
        if writer:store.release_workspace_lease(writer.id,writer.fencing_token)
        store.release_worker(worker.id,worker.fencing_token)
        raise
