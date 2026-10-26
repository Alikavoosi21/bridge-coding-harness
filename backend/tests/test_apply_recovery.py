"""T013 foundation: captured bytes, read-only diff and original conflicts.

Apply/restore acceptance is not implied by these review tests.
"""
import httpx
import pytest

from harness.task_runtime import open_task_runtime,task_directory
from harness.worktrees.diff import changes,file_diff
from harness.workspace import Workspace
from server.app import create_app
from server.storage import Database,Store,migrate
from server.errors import ApiError


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    workspace=Workspace.at(tmp_path/'project').scaffold()
    (workspace.root/'کد.py').write_bytes(b'old\r\n')
    (workspace.root/'delete.txt').write_text('remove in copy',encoding='utf8')
    (workspace.root/'.env').write_text('fixture-secret',encoding='utf8')
    store=Store(Database());migrate(store.db)
    ws=store.upsert_workspace(str(workspace.root));task=store.create_task(workspace_id=ws['id'],prompt='fixture',read_only=True)
    assembly=open_task_runtime(workspace,store,task['id'],read_only=True,max_seconds=60)
    assembly.close()
    store.set_task_status(task['id'],'paused',reason='fixture: runtime is closed')
    return store,task,workspace,task_directory(store,task['id'])


def test_baseline_bytes_stay_immutable_and_diff_reports_three_versions(fixture):
    store,task,workspace,directory=fixture;working=directory/'working'
    assert (directory/'baseline'/'کد.py').read_bytes()==b'old\r\n'
    assert not (directory/'baseline'/'.env').exists()
    (working/'کد.py').write_bytes(b'agent\r\n')
    (working/'delete.txt').unlink()
    (working/'new.py').write_text('new',encoding='utf8')
    (working/'blob.bin').write_bytes(b'\x00\x01')
    (workspace.root/'کد.py').write_bytes(b'user edit\r\n')
    report=changes(store,task['id']);rows={row['path']:row for row in report['items']}
    assert rows['کد.py']['kind']=='modified' and rows['کد.py']['conflict']
    assert rows['delete.txt']['kind']=='deleted' and rows['new.py']['kind']=='added'
    assert rows['blob.bin']['kind']=='binary'
    assert len({rows['کد.py'][key] for key in ['baseline_hash','working_hash','current_hash']})==3
    diff=file_diff(store,task['id'],'کد.py')
    assert diff['before']=='old\r\n' and diff['after']=='agent\r\n'
    assert diff['current']=='user edit\r\n' and diff['current_supported']
    assert '-old\r\n' in diff['diff'] and '+agent\r\n' in diff['diff']
    assert (directory/'baseline'/'کد.py').read_bytes()==b'old\r\n'
    assert (workspace.root/'کد.py').read_bytes()==b'user edit\r\n'
    assert not file_diff(store,task['id'],'blob.bin')['supported']
    assert changes(store,task['id'])['items']==report['items']


def test_missing_legacy_baseline_never_uses_changed_original_as_old_bytes(fixture):
    store,task,workspace,directory=fixture
    (directory/'working'/'کد.py').write_text('agent',encoding='utf8')
    baseline=directory/'baseline';archive=directory/'baseline-fixture-archive'
    assert baseline.resolve().is_relative_to(directory.resolve()) and archive.resolve().parent==directory.resolve()
    baseline.rename(archive)
    assert file_diff(store,task['id'],'کد.py')['before']=='old\r\n'
    (workspace.root/'کد.py').write_text('new user bytes',encoding='utf8')
    result=file_diff(store,task['id'],'کد.py')
    assert not result['supported'] and result['reason']=='baseline_unavailable' and result['diff'] is None


async def test_review_api_is_read_only_and_refuses_secret_and_traversal_paths(fixture):
    store,task,workspace,directory=fixture
    (directory/'working'/'کد.py').write_text('agent',encoding='utf8')
    app=create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as api:
        base=f"/tasks/{task['id']}/changes"
        response=await api.get(base)
        assert response.status_code==200 and response.json()['baseline_available']
        response=await api.get(base+'/file',params={'path':'کد.py'})
        assert response.status_code==200 and response.json()['supported']
        for path in ['../outside.txt','.env','/absolute.py','C:/secret.txt']:
            assert (await api.get(base+'/file',params={'path':path})).status_code==422
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'
    assert store.worker_lease() is None


def test_corrupt_saved_manifest_requires_recovery_without_touching_original(fixture):
    from harness.worktrees.snapshot import manifest_path
    store,task,workspace,directory=fixture
    manifest_path(directory/'working').write_text('{broken fixture manifest',encoding='utf8')
    with pytest.raises(ApiError) as error:changes(store,task['id'])
    assert error.value.code=='recovery_required'
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'


def test_review_does_not_follow_a_working_file_symlink(fixture):
    import os
    store,task,workspace,directory=fixture
    outside=directory/'outside-review-fixture.txt';outside.write_text('must never appear in diff',encoding='utf8')
    file=directory/'working'/'کد.py';file.unlink()
    try:os.symlink(outside,file)
    except OSError as error:pytest.skip(f'Actual symlink creation unavailable on this host: {error.winerror if hasattr(error,"winerror") else error.errno}')
    row=next(item for item in changes(store,task['id'])['items'] if item['path']=='کد.py')
    assert row['kind']=='unsupported'
    result=file_diff(store,task['id'],'کد.py')
    assert not result['supported'] and result['diff'] is None and 'must never appear' not in str(result)
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'


def test_working_revision_tracks_bytes_not_lifecycle_and_file_reads_are_hash_bound(fixture):
    from harness.worktrees.diff import working_file
    store,task,_,directory=fixture
    first=changes(store,task['id'])
    assert first['working_revision']==1
    store.set_task_status(task['id'],'paused')
    assert changes(store,task['id'])['working_revision']==1
    (directory/'working'/'کد.py').write_bytes(b'edited\r\n')
    content=working_file(store,task['id'],'کد.py')
    assert content['supported'] and content['content']=='edited\r\n' and content['working_revision']==2
    assert changes(Store(store.db),task['id'])['working_revision']==2
    assert changes(store,task['id'])['items'][0]['working_hash']==content['hash']


