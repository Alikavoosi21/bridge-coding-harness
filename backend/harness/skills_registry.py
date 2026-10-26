"""Local skill sources and reviewed immutable copies; content is never consent.

The agent's SkillsMiddleware remains responsible for progressive loading. This
registry lists metadata only; full instructions are returned by explicit preview.
"""
import json
import os
from pathlib import Path
import re
import time
import uuid

import yaml

from server.errors import ApiError
from .worktrees.snapshot import build,sync,_is_link_path,SnapshotTooLarge
from .verification.observe import snapshot_hash


def parse_skill_text(text):
    """Parse user-supplied SKILL.md as data; never execute its instructions."""
    if len(text.encode('utf-8'))>65536:raise ValueError('SKILL.md must be at most 64 KiB.')
    lines=text.lstrip('\ufeff').splitlines()
    if not lines or lines[0]!='---':raise ValueError('SKILL.md requires YAML frontmatter with name and description.')
    end=next((i for i in range(1,len(lines)) if lines[i]=='---'),None)
    if end is None:raise ValueError('Close the YAML frontmatter with ---.')
    metadata=yaml.safe_load('\n'.join(lines[1:end]))
    if not isinstance(metadata,dict):raise ValueError('Skill frontmatter must be a mapping.')
    name=metadata.get('name');description=metadata.get('description')
    if not isinstance(name,str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name) or len(name)>64:raise ValueError('Skill name must use lowercase letters, numbers and hyphens.')
    if not isinstance(description,str) or not description.strip() or len(description)>1024:raise ValueError('Skill description must contain 1–1024 characters.')
    return {'name':name,'description':description.strip(),'body':'\n'.join(lines[end+1:]).strip()}


def scan_skill_sources(source):
    """Bounded discovery in a single skill or nested collection; read-only."""
    root=Path(source).absolute()
    if not root.is_dir() or any(_is_link_path(p) for p in [root,*root.parents]):
        raise ApiError('invalid_request','یک پوشهٔ عادی برای مهارت یا مجموعهٔ مهارت انتخاب کن.',status_code=422)
    items=[];visited=0;truncated=False
    for directory,folders,files in os.walk(root,followlinks=False):
        visited+=1;current=Path(directory)
        folders[:]=sorted(name for name in folders if name not in {'.git','node_modules','.venv','__pycache__','.next'} and not _is_link_path(current/name))
        if len(current.relative_to(root).parts)>=6:
            truncated=truncated or bool(folders);folders[:]=[]
        if visited>1024 or len(items)>=128:truncated=True;break
        if 'SKILL.md' not in files:continue
        preview=inspect_source(current)
        items.append({'source':str(current),'relative':current.relative_to(root).as_posix(),**{k:preview.get(k) for k in ('valid','name','description','error')}})
        # Resource folders belong to this skill, not to another collection.
        folders[:]=[]
    return {'items':items,'truncated':truncated}


