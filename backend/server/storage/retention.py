"""Explicit cache cleanup; task history, pins, captures and journals are retained."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import time

from ..errors import ApiError
from harness.worktrees.coordination import exclusive_entry

DEFAULT_POLICY={'retention_days':30,'cache_limit_gb':5}
MIN_FREE_BYTES=128*1024**2
CACHES=('node_modules','.venv','.pytest_cache','.mypy_cache','.ruff_cache')


def require_space(store):
    if shutil.disk_usage(store.db.path.parent).free<MIN_FREE_BYTES:
        raise ApiError('runtime_unavailable','فضای ذخیره‌سازی کافی نیست؛ پیش از ایجاد کار، داده‌های محلی را بررسی کنید.',status_code=409,details={'reason':'storage_low','minimum_free_bytes':MIN_FREE_BYTES})


def policy(store):
    path=store.db.path.parent/'data-policy.json'
    try:
        value=json.loads(path.read_text(encoding='utf8'))
        if type(value['retention_days']) is int and 1<=value['retention_days']<=3650 and type(value['cache_limit_gb']) is int and 1<=value['cache_limit_gb']<=50:return {key:value[key] for key in DEFAULT_POLICY}
    except (OSError,ValueError,KeyError,TypeError):pass
    return dict(DEFAULT_POLICY)


def save_policy(store,value):
    from harness.skill_repin import _write
    _write(store.db.path.parent/'data-policy.json',value)
    return policy(store)


def linked(path):
    info=path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&0x400)


def tree(path,root):
    """Bounded metadata scan, refusing links, reparse points and special files."""
    target=path.absolute();base=root.absolute()
    if target==base or not target.is_relative_to(base):raise ValueError('outside cache storage')
    for parent in [target,*target.parents]:
        if parent.exists() and linked(parent):raise ValueError('linked cache parent')
    if not target.resolve().is_relative_to(base.resolve()):raise ValueError('outside resolved storage')
    rows=[];size=0;newest=0;pending=[target]
    while pending:
        item=pending.pop();info=item.lstat()
        if linked(item) or (not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode)):raise ValueError('unsupported cache entry')
        if info.st_nlink>1 and stat.S_ISREG(info.st_mode):raise ValueError('linked cache file')
        rows.append((item.relative_to(base).as_posix(),info.st_size,info.st_mtime_ns,info.st_ino))
        newest=max(newest,info.st_mtime)
        if len(rows)>50000:raise ValueError('cache scan limit')
        if stat.S_ISDIR(info.st_mode):pending.extend(item.iterdir())
        else:size+=info.st_size
    fingerprint=hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest()
    return {'bytes':size,'files':sum(not (base/row[0]).is_dir() for row in rows),'newest':newest,'fingerprint':fingerprint}


def preview(store):
    root=store.db.path.parent/'tasks';prefs=policy(store);items=[];protected=0;skipped=0;cache_bytes=0
    with store.db.read() as db:
        tasks=db.execute('SELECT id,status,workspace_id,updated_at FROM tasks').fetchall()
        uncertain={row[0] for row in db.execute("SELECT DISTINCT task_id FROM actions WHERE state IN ('pending','awaiting_approval','dispatching','running','unknown')")}
        uncertain.update(row[0] for row in db.execute("SELECT DISTINCT task_id FROM apply_operations WHERE state IN ('prepared','applying','partial','unknown')"))
        busy_workspaces={row[0] for row in db.execute("SELECT workspace_id FROM workspace_leases WHERE state IN ('active','quarantined')")}
    cutoff=time.time()-prefs['retention_days']*86400
    for task in tasks:
        if task['status'] not in {'closed','failed','cancelled'} or task['id'] in uncertain or task['workspace_id'] in busy_workspaces:
            protected+=1;continue
        if not re.fullmatch(r'task_[A-Za-z0-9]+',task['id']):skipped+=1;continue
        folder=root/task['id']
        if not folder.is_dir():continue
        if linked(folder):skipped+=1;continue
        candidates=[folder/'working'/name for name in CACHES]
        candidates.extend(path for path in folder.glob('candidate-check-*') if re.fullmatch(r'candidate-check-op_[A-Za-z0-9]+-[A-Za-z0-9_-]+',path.name))
        for path in candidates:
            if not path.exists():continue
            try:details=tree(path,root)
            except (OSError,ValueError):skipped+=1;continue
            cache_bytes+=details['bytes']
            if max(task['updated_at'],details['newest'])>cutoff:continue
            relative=path.relative_to(root).as_posix()
            items.append({'id':hashlib.sha256(relative.encode()).hexdigest(),'task_id':task['id'],'category':'dependencies' if path.name in {'node_modules','.venv'} else 'temporary_checks' if path.name.startswith('candidate-check-') else 'cache','relative':relative,**details})
    items.sort(key=lambda row:row['id'])
    digest=hashlib.sha256(json.dumps({'items':items,'policy':prefs},sort_keys=True).encode()).hexdigest()
    disk=shutil.disk_usage(store.db.path.parent)
    return {'preview_hash':digest,'policy':prefs,'items':items,'reclaimable_bytes':sum(row['bytes'] for row in items),'cache_bytes':cache_bytes,'protected_tasks':protected,'skipped_entries':skipped,'disk_free_bytes':disk.free,'cache_limit_exceeded':cache_bytes>prefs['cache_limit_gb']*1024**3,'data_directory':str(store.db.path.parent),'preserved':['history','working_source','baseline','pins','checkpoints','apply_journals','recovery']}


def cleanup(store,*,preview_hash,item_ids,confirm=False):
    if not confirm:raise ApiError('action_not_approved','Review the cache cleanup and confirm explicitly.',status_code=409)
    if not item_ids or len(set(item_ids))!=len(item_ids):raise ApiError('invalid_request','Select distinct cache entries.',status_code=422)
    with exclusive_entry():
        worker=store.acquire_worker('retention')
        try:
            fresh=preview(store)
            if fresh['preview_hash']!=preview_hash:raise ApiError('selection_stale','Cleanup candidates changed; preview again.',status_code=409)
            allowed={row['id']:row for row in fresh['items']}
            if any(key not in allowed for key in item_ids):raise ApiError('invalid_request','Unknown cleanup entry.',status_code=422)
            root=(store.db.path.parent/'tasks').absolute();deleted=[];failed=[]
            for key in item_ids:
                row=allowed[key];target=root/row['relative']
                try:
                    # Absolute containment and every reparse point are checked
                    # immediately before native deletion, under the shared worker.
                    if tree(target,root)['fingerprint']!=row['fingerprint']:raise ValueError('changed cache')
                    if target.is_dir():shutil.rmtree(target)
                    else:target.unlink()
                    deleted.append(key)
                except (OSError,ValueError):failed.append(key)
            return {'deleted':deleted,'failed':failed,'deleted_bytes':sum(allowed[key]['bytes'] for key in deleted),'history_deleted':False,'project_files_deleted':False}
        finally:store.release_worker(worker.id,worker.fencing_token)