def test_human_edit_guard_rejects_stale_copy_and_blocks_resume_with_shared_leases(fixture):
    from types import SimpleNamespace
    from harness.worktrees.guard import locked_copy
    from harness.task_controller import TaskController,TaskControllerError
    store,task,_,directory=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    before=changes(store,task['id'])
    controller=TaskController(SimpleNamespace(is_running=lambda thread:False),store,model_resolver=lambda:None)
    with locked_copy(store,task['id'],expected_revision=before['working_revision'],expected_manifest_hash=before['working_manifest_hash']) as held:
        held['lease'].check('fixture only')
        with pytest.raises(TaskControllerError) as busy:controller._idle(store.task(task['id']))
        assert busy.value.code=='workspace_busy'
        with pytest.raises(ApiError) as launch:controller.propose(task['id'])
        assert launch.value.code=='workspace_busy'
        with pytest.raises(ApiError) as second:
            with locked_copy(store,task['id'],expected_revision=1,expected_manifest_hash=before['working_manifest_hash']):pass
        assert second.value.code=='workspace_busy'
    assert store.worker_lease() is None and store.workspace_lease(task['workspace_id']) is None
    from harness.worktrees.lease import LeaseLost
    with pytest.raises(LeaseLost):held['lease'].check('cannot write after release')
    (directory/'working'/'کد.py').write_text('external working-copy edit',encoding='utf8')
    with pytest.raises(ApiError) as stale:
        with locked_copy(store,task['id'],expected_revision=1,expected_manifest_hash=before['working_manifest_hash']):pass
    assert stale.value.code=='selection_stale'
    assert store.worker_lease() is None and store.workspace_lease(task['workspace_id']) is None


def test_read_only_and_active_task_cannot_enter_human_write_guard(fixture):
    from harness.worktrees.guard import locked_copy
    store,task,_,_=fixture;before=changes(store,task['id'])
    with pytest.raises(ApiError) as readonly:
        with locked_copy(store,task['id'],expected_revision=1,expected_manifest_hash=before['working_manifest_hash']):pass
    assert readonly.value.code=='runtime_unavailable'
    with store.db.write() as db:db.execute("UPDATE tasks SET read_only=0,status='executing' WHERE id=?",(task['id'],))
    with pytest.raises(ApiError) as active:
        with locked_copy(store,task['id'],expected_revision=1,expected_manifest_hash=before['working_manifest_hash']):pass
    assert active.value.code=='workspace_busy' and store.worker_lease() is None
    store.set_task_status(task['id'],'queued',reason='fixture queue')
    with pytest.raises(ApiError) as queued:
        with locked_copy(store,task['id'],expected_revision=1,expected_manifest_hash=before['working_manifest_hash']):pass
    assert queued.value.code=='workspace_busy'


def test_file_without_check_profile_can_be_captured_but_never_claims_verified(fixture,monkeypatch):
    import json
    from harness.worktrees.selection import prepare_selection,validate_selection
    from harness.verification.results import CheckResults,CheckTarget
    store,task,workspace,directory=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    monkeypatch.setattr('harness.worktrees.selection.runtime_descriptor',lambda *_:{'runtime_id':'fixture-runtime'})
    (directory/'working'/'login.html').write_text('<html>Login</html>',encoding='utf8')
    report=changes(store,task['id']);file_id=next(row['file_id'] for row in report['items'] if row['path']=='login.html')
    selected=prepare_selection(store,task['id'],file_ids=[file_id],expected_revision=report['working_revision'],expected_manifest_hash=report['working_manifest_hash'])
    assert validate_selection(store,task['id'],selected['id'])['id']==selected['id']
    target=CheckTarget('apply_candidate',selected['candidate_manifest_hash'],selected['profile_hash'],selected['runtime_fingerprint'],selected['id'])
    assert CheckResults(store).quality(task['id'],target=target,required=[])['quality_status']=='not_verified'
    store.upsert_workspace(str(workspace.root),profile=json.dumps({'profile_hash':'new-profile','commands':[]}))
    with pytest.raises(ApiError) as stale:validate_selection(store,task['id'],selected['id'])
    assert stale.value.code=='selection_stale'


def test_subset_capture_uses_current_original_and_never_inherits_working_quality(fixture,monkeypatch):
    import json
    from harness.worktrees.selection import prepare_selection,validate_selection
    from harness.verification.results import CheckResults,CheckTarget
    store,task,workspace,directory=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    store.upsert_workspace(str(workspace.root),profile=json.dumps({'profile_hash':'profile-fixture'}))
    monkeypatch.setattr('harness.worktrees.selection.runtime_descriptor',lambda *args:{'runtime_id':'runtime-fixture'})
    (directory/'working'/'کد.py').write_bytes(b'agent dependent on changed delete.txt\r\n')
    (directory/'working'/'delete.txt').write_text('agent second file',encoding='utf8')
    report=changes(store,task['id'])
    target=CheckTarget('working_copy',report['working_manifest_hash'],'profile-fixture','runtime-fixture')
    CheckResults(store).record(task['id'],target=target,check_id='test',outcome='passed',command='test')
    chosen=next(row['file_id'] for row in report['items'] if row['path']=='کد.py')
    selection=prepare_selection(store,task['id'],file_ids=[chosen],expected_revision=report['working_revision'],expected_manifest_hash=report['working_manifest_hash'])
    candidate=directory/'selections'/selection['id']
    assert (candidate/'کد.py').read_bytes()==b'agent dependent on changed delete.txt\r\n'
    assert (candidate/'delete.txt').read_text(encoding='utf8')=='remove in copy'
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'
    assert not (candidate/'.env').exists()
    assert selection['candidate_manifest_hash']!=report['working_manifest_hash']
    candidate_target=CheckTarget('apply_candidate',selection['candidate_manifest_hash'],'profile-fixture','runtime-fixture',selection['id'])
    assert CheckResults(store).quality(task['id'],target=candidate_target,required=['test'])['quality_status']=='not_verified'
    assert validate_selection(store,task['id'],selection['id'])['id']==selection['id']
    # An unselected input changed: the old preview/ack cannot still authorize apply.
    (workspace.root/'delete.txt').write_text('user new input',encoding='utf8')
    with pytest.raises(ApiError) as stale:validate_selection(store,task['id'],selection['id'])
    assert stale.value.code=='selection_stale'
    assert (candidate/'delete.txt').read_text(encoding='utf8')=='remove in copy'
    assert store.worker_lease() is None