def inspect_source(source,*,body=False):
    root=Path(source).absolute()
    try:
        if not root.is_dir() or any(_is_link_path(parent) for parent in [root,*root.parents]):
            raise ValueError('Skill source must be a regular directory without linked parents.')
        snapshot=build(root,max_files=256,max_bytes=8_000_000)
        if any('link' in row['reason'] or row['reason']=='secret file' for row in snapshot.excluded):
            raise ValueError('Remove linked or secret files from the skill source before enabling it.')
        entry=snapshot.by_path().get('SKILL.md')
        if entry is None or entry.size>65536:raise ValueError('SKILL.md is missing or larger than 64 KiB.')
        import hashlib
        with (root/'SKILL.md').open('rb') as file:data=file.read(65537)
        if len(data)>65536 or hashlib.sha256(data).hexdigest()!=entry.sha256:
            raise ValueError('SKILL.md changed during inspection; preview again.')
        text=data.decode('utf-8-sig')
        lines=text.splitlines()
        if not lines or lines[0]!='---':raise ValueError('SKILL.md requires YAML frontmatter.')
        end=next((index for index in range(1,len(lines)) if lines[index]=='---'),None)
        if end is None:raise ValueError('Close the YAML frontmatter with ---.')
        metadata=yaml.safe_load('\n'.join(lines[1:end]))
        if not isinstance(metadata,dict):raise ValueError('Skill frontmatter must be a mapping.')
        name=metadata.get('name');description=metadata.get('description')
        if not isinstance(name,str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name) or len(name)>64:
            raise ValueError('Skill name must use lowercase letters, numbers and single hyphens (up to 64 characters).')
        if not isinstance(description,str) or not description.strip() or len(description)>1024:
            raise ValueError('Skill description must contain 1–1024 characters.')
        result={'valid':True,'name':name,'description':description.strip(),'current_hash':snapshot_hash(snapshot),'files':[entry.path for entry in snapshot.files],'excluded':list(snapshot.excluded)}
        if body:result['body']='\n'.join(lines[end+1:]).strip()
        return result
    except (OSError,UnicodeError,ValueError,yaml.YAMLError,SnapshotTooLarge) as error:
        return {'valid':False,'error':str(error),'current_hash':None}


