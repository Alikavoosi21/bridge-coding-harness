"""Bind shell consent to the saved profile and actual local script bytes."""
from __future__ import annotations

import json
import hashlib
import shlex
from pathlib import Path
from typing import Any

from .worktrees.snapshot import UnsafePath, _is_link_path, excluded, validate_relative, within


def profile_identity(profile):
    # No configured checks is a real state, not a prerequisite to delivering a file.
    return profile.get('profile_hash') if profile else hashlib.sha256(b'{}').hexdigest()


def saved_profile(store, task: dict[str,Any]) -> dict[str,Any]:
    value=store.workspace(task['workspace_id']).get('profile')
    profile=json.loads(value) if isinstance(value,str) else value
    return profile if isinstance(profile,dict) else {}


def command_details(call: dict[str,Any], profile: dict[str,Any], root: Path | None,*,skills_root:Path|None=None):
    """Flags come from the server profile/command text, not model-supplied flags.

    The installer classification recognizes package-manager invocations. It is
    not a general semantic proof about arbitrary code; isolation remains the
    runtime boundary and shell networking remains disabled by default.
    """
    if call['name']!='execute':return False,False,b''
    command=str((call.get('args') or {}).get('command') or '')
    if '.harness/skills' in command:
        raise UnsafePath('Execute skill scripts from the read-only /skills mount, not a working cache.')
    try:tokens=shlex.split(command)
    except ValueError:raise ValueError('The command cannot be parsed for review.') from None
    commands=profile.get('commands') or []
    verifier=any(row.get('command')==command for row in commands)
    install=bool(profile.get('install') and profile['install'].get('command')==command)
    # Classify common direct installer forms, including python -m pip / uv pip.
    words=[token.rsplit('/',1)[-1].lower() for token in tokens]
    managers={'npm','pnpm','yarn','bun','pip','pip3','uv','poetry','pdm','pipenv','conda'}
    verbs={'install','i','ci','add','sync','update','upgrade'}
    install=install or any(word in managers and any(next_word in verbs for next_word in words[index+1:]) for index,word in enumerate(words))
    sources={'package.json','pyproject.toml'}
    if install:
        sources.update({'package-lock.json','npm-shrinkwrap.json','pnpm-lock.yaml','yarn.lock','bun.lock','bun.lockb','uv.lock','poetry.lock','pdm.lock','requirements.txt','requirements-dev.txt'})
    sources.update(str(row['source']) for row in commands if row.get('command')==command and row.get('source'))
    sources.update(token.removeprefix('/workspace/') for token in tokens if token.endswith(('.py','.sh','.js','.mjs','.cjs','.ts')))
    pieces=[]
    if root:
        for source in sorted(sources):
            selected_root=root
            if source.startswith('/skills/'):
                if skills_root is None:raise UnsafePath('No pinned skill mount is available.')
                selected_root=Path(skills_root);source=source.removeprefix('/skills/')
            if '.harness/skills/' in source:raise UnsafePath('Execute pinned skill scripts from /skills/, not the working cache.')
            relative=validate_relative(source)
            file=selected_root.joinpath(*relative.parts)
            if excluded(relative) or not within(selected_root,file) or _is_link_path(file.parent) or file.is_symlink():
                raise UnsafePath('A command source is excluded or is a link.')
            if not file.exists():continue
            if _is_link_path(file):raise UnsafePath('A command source is a link.')
            if not file.is_file() or file.stat().st_size>2_000_000:raise ValueError('Command source is too large for a safe fingerprint.')
            data=file.read_bytes()
            pieces.append(source.encode()+b'\0'+str(len(data)).encode()+b'\0'+data)
    if skills_root is not None:
        from .verification.observe import snapshot_hash
        from .worktrees.snapshot import build
        pinned=Path(skills_root)
        if _is_link_path(pinned):raise UnsafePath('Pinned skills are unavailable or linked.')
        # Bind the whole collection, including imported helpers and indirect
        # shell invocations. The model never receives these bodies as context.
        pieces.append(b'pinned-skills\0'+snapshot_hash(build(pinned)).encode())
    if verifier and root:
        from .verification.inputs import check_input_digest
        pieces.append(b'check-inputs\0'+check_input_digest(root,profile))
    return install,verifier,b'\0'.join(pieces)