def test_selection_rejects_empty_duplicate_and_conflicting_files(fixture,monkeypatch):
    import json
    from harness.worktrees.selection import prepare_selection
    store,task,workspace,directory=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    store.upsert_workspace(str(workspace.root),profile=json.dumps({'profile_hash':'profile-fixture'}))
    monkeypatch.setattr('harness.worktrees.selection.runtime_descriptor',lambda *args:{'runtime_id':'runtime-fixture'})
    (directory/'working'/'کد.py').write_text('agent',encoding='utf8')
    (workspace.root/'کد.py').write_text('concurrent user',encoding='utf8')
    report=changes(store,task['id']);identifier=report['items'][0]['file_id']
    for selected,code in [([], 'invalid_request'),([identifier,identifier],'invalid_request'),([identifier],'selection_stale')]:
        with pytest.raises(ApiError) as error:
            prepare_selection(store,task['id'],file_ids=selected,expected_revision=report['working_revision'],expected_manifest_hash=report['working_manifest_hash'])
        assert error.value.code==code
    assert (workspace.root/'کد.py').read_text(encoding='utf8')=='concurrent user'


async def test_preview_receipt_replays_without_second_capture_and_rejects_later_stale(fixture,monkeypatch):
    import json
    store,task,workspace,directory=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    store.upsert_workspace(str(workspace.root),profile=json.dumps({'profile_hash':'profile-fixture'}))
    monkeypatch.setattr('harness.worktrees.selection.runtime_descriptor',lambda *args:{'runtime_id':'runtime-fixture'})
    (directory/'working'/'کد.py').write_text('agent',encoding='utf8')
    report=changes(store,task['id'])
    body={'file_ids':[report['items'][0]['file_id']],'expected_working_revision':report['working_revision'],'expected_manifest_hash':report['working_manifest_hash'],'idempotency_key':'preview-once'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='http://127.0.0.1:8765') as api:
        base=f"/tasks/{task['id']}/apply-previews"
        first=await api.post(base,json=body)
        assert first.status_code==201
        repeated=await api.post(base,json=body)
        assert repeated.json()==first.json() and repeated.headers['Idempotent-Replayed']=='true'
        identifier=first.json()['id']
        assert (await api.get(base+'/'+identifier)).status_code==200
        (directory/'working'/'delete.txt').write_text('later unselected edit',encoding='utf8')
        assert (await api.get(base+'/'+identifier)).status_code==409
    with store.db.read() as db:
        assert db.execute('SELECT COUNT(*) FROM apply_selections').fetchone()[0]==1
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'


def test_actual_windows_handles_block_other_writer_and_parent_rename(fixture):
    import os
    from harness.worktrees.file_lock import locked_regular_file
    if os.name!='nt':pytest.skip('Actual Windows sharing semantics require Windows.')
    _,_,_,directory=fixture
    folder=directory/'working'/'nested';folder.mkdir()
    file=folder/'code.py';file.write_bytes(b'first')
    with locked_regular_file(directory/'working','nested/code.py') as held:
        assert held.read()==b'first'
        with pytest.raises(OSError):file.write_bytes(b'must not write')
        with pytest.raises(OSError):folder.rename(folder.with_name('renamed'))
        held.seek(0);held.write(b'after');held.flush()
    assert file.read_bytes()==b'after'


def test_manual_save_preserves_bom_crlf_and_receipt_without_touching_original(fixture):
    import os,json
    from harness.worktrees.edit import save_working_file
    from harness.worktrees.diff import working_file
    from harness.verification.results import CheckResults,CheckTarget
    if os.name!='nt':pytest.skip('Exclusive manual edit is currently Windows-only.')
    store,task,workspace,directory=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    file=directory/'working'/'کد.py';file.write_bytes(b'\xef\xbb\xbfstart\r\n')
    opened=working_file(store,task['id'],'کد.py')
    checks=CheckResults(store)
    checks.record(task['id'],target=CheckTarget('working_copy',opened['working_manifest_hash'],'profile','runtime'),check_id='test',outcome='passed',command='test')
    arguments=dict(path='کد.py',content='human\nnext\n',expected_revision=opened['working_revision'],expected_manifest_hash=opened['working_manifest_hash'],expected_file_hash=opened['hash'],key='human-save')
    result=save_working_file(store,task['id'],**arguments)
    assert file.read_bytes()==b'\xef\xbb\xbfhuman\r\nnext\r\n'
    assert result['working_revision']==opened['working_revision']+1
    assert checks.quality(task['id'],target=CheckTarget('working_copy',result['working_manifest_hash'],'profile','runtime'),required=['test'])['quality_status']=='stale'
    assert save_working_file(store,task['id'],**arguments)==result
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'
    operation=store.action(result['operation_id'])
    assert operation['state']=='succeeded' and json.loads(operation['result_ref'])==result
    changed=[event['payload'] for event in store.events(task['id'])['items'] if event['type']=='file_changed']
    assert changed[-1]['file_id'] and changed[-1]['change_kind']=='modified' and changed[-1]['hash']==result['hash']
    journal=directory/'manual-edits'/result['operation_id']
    assert (journal/'before.bin').read_bytes()==b'\xef\xbb\xbfstart\r\n'
    assert (journal/'after.bin').read_bytes()==file.read_bytes()
    with pytest.raises(ApiError) as stale:save_working_file(store,task['id'],**{**arguments,'key':'other-save'})
    assert stale.value.code=='selection_stale'
    with pytest.raises(ApiError) as reused:save_working_file(store,task['id'],**{**arguments,'content':'different'})
    assert reused.value.code=='idempotency_conflict'