class SkillRegistry:
    def __init__(self,store):self.store=store

    def bootstrap(self,workspace_id):
        """Bundled default is trusted by product identity, not project pathname.

        Discovery only registers project sources disabled. Neither discovery nor
        startup re-enables a source the user disabled or removed previously.
        """
        bundled=Path(__file__).with_name('bundled')/'coding-checks'
        with self.store.db.read() as db:
            existing=db.execute("SELECT id FROM skill_sources WHERE source=? AND scope='bundled'",(str(bundled),)).fetchone()
        if existing is None:
            metadata=inspect_source(bundled)
            if not metadata['valid']:raise ApiError('recovery_required','Bundled skill is invalid.',status_code=409)
            identifier='skill_'+uuid.uuid4().hex[:20]
            with self.store.db.write() as db:db.execute("INSERT INTO skill_sources(id,source,scope,hash,enabled,trust,created_at) VALUES(?,?,?, ?,0,'unreviewed',?) ON CONFLICT DO NOTHING",(identifier,str(bundled),'bundled',metadata['current_hash'],time.time()))
            with self.store.db.read() as db:identifier=db.execute("SELECT id FROM skill_sources WHERE source=? AND scope='bundled'",(str(bundled),)).fetchone()['id']
            self.enable(identifier,expected_hash=metadata['current_hash'],confirm=True)
        workspace=Path(self.store.workspace(workspace_id)['root'])
        errors=[]
        for folder in (workspace/'.harness'/'skills',workspace/'.agents'/'skills'):
            if not folder.exists():continue
            if _is_link_path(folder):errors.append({'source':str(folder),'error':'Skill collection is a link.'});continue
            for child in sorted(folder.iterdir())[:64]:
                if not child.is_dir():continue
                with self.store.db.read() as db:
                    known=db.execute('SELECT id FROM skill_sources WHERE source=? AND scope=?',(str(child.absolute()),'project:'+workspace_id)).fetchone()
                if known:continue
                try:self.register(child,scope='project',workspace_id=workspace_id)
                except ApiError as error:errors.append({'source':str(child),'error':error.message})
        return errors

    def register(self,source,*,scope,workspace_id=None):
        if scope not in {'personal','project'}:raise ApiError('invalid_request','Unsupported skill scope.',status_code=422)
        root=Path(source).absolute()
        if scope=='project':
            if not workspace_id:raise ApiError('invalid_request','A project skill requires its workspace.',status_code=422)
            workspace=Path(self.store.workspace(workspace_id)['root']).resolve()
            if not root.resolve().is_relative_to(workspace):raise ApiError('invalid_request','Project skill source must stay in that project.',status_code=422)
            scope='project:'+workspace_id
        preview=inspect_source(root)
        identifier='skill_'+uuid.uuid4().hex[:20]
        with self.store.db.write() as db:
            db.execute("INSERT INTO skill_sources(id,source,scope,hash,enabled,trust,created_at) VALUES(?,?,?,?,0,'unreviewed',?) ON CONFLICT(source,scope) DO UPDATE SET trust=CASE WHEN skill_sources.trust='removed' THEN 'unreviewed' ELSE skill_sources.trust END",(identifier,str(root),scope,preview.get('current_hash') or '',time.time()))
            row=db.execute('SELECT id FROM skill_sources WHERE source=? AND scope=?',(str(root),scope)).fetchone()
        return self.detail(row['id'])

    def _row(self,identifier):
        with self.store.db.read() as db:row=db.execute('SELECT * FROM skill_sources WHERE id=?',(identifier,)).fetchone()
        if row is None:raise ApiError('not_found','Skill source not found.',status_code=404)
        return dict(row)

    def detail(self,identifier,*,body=False):
        row=self._row(identifier)
        preview=inspect_source(row['source'],body=body)
        return {key:value for key,value in row.items() if key!='copy_ref'}|preview|{'enabled':bool(row['enabled']),'changed':preview.get('current_hash')!=row['hash'],'accepted_hash':row['hash']}

    def list(self,workspace_id=None):
        with self.store.db.read() as db:
            rows=db.execute("SELECT id FROM skill_sources WHERE trust!='removed' AND (scope IN ('personal','bundled') OR scope=?) ORDER BY created_at,id",('project:'+str(workspace_id),)).fetchall()
        return [self.detail(row['id']) for row in rows]

    def enable(self,identifier,*,expected_hash,confirm=False):
        if not confirm:raise ApiError('action_not_approved','Review the source and explicitly enable this skill.',status_code=409)
        row=self._row(identifier);preview=inspect_source(row['source'])
        if not preview['valid']:raise ApiError('invalid_request',preview['error'],status_code=422)
        if preview['current_hash']!=expected_hash:raise ApiError('selection_stale','Skill source changed after preview.',status_code=409)
        copy=self.store.db.path.parent/'skill-copies'/expected_hash
        copy.parent.mkdir(exist_ok=True)
        if copy.exists():
            if _is_link_path(copy) or snapshot_hash(build(copy))!=expected_hash:
                raise ApiError('recovery_required','The reviewed skill copy changed.',status_code=409)
        else:
            import tempfile
            with tempfile.TemporaryDirectory(prefix='skill-',dir=copy.parent) as temporary:
                staging=Path(temporary)/'copy'
                sync(build(row['source'],max_files=256,max_bytes=8_000_000),staging,write_manifest_file=False)
                if snapshot_hash(build(staging))!=expected_hash:raise ApiError('selection_stale','Skill changed during capture.',status_code=409)
                staging.rename(copy)
        with self.store.db.write() as db:db.execute("UPDATE skill_sources SET enabled=1,trust='reviewed',hash=?,copy_ref=? WHERE id=?",(expected_hash,str(copy),identifier))
        return self.detail(identifier)

    def disable(self,identifier):
        self._row(identifier)
        with self.store.db.write() as db:db.execute('UPDATE skill_sources SET enabled=0 WHERE id=?',(identifier,))
        return self.detail(identifier)

    def forget(self,identifier):
        """Keep source and pinned history. Unregister by disabling its entry."""
        self._row(identifier)
        with self.store.db.write() as db:db.execute("UPDATE skill_sources SET enabled=0,trust='removed' WHERE id=?",(identifier,))
        return {'id':identifier,'removed':True,'source_deleted':False}

    def pin_task(self,task_id):
        """First capture only. Later calls reconstruct the same reviewed hashes.

        Called by the task runtime while it owns the shared worker. An existing
        pin never follows current registry/source updates or enable changes.
        """
        from .task_runtime import task_directory
        task=self.store.task(task_id);directory=task_directory(self.store,task_id)
        marker=directory/'skill-pins.json'
        with self.store.db.read() as db:
            pinned=db.execute('SELECT p.skill_id,p.hash,s.scope FROM skill_pins p JOIN skill_sources s ON s.id=p.skill_id WHERE p.task_id=? ORDER BY p.skill_id',(task_id,)).fetchall()
            if not pinned and not marker.exists():
                pinned=db.execute("SELECT id AS skill_id,hash,scope FROM skill_sources WHERE enabled=1 AND trust='reviewed' AND (scope IN ('personal','bundled') OR scope=?) ORDER BY id",('project:'+task['workspace_id'],)).fetchall()
        planned=[];names=set()
        for pin in pinned:
            copy=self.store.db.path.parent/'skill-copies'/pin['hash']
            metadata=inspect_source(copy)
            if not metadata['valid'] or metadata['current_hash']!=pin['hash']:
                raise ApiError('recovery_required','A pinned skill copy is unavailable or changed.',status_code=409)
            if metadata['name'] in names:raise ApiError('conflict','Enabled skill names overlap; disable one source before starting the task.',status_code=409)
            names.add(metadata['name'])
            planned.append({'skill_id':pin['skill_id'],'hash':pin['hash'],'scope':pin['scope'],'name':metadata['name'],'description':metadata['description']})
        root=directory/'knowledge'/'skills';root.mkdir(parents=True,exist_ok=True)
        if _is_link_path(root):raise ApiError('recovery_required','Pinned skill directory is a link.',status_code=409)
        if any(path.name not in names for path in root.iterdir()):
            raise ApiError('recovery_required','Untracked skill content exists in this task; review migration before loading it.',status_code=409)
        for pin in planned:
            target=root/pin['name'];source=self.store.db.path.parent/'skill-copies'/pin['hash']
            if target.exists():
                if _is_link_path(target) or snapshot_hash(build(target))!=pin['hash']:
                    raise ApiError('recovery_required','Task skill pin was changed; it will not be silently replaced.',status_code=409)
            else:sync(build(source),target,write_manifest_file=False)
        with self.store.db.write() as db:
            for pin in planned:db.execute('INSERT INTO skill_pins(task_id,skill_id,hash,pinned_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING',(task_id,pin['skill_id'],pin['hash'],time.time()))
        encoded=json.dumps(planned,ensure_ascii=False,sort_keys=True)
        if marker.exists():
            if _is_link_path(marker) or marker.read_text(encoding='utf8')!=encoded:
                raise ApiError('recovery_required','The saved skill pin manifest differs from its registry rows.',status_code=409)
        else:
            from .worktrees.edit import _durable
            _durable(marker,encoded.encode('utf8'))
        return planned

    def task_pins(self,task_id):
        """Inspect durable pins without creating/updating a task snapshot."""
        from .task_runtime import task_directory
        self.store.task(task_id)
        with self.store.db.read() as db:
            rows=db.execute('SELECT p.skill_id,p.hash,p.pinned_at,s.source,s.scope,s.enabled FROM skill_pins p JOIN skill_sources s ON s.id=p.skill_id WHERE p.task_id=? ORDER BY p.skill_id',(task_id,)).fetchall()
        result=[]
        for row in rows:
            copy=self.store.db.path.parent/'skill-copies'/row['hash']
            metadata=inspect_source(copy)
            valid=metadata['valid'] and metadata['current_hash']==row['hash']
            if valid:
                task_copy=task_directory(self.store,task_id)/'knowledge'/'skills'/metadata['name']
                valid=not _is_link_path(task_copy.parent) and not _is_link_path(task_copy) and snapshot_hash(build(task_copy))==row['hash']
            result.append({**dict(row),'enabled':bool(row['enabled']),'name':metadata.get('name'),'description':metadata.get('description'),'valid':valid})
        return result
