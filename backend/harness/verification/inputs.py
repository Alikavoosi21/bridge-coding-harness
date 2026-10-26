"""Recognized test/config inputs need explicit plan scope and renewed consent.

This is a deterministic guard for conventional projects, not a proof of the
semantics of arbitrary shell scripts. Whole-copy hashes still bind check results.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
from pathlib import PurePosixPath

from ..worktrees.snapshot import build,load_manifest,manifest_path


def is_check_input(path: str,profile: dict) -> bool:
    relative=PurePosixPath(path.lstrip('/'));name=relative.name
    declared={str(row.get('source','')).split('#',1)[0] for row in profile.get('commands',[])}
    if str(relative) in declared:return True
    if any(part in {'tests','test','__tests__'} for part in relative.parts):return True
    return name in {'package.json','pyproject.toml','pytest.ini','tox.ini','setup.cfg','conftest.py'} or any(fnmatch.fnmatchcase(name,pattern) for pattern in ('test_*.py','*_test.py','*.test.*','*.spec.*','jest.config.*','vitest.config.*'))


def check_input_digest(root,profile: dict) -> bytes:
    files=sorted((entry.path,entry.sha256,entry.size) for entry in build(root).files if is_check_input(entry.path,profile))
    return hashlib.sha256(json.dumps(files,ensure_ascii=False,separators=(',',':')).encode()).digest()


def changed_check_inputs(root,profile: dict) -> list[str]:
    original=load_manifest(manifest_path(root))
    if original is None:return []  # fixture backends; product assembly stores this manifest
    before={entry.path:entry.sha256 for entry in original.files if is_check_input(entry.path,profile)}
    after={entry.path:entry.sha256 for entry in build(root).files if is_check_input(entry.path,profile)}
    return sorted(path for path in before.keys()|after.keys() if before.get(path)!=after.get(path))


def covered_by_plan(paths: list[str],plan) -> bool:
    # A broad directory/glob does not silently authorize rewriting test criteria.
    approved={str(path).lstrip('/') for path in (plan or {}).get('scope',[])}
    return bool(plan and plan.get('approved_revision')==plan.get('revision')) and all(path in approved for path in paths)


def changed_inputs_reviewed(store,task_id,root,profile,runtime) -> bool:
    changed=changed_check_inputs(root,profile)
    if not changed:return True
    task=store.task(task_id);plan=task.get('plan')
    if not covered_by_plan(changed,plan):return False
    from ..command_context import command_details
    from ..policy import ActionContext
    with store.db.read() as db:
        receipts=db.execute("SELECT r.request_json,r.action_hash FROM approvals r JOIN actions a ON a.operation_id=r.action_id WHERE r.task_id=? AND r.state='decided' AND r.decision='approve' AND r.action_hash=a.args_hash AND a.plan_revision=?",(task_id,plan['revision'])).fetchall()
    commands=[row['command'] for row in profile.get('commands',[]) if row.get('required')]
    for command in commands:
        matched=False
        for receipt in receipts:
            saved=json.loads(receipt['request_json'] or 'null')
            if not saved or saved['tool']!='execute' or saved['args'].get('command')!=command:continue
            if saved['runtime']!=runtime or saved['environment_profile']!='offline:'+profile['profile_hash'] or saved['plan_revision']!=plan['revision']:continue
            script=command_details({'name':'execute','args':saved['args']},profile,root)[2]
            context=ActionContext('execute',saved['args'],saved['cwd'],saved['shell'],runtime,saved['environment_profile'],plan['revision'],script=script)
            if context.fingerprint()==receipt['action_hash']:matched=True;break
        if not matched:return False
    return True