def test_manual_edit_after_write_failure_is_unknown_and_never_replayed(fixture,monkeypatch):
    import os
    from harness.worktrees.edit import save_working_file
    from harness.worktrees.diff import working_file
    from harness.task_controller import TaskController,TaskControllerError
    from types import SimpleNamespace
    if os.name!='nt':pytest.skip('Exclusive manual edit is currently Windows-only.')
    store,task,_,directory=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    opened=working_file(store,task['id'],'کد.py')
    arguments=dict(path='کد.py',content='human\n',expected_revision=opened['working_revision'],expected_manifest_hash=opened['working_manifest_hash'],expected_file_hash=opened['hash'],key='interrupted')
    original=store.set_action_state
    def interrupt(identifier,state,**kwargs):
        if state=='succeeded':raise OSError('fixture: disk/database failure after file write')
        return original(identifier,state,**kwargs)
    monkeypatch.setattr(store,'set_action_state',interrupt)
    with pytest.raises(OSError):save_working_file(store,task['id'],**arguments)
    assert store.task(task['id'])['status']=='recovery_required'
    assert store.action_by_invocation(task['id'],'manual-edit:interrupted')['state']=='unknown'
    assert (directory/'working'/'کد.py').read_bytes()==b'human\r\n'
    with pytest.raises(ApiError) as unknown:save_working_file(store,task['id'],**arguments)
    assert unknown.value.code=='recovery_required'
    controller=TaskController(SimpleNamespace(is_running=lambda thread:False),store,model_resolver=lambda:None)
    with pytest.raises(TaskControllerError) as resume:controller._idle(store.task(task['id']))
    assert resume.value.code=='recovery_required'
    assert store.worker_lease() is None


async def test_interrupted_manual_edit_accepts_only_explicit_inspected_bytes_and_never_rewrites(fixture,monkeypatch):
    import os
    from harness.worktrees.edit import save_working_file
    from harness.worktrees.diff import working_file
    if os.name!='nt':pytest.skip('Exclusive manual edit is currently Windows-only.')
    store,task,_,directory=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    opened=working_file(store,task['id'],'کد.py')
    original=store.set_action_state
    def interrupt(identifier,state,**kwargs):
        if state=='succeeded':raise OSError('fixture interruption')
        return original(identifier,state,**kwargs)
    monkeypatch.setattr(store,'set_action_state',interrupt)
    with pytest.raises(OSError):save_working_file(store,task['id'],path='کد.py',content='requested',expected_revision=opened['working_revision'],expected_manifest_hash=opened['working_manifest_hash'],expected_file_hash=opened['hash'],key='reconcile-fixture')
    operation=store.action_by_invocation(task['id'],'manual-edit:reconcile-fixture')
    file=directory/'working'/'کد.py'
    file.write_bytes(b'new user edit after interruption')
    inspected=working_file(store,task['id'],'کد.py')
    body={'expected_working_revision':inspected['working_revision'],'expected_manifest_hash':inspected['working_manifest_hash'],'expected_file_hash':inspected['hash'],'accept_current':False,'idempotency_key':'accept-once'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='http://127.0.0.1:8765') as api:
        route=f"/tasks/{task['id']}/manual-edits/{operation['operation_id']}/reconciliations"
        inspected_response=await api.get(route.removesuffix('/reconciliations'))
        assert inspected_response.status_code==200
        assert inspected_response.json()['before']=='old\r\n' and inspected_response.json()['requested']=='requested'
        assert inspected_response.json()['current']['content']=='new user edit after interruption'
        assert (await api.post(route,json=body)).status_code==422
        body['accept_current']=True
        other=store.ensure_action(task['id'],'unrelated-unknown','fixture-hash')
        store.set_action_state(other['operation_id'],'unknown')
        assert (await api.post(route,json={**body,'idempotency_key':'other-unresolved'})).status_code==409
        store.set_action_state(other['operation_id'],'failed')
        first=await api.post(route,json={**body,'expected_file_hash':'0'*64,'idempotency_key':'stale'})
        assert first.status_code==409
        first=await api.post(route,json=body)
        assert first.status_code==200 and first.json()['resolution']=='kept_current'
        assert not first.json()['matches_requested_edit']
        repeated=await api.post(route,json=body)
        assert repeated.json()==first.json() and repeated.headers['Idempotent-Replayed']=='true'
    assert store.task(task['id'])['status']=='paused'
    assert store.action(operation['operation_id'])['state']=='failed'
    assert file.read_bytes()==b'new user edit after interruption'


def test_manual_save_refuses_a_hardlink_to_original(fixture):
    import os
    from harness.worktrees.edit import save_working_file
    from harness.worktrees.diff import working_file
    if os.name!='nt':pytest.skip('Exclusive manual edit is currently Windows-only.')
    store,task,workspace,directory=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    file=directory/'working'/'کد.py';file.unlink()
    os.link(workspace.root/'کد.py',file)
    opened=working_file(store,task['id'],'کد.py')
    with pytest.raises(ApiError) as refused:
        save_working_file(store,task['id'],path='کد.py',content='must not reach original',expected_revision=opened['working_revision'],expected_manifest_hash=opened['working_manifest_hash'],expected_file_hash=opened['hash'],key='hardlink')
    assert refused.value.code=='invalid_request'
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'


async def test_working_edit_route_saves_only_copy_and_replays_receipt(fixture):
    import os
    from harness.worktrees.diff import working_file
    if os.name!='nt':pytest.skip('Exclusive manual edit is currently Windows-only.')
    store,task,workspace,_=fixture
    opened=working_file(store,task['id'],'کد.py')
    body={'path':'کد.py','content':'via API\n','expected_working_revision':opened['working_revision'],'expected_manifest_hash':opened['working_manifest_hash'],'expected_file_hash':opened['hash'],'idempotency_key':'api-save'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='http://127.0.0.1:8765') as api:
        route=f"/tasks/{task['id']}/working-file"
        assert (await api.put(route,json=body)).status_code==409 # no Docker/read-only cannot gain writes
        with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
        first=await api.put(route,json=body)
        assert first.status_code==200
        assert (await api.put(route,json=body)).json()==first.json()
        current=await api.get(route,params={'path':'کد.py'})
        assert current.json()['content']=='via API\r\n'
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'


def test_crash_after_prepare_claim_before_write_requires_human_reconcile(fixture,monkeypatch):
    import os
    from harness.worktrees.edit import save_working_file,accept_current_after_interruption
    from harness.worktrees.diff import working_file
    if os.name!='nt':pytest.skip('Exclusive manual edit is currently Windows-only.')
    store,task,workspace,directory=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    opened=working_file(store,task['id'],'کد.py')
    original_write=store.db.write
    from contextlib import contextmanager
    @contextmanager
    def crash_after_commit():
        with original_write() as db:yield db
        with store.db.read() as db:
            claim=db.execute("SELECT 1 FROM actions WHERE task_id=? AND state='dispatching'",(task['id'],)).fetchone()
        if claim:raise SystemExit('fixture crash after durable claim, before file write')
    with monkeypatch.context() as crashing:
        crashing.setattr(store.db,'write',crash_after_commit)
        with pytest.raises(SystemExit):
            save_working_file(store,task['id'],path='کد.py',content='not written',expected_revision=opened['working_revision'],expected_manifest_hash=opened['working_manifest_hash'],expected_file_hash=opened['hash'],key='crash-before-write')
    # A fresh Store sees the durable claim even though the file never changed.
    reopened=Store(store.db);action=reopened.action_by_invocation(task['id'],'manual-edit:crash-before-write')
    assert action['state']=='dispatching'
    assert (directory/'working'/'کد.py').read_bytes()==b'old\r\n'
    with pytest.raises(ApiError) as replay:
        save_working_file(reopened,task['id'],path='کد.py',content='not written',expected_revision=opened['working_revision'],expected_manifest_hash=opened['working_manifest_hash'],expected_file_hash=opened['hash'],key='crash-before-write')
    assert replay.value.code=='recovery_required'
    result=accept_current_after_interruption(reopened,task['id'],action['operation_id'],expected_revision=opened['working_revision'],expected_manifest_hash=opened['working_manifest_hash'],expected_file_hash=opened['hash'])
    assert not result['matches_requested_edit'] and result['resolution']=='kept_current'
    assert reopened.task(task['id'])['status']=='paused'
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'


@pytest.mark.parametrize('outcome',['passed','failed','mutated','unknown','stopped','timed_out','install','dependencies'])
def test_candidate_checks_run_only_selected_capture_with_exact_consent_and_no_replay(fixture,monkeypatch,outcome):
    import json,hashlib
    from dataclasses import asdict
    from pathlib import Path
    from harness.runtime.docker import ContainerConfig,ExecResult
    from harness.worktrees.selection import prepare_selection
    from harness.worktrees.candidate_checks import run_candidate_checks
    store,task,workspace,directory=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    image='sha256:'+'a'*64
    config=ContainerConfig(image=image)
    fingerprint=hashlib.sha256(json.dumps(asdict(config),sort_keys=True).encode()).hexdigest()
    descriptor={'image':image,'runtime_id':fingerprint}
    monkeypatch.setattr('harness.worktrees.selection.runtime_descriptor',lambda *args:descriptor)
    monkeypatch.setattr('harness.worktrees.candidate_checks.runtime_descriptor',lambda *args:descriptor)
    command_text='npm install' if outcome=='install' else 'python check.py'
    store.upsert_workspace(str(workspace.root),profile=json.dumps({'profile_hash':'profile','commands':[{'id':'tests','command':command_text,'required':True}],'install':{'command':'npm ci'} if outcome=='dependencies' else None}))
    (directory/'working'/'کد.py').write_text('selected',encoding='utf8')
    (directory/'working'/'delete.txt').write_text('unselected agent change',encoding='utf8')
    report=changes(store,task['id']);chosen=next(row['file_id'] for row in report['items'] if row['path']=='کد.py')
    selection=prepare_selection(store,task['id'],file_ids=[chosen],expected_revision=report['working_revision'],expected_manifest_hash=report['working_manifest_hash'])
    hits=[]
    class Runtime:
        def __init__(self,config):self.config=config
        def set_lease(self,lease):self.lease=lease
        def pin_image(self):return image
        def cancel(self,exec_id):self.cancelled=exec_id
        def execute(self,command,**kwargs):
            self.lease.check('fixture candidate')
            root=Path(kwargs['snapshot']);hits.append(command)
            assert root!=(directory/'working') and root!=workspace.root
            assert (root/'کد.py').read_text(encoding='utf8')=='selected'
            assert (root/'delete.txt').read_text(encoding='utf8')=='remove in copy'
            if outcome=='dependencies':
                if command=='npm ci':
                    assert kwargs['network_until']>0
                    (root/'node_modules').mkdir()
                    (root/'node_modules'/'fixture-package').write_text('installed only in disposable copy')
                    return ExecResult(kwargs['exec_id'],0,'fixture dependency install')
                assert 'network_until' not in kwargs and (root/'node_modules'/'fixture-package').exists()
            if outcome=='mutated':(root/'کد.py').write_text('test mutated input',encoding='utf8')
            if outcome=='stopped':
                from harness.worktrees.candidate_checks import stop_candidate
                assert stop_candidate(store,task['id']) and self.cancelled==kwargs['exec_id']
                assert store.task(task['id'])['status']=='stopping'
            return ExecResult(kwargs['exec_id'],1 if outcome=='failed' else 0,'fixture output',unknown=outcome=='unknown',stopped=outcome=='stopped',timed_out=outcome=='timed_out')
    args=dict(key='once',approved_commands=[command_text],runtime_factory=Runtime)
    with pytest.raises(ApiError) as consent:run_candidate_checks(store,task['id'],selection['id'],**{**args,'approved_commands':['other command']})
    assert consent.value.code=='action_not_approved' and not hits
    if outcome=='dependencies':
        from harness.network_access import allow
        with pytest.raises(ApiError):run_candidate_checks(store,task['id'],selection['id'],**args,approved_install='npm ci')
        permission=allow(store,task['id'],expected_revision=store.task(task['id'])['revision'],duration_seconds=300,confirm=True)
        args.update(approved_install='npm ci',network_grant=permission['id'])
    if outcome=='install':
        with pytest.raises(ApiError) as installer:run_candidate_checks(store,task['id'],selection['id'],**args)
        assert installer.value.code=='action_not_approved' and not hits
        assert store.budget(task['id'])['tool_calls']==0
        return
    if outcome in {'passed','failed','stopped','timed_out','dependencies'}:
        result=run_candidate_checks(store,task['id'],selection['id'],**args)
        assert result['quality_status']==('verified_snapshot' if outcome in {'passed','dependencies'} else 'failed' if outcome=='failed' else 'not_verified')
        assert run_candidate_checks(store,task['id'],selection['id'],**args)==result
    else:
        with pytest.raises((ApiError,RuntimeError)):run_candidate_checks(store,task['id'],selection['id'],**args)
        with pytest.raises(ApiError) as replay:run_candidate_checks(store,task['id'],selection['id'],**args)
        assert replay.value.code=='recovery_required'
    assert hits==(['npm ci','python check.py'] if outcome=='dependencies' else ['python check.py'])
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'
    assert (directory/'selections'/selection['id']/'کد.py').read_text(encoding='utf8')=='selected'
    assert bool(list(directory.glob('candidate-check-*')))==(outcome=='unknown')


@pytest.fixture
def apply_fixture(fixture,monkeypatch):
    import os,json
    from harness.worktrees.selection import prepare_selection
    if os.name!='nt':pytest.skip('Exclusive original file writes currently Windows-only.')
    store,task,workspace,directory=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    store.upsert_workspace(str(workspace.root),profile=json.dumps({'profile_hash':'profile-fixture'}))
    monkeypatch.setattr('harness.worktrees.selection.runtime_descriptor',lambda *args:{'runtime_id':'runtime-fixture'})
    monkeypatch.setattr('harness.worktrees.reconcile.runtime_descriptor',lambda *args:{'runtime_id':'runtime-fixture'})
    working=directory/'working'
    (working/'کد.py').write_bytes(b'agent\r\n')
    (working/'delete.txt').unlink()
    (working/'nested').mkdir();(working/'nested'/'new.py').write_bytes(b'new file\r\n')
    report=changes(store,task['id'])
    selection=prepare_selection(store,task['id'],file_ids=[row['file_id'] for row in report['items']],expected_revision=report['working_revision'],expected_manifest_hash=report['working_manifest_hash'])
    return store,task,workspace,directory,selection


def test_interrupted_restore_keeps_later_user_bytes_and_records_file_outcomes(apply_fixture):
    import json
    from harness.worktrees.apply import apply_selection
    from harness.worktrees.restore import inspect_interrupted_restore,accept_interrupted_restore
    store,task,workspace,directory,selection=apply_fixture
    operation=apply_selection(store,task['id'],selection['id'],key='restore-recovery-apply',confirm=True,quality_ack=True)
    action=store.ensure_action(task['id'],'restore:interrupted','fixture-hash')
    store.set_action_state(action['operation_id'],'unknown',result_ref=json.dumps({'apply_operation_id':operation['id'],'requested_paths':['کد.py'],'files':[]}))
    store.set_task_status(task['id'],'recovery_required')
    (workspace.root/'کد.py').write_bytes(b'later user bytes')
    preview=inspect_interrupted_restore(store,task['id'],action['operation_id'])
    assert preview['files'][0]['state']=='kept_current'
    result=accept_interrupted_restore(store,task['id'],action['operation_id'],expected_original_hash=preview['original_manifest_hash'],expected_working_revision=preview['working_revision'],expected_working_hash=preview['working_manifest_hash'],confirm=True)
    assert result['state']=='reconciled' and result['files'][0]['state']=='kept_current'
    assert (workspace.root/'کد.py').read_bytes()==b'later user bytes'
    assert store.action(action['operation_id'])['state']=='failed'


def test_apply_requires_explicit_quality_ack_and_changes_only_selected_files_once(apply_fixture):
    from harness.worktrees.apply import apply_selection
    store,task,workspace,directory,selection=apply_fixture
    for confirmed,ack in [(False,False),(True,False)]:
        with pytest.raises(ApiError) as required:apply_selection(store,task['id'],selection['id'],key='apply-once',confirm=confirmed,quality_ack=ack)
        assert required.value.code=='action_not_approved'
    result=apply_selection(store,task['id'],selection['id'],key='apply-once',confirm=True,quality_ack=True)
    assert result['state']=='applied' and all(row['state']=='applied' for row in result['files'])
    assert (workspace.root/'کد.py').read_bytes()==b'agent\r\n'
    assert not (workspace.root/'delete.txt').exists()
    assert (workspace.root/'nested'/'new.py').read_bytes()==b'new file\r\n'
    assert (directory/'baseline'/'کد.py').read_bytes()==b'old\r\n'
    # A retry is a historical receipt, not an overwrite of a subsequent user edit.
    (workspace.root/'کد.py').write_bytes(b'later user edit')
    assert apply_selection(store,task['id'],selection['id'],key='apply-once',confirm=True,quality_ack=True)==result
    assert (workspace.root/'کد.py').read_bytes()==b'later user edit'


def test_apply_refuses_source_changes_before_any_write(apply_fixture):
    from harness.worktrees.apply import apply_selection
    store,task,workspace,_,selection=apply_fixture
    (workspace.root/'کد.py').write_bytes(b'user concurrent')
    with pytest.raises(ApiError) as stale:apply_selection(store,task['id'],selection['id'],key='stale',confirm=True,quality_ack=True)
    assert stale.value.code=='selection_stale'
    assert (workspace.root/'delete.txt').exists() and not (workspace.root/'nested').exists()


def test_apply_late_conflict_is_partial_and_does_not_overwrite_user_edit(apply_fixture,monkeypatch):
    from contextlib import contextmanager
    from harness.worktrees.apply import apply_selection
    from harness.worktrees.file_lock import locked_regular_file
    store,task,workspace,_,selection=apply_fixture
    @contextmanager
    def racing(root,path,**kwargs):
        if path=='کد.py':(workspace.root/path).write_bytes(b'late user edit')
        with locked_regular_file(root,path,**kwargs) as stream:yield stream
    monkeypatch.setattr('harness.worktrees.apply.locked_regular_file',racing)
    result=apply_selection(store,task['id'],selection['id'],key='late-race',confirm=True,quality_ack=True)
    assert result['state']=='partial'
    assert next(row for row in result['files'] if row['path']=='کد.py')['state']=='conflict'
    assert (workspace.root/'کد.py').read_bytes()==b'late user edit'
    assert apply_selection(store,task['id'],selection['id'],key='late-race',confirm=True,quality_ack=True)==result


def test_apply_interrupted_write_is_unknown_and_not_replayed(apply_fixture,monkeypatch):
    from contextlib import contextmanager
    from harness.worktrees.apply import apply_selection
    from harness.worktrees.file_lock import locked_regular_file
    store,task,workspace,_,selection=apply_fixture
    class Interrupted:
        def __init__(self,stream):self.stream=stream
        def __getattr__(self,name):return getattr(self.stream,name)
        def write(self,data):
            self.stream.write(data[:2]);self.stream.flush()
            raise OSError('fixture: interrupted partial write')
    @contextmanager
    def interrupt(root,path,**kwargs):
        with locked_regular_file(root,path,**kwargs) as stream:
            yield Interrupted(stream) if path=='کد.py' else stream
    monkeypatch.setattr('harness.worktrees.apply.locked_regular_file',interrupt)
    result=apply_selection(store,task['id'],selection['id'],key='interrupted',confirm=True,quality_ack=True)
    assert result['state']=='unknown'
    assert store.task(task['id'])['status']=='recovery_required'
    assert apply_selection(store,task['id'],selection['id'],key='interrupted',confirm=True,quality_ack=True)==result
    # The actual partial bytes remain for explicit reconcile; no guessed rollback.
    assert (workspace.root/'کد.py').read_bytes().startswith(b'ag')


def test_apply_crash_after_durable_prepare_never_restarts_pending_files(apply_fixture,monkeypatch):
    from contextlib import contextmanager
    from harness.worktrees.apply import apply_selection
    from harness.worktrees.guard import locked_copy
    store,task,workspace,_,selection=apply_fixture
    original=store.db.write;fired=False
    @contextmanager
    def crash():
        nonlocal fired
        with original() as db:yield db
        with store.db.read() as db:prepared=db.execute("SELECT 1 FROM apply_operations WHERE state='prepared'").fetchone()
        if prepared and not fired:
            fired=True;raise SystemExit('fixture abrupt exit after durable prepare')
    with monkeypatch.context() as interrupted:
        interrupted.setattr(store.db,'write',crash)
        with pytest.raises(SystemExit):apply_selection(store,task['id'],selection['id'],key='prepared-crash',confirm=True,quality_ack=True)
    reopened=Store(store.db)
    result=apply_selection(reopened,task['id'],selection['id'],key='prepared-crash',confirm=True,quality_ack=True)
    assert result['state']=='prepared' and all(row['state']=='pending' for row in result['files'])
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'
    assert (workspace.root/'delete.txt').exists() and not (workspace.root/'nested').exists()
    report=changes(reopened,task['id'])
    with pytest.raises(ApiError) as blocked:
        with locked_copy(reopened,task['id'],expected_revision=report['working_revision'],expected_manifest_hash=report['working_manifest_hash']):pass
    assert blocked.value.code=='recovery_required'


def test_restore_created_modified_deleted_files_preserves_working_and_replays_receipt(apply_fixture):
    from harness.worktrees.apply import apply_selection
    from harness.worktrees.restore import restore_preview,restore_operation
    store,task,workspace,directory,selection=apply_fixture
    applied=apply_selection(store,task['id'],selection['id'],key='apply',confirm=True,quality_ack=True)
    preview=restore_preview(store,task['id'],applied['id']);report=changes(store,task['id'])
    assert all(row['restorable'] for row in preview['files'])
    args=dict(key='restore-once',paths=[row['path'] for row in preview['files']],expected_original_hash=preview['original_manifest_hash'],expected_working_revision=report['working_revision'],expected_working_hash=report['working_manifest_hash'],confirm=True)
    restored=restore_operation(store,task['id'],applied['id'],**args)
    assert restored['state']=='restored'
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'
    assert (workspace.root/'delete.txt').read_text(encoding='utf8')=='remove in copy'
    assert not (workspace.root/'nested'/'new.py').exists()
    assert (directory/'working'/'کد.py').read_bytes()==b'agent\r\n'
    (workspace.root/'کد.py').write_bytes(b'new user data after restore')
    assert restore_operation(store,task['id'],applied['id'],**args)==restored
    assert (workspace.root/'کد.py').read_bytes()==b'new user data after restore'


def test_restore_preview_detects_user_change_and_refuses_overwrite(apply_fixture):
    from harness.worktrees.apply import apply_selection
    from harness.worktrees.restore import restore_preview,restore_operation
    store,task,workspace,_,selection=apply_fixture
    applied=apply_selection(store,task['id'],selection['id'],key='apply',confirm=True,quality_ack=True)
    (workspace.root/'کد.py').write_bytes(b'user changed it')
    preview=restore_preview(store,task['id'],applied['id']);report=changes(store,task['id'])
    assert not next(row for row in preview['files'] if row['path']=='کد.py')['restorable']
    with pytest.raises(ApiError) as conflict:
        restore_operation(store,task['id'],applied['id'],key='unsafe',paths=['کد.py'],expected_original_hash=preview['original_manifest_hash'],expected_working_revision=report['working_revision'],expected_working_hash=report['working_manifest_hash'],confirm=True)
    assert conflict.value.code=='selection_stale'
    assert (workspace.root/'کد.py').read_bytes()==b'user changed it'


def test_restore_interruption_preserves_unknown_and_refuses_replay(apply_fixture,monkeypatch):
    from contextlib import contextmanager
    from harness.worktrees.apply import apply_selection
    from harness.worktrees.restore import restore_preview,restore_operation
    from harness.worktrees.file_lock import locked_regular_file
    store,task,workspace,_,selection=apply_fixture
    applied=apply_selection(store,task['id'],selection['id'],key='apply',confirm=True,quality_ack=True)
    preview=restore_preview(store,task['id'],applied['id']);report=changes(store,task['id'])
    class Interrupted:
        def __init__(self,file):self.file=file
        def __getattr__(self,name):return getattr(self.file,name)
        def write(self,data):
            self.file.write(data[:1]);self.file.flush();raise OSError('fixture restore write interrupted')
    @contextmanager
    def fail(root,path,**kwargs):
        with locked_regular_file(root,path,**kwargs) as file:yield Interrupted(file)
    monkeypatch.setattr('harness.worktrees.restore.locked_regular_file',fail)
    args=dict(key='interrupted',paths=['کد.py'],expected_original_hash=preview['original_manifest_hash'],expected_working_revision=report['working_revision'],expected_working_hash=report['working_manifest_hash'],confirm=True)
    result=restore_operation(store,task['id'],applied['id'],**args)
    assert result['state']=='unknown' and store.task(task['id'])['status']=='recovery_required'
    import json
    pending=store.action_by_invocation(task['id'],'restore:interrupted')
    assert json.loads(pending['result_ref'])['requested_paths']==['کد.py']
    before=(workspace.root/'کد.py').read_bytes()
    with pytest.raises(ApiError) as replay:restore_operation(store,task['id'],applied['id'],**args)
    assert replay.value.code=='recovery_required'
    assert (workspace.root/'کد.py').read_bytes()==before


async def test_apply_restore_http_flow_is_explicit_and_idempotent(apply_fixture):
    store,task,workspace,_,selection=apply_fixture
    base=f"/tasks/{task['id']}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='http://127.0.0.1:8765') as api:
        route=base+'/apply-previews/'+selection['id']+'/apply'
        body={'idempotency_key':'http-apply','confirm':False,'quality_ack':True}
        assert (await api.post(route,json=body)).status_code==409
        body['confirm']=True
        first=await api.post(route,json=body)
        assert first.status_code==200 and first.json()['state']=='applied'
        assert (await api.post(route,json=body)).json()==first.json()
        operation=base+'/apply-operations/'+first.json()['id']
        inspected=(await api.get(operation)).json()
        assert all(row['comparison']=='after' for row in inspected['files'])
        preview=(await api.get(operation+'/restore-preview')).json()
        working=changes(store,task['id'])
        restore={'idempotency_key':'http-restore','confirm':True,'paths':[row['path'] for row in preview['files']],'expected_original_hash':preview['original_manifest_hash'],'expected_working_revision':working['working_revision'],'expected_working_hash':working['working_manifest_hash']}
        restored=await api.post(operation+'/restores',json=restore)
        assert restored.status_code==200 and restored.json()['state']=='restored'
        assert (await api.post(operation+'/restores',json=restore)).json()==restored.json()
    assert (workspace.root/'کد.py').read_bytes()==b'old\r\n'


async def test_apply_reconcile_keeps_inspected_bytes_without_writes_or_pending_replay(apply_fixture):
    from harness.worktrees.apply import apply_selection
    store,task,workspace,_,selection=apply_fixture
    applied=apply_selection(store,task['id'],selection['id'],key='before-reconcile',confirm=True,quality_ack=True)
    # Simulate the persisted unresolved journal after an interrupted result commit.
    with store.db.write() as db:
        db.execute("UPDATE apply_operations SET state='unknown' WHERE id=?",(applied['id'],))
        db.execute("UPDATE apply_files SET state='writing' WHERE operation_id=?",(applied['id'],))
    store.set_task_status(task['id'],'recovery_required',reason='fixture interrupted apply journal')
    (workspace.root/'کد.py').write_bytes(b'user inspected current data')
    base=f"/tasks/{task['id']}/apply-operations/{applied['id']}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='http://127.0.0.1:8765') as api:
        inspected=(await api.get(base)).json()
        assert next(row for row in inspected['files'] if row['path']=='کد.py')['comparison']=='other'
        body={'idempotency_key':'keep-current','accept_current':False,'expected_original_hash':inspected['original_manifest_hash'],'expected_working_revision':inspected['working_revision'],'expected_working_hash':inspected['working_manifest_hash']}
        assert (await api.post(base+'/reconciliations',json=body)).status_code==409
        body['accept_current']=True
        assert (await api.post(base+'/reconciliations',json={**body,'expected_original_hash':'0'*64,'idempotency_key':'stale-current'})).status_code==409
        first=await api.post(base+'/reconciliations',json=body)
        assert first.status_code==200 and first.json()['state']=='reconciled'
        assert next(row for row in first.json()['files'] if row['path']=='کد.py')['state']=='kept_current'
        assert (await api.post(base+'/reconciliations',json=body)).json()==first.json()
    assert store.task(task['id'])['status']=='paused'
    assert (workspace.root/'کد.py').read_bytes()==b'user inspected current data'
    assert store.worker_lease() is None


def test_result_separates_candidate_checks_from_changed_current_original(apply_fixture):
    import json
    from harness.worktrees.apply import apply_selection
    from harness.worktrees.reconcile import inspect_apply
    from harness.verification.results import CheckResults,CheckTarget
    store,task,workspace,_,selection=apply_fixture
    store.upsert_workspace(str(workspace.root),profile=json.dumps({'profile_hash':'profile-fixture','commands':[{'id':'tests','command':'test','required':True}]}))
    target=CheckTarget('apply_candidate',selection['candidate_manifest_hash'],selection['profile_hash'],selection['runtime_fingerprint'],selection['id'])
    CheckResults(store).record(task['id'],target=target,check_id='tests',outcome='passed',command='test')
    operation=apply_selection(store,task['id'],selection['id'],key='verified-apply',confirm=True)
    result=inspect_apply(store,task['id'],operation['id'])
    assert result['candidate_quality']['quality_status']=='verified_snapshot'
    assert result['original_matches_candidate'] and result['original_quality_status']=='verified_snapshot'
    (workspace.root/'کد.py').write_bytes(b'new original bytes after verified apply')
    result=inspect_apply(store,task['id'],operation['id'])
    assert result['state']=='applied' # historical effect, not a new quality claim
    assert result['candidate_quality']['quality_status']=='verified_snapshot'
    assert not result['original_matches_candidate'] and result['original_quality_status']=='not_verified'


def test_conflict_review_never_substitutes_baseline_for_binary_current_original(fixture):
    store,task,workspace,directory=fixture
    (directory/'working'/'کد.py').write_bytes(b'agent new\r\n')
    (workspace.root/'کد.py').write_bytes(b'\x00binary user original')
    review=file_diff(store,task['id'],'کد.py')
    assert review['conflict'] and review['supported']
    assert review['before']=='old\r\n' and review['after']=='agent new\r\n'
    assert review['current'] is None and not review['current_supported']
    assert (workspace.root/'کد.py').read_bytes()==b'\x00binary user original'
