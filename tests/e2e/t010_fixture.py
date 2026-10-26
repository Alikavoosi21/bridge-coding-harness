"""Opt-in test server with a fake container adapter; never a host-shell fallback."""
import asyncio,json,os,threading
from dataclasses import replace
from pathlib import Path
from fastapi import Request
from langchain_core.messages import AIMessage,HumanMessage
from harness.demo_model import ScriptedChatModel,call
from harness.runtime.docker import Capability,ContainerConfig,ExecResult


class FixtureRuntime:
    def __init__(self,config=None):self.config=config or ContainerConfig();self.lease=None;self.stop=threading.Event()
    def pin_image(self):self.config=replace(self.config,image='sha256:'+'a'*64);return self.config.image
    def capability(self):return Capability(True,'FIXTURE ONLY; no real Docker',image=self.config.image,image_present=True)
    def set_lease(self,lease):self.lease=lease
    def cancel_all(self):self.stop.set()
    def execute(self,command,*,snapshot,exec_id,**kwargs):
        home=Path(os.environ['HARNESS_HOME']).resolve()
        if not Path(snapshot).resolve().is_relative_to(home):raise RuntimeError('Fixture path outside temporary home')
        self.lease.check('fixture execute')
        if command=='fixture-check':
            notes=(Path(snapshot)/'notes.md').read_text(encoding='utf8')
            if notes=='fixture timeout':return ExecResult(exec_id,124,'fixture check timed out',timed_out=True,operation_id=exec_id)
            if notes=='fixed fixture':return ExecResult(exec_id,0,'fixture check passed: corrected notes',operation_id=exec_id)
            return ExecResult(exec_id,1,'fixture check failed: expected corrected notes',operation_id=exec_id)
        if command=='fixture-long':
            (Path(snapshot)/'running.txt').write_text('fixture only',encoding='utf8')
            self.stop.wait(45)
            return ExecResult(exec_id,130 if self.stop.is_set() else 0,'fixture stopped',stopped=self.stop.is_set(),operation_id=exec_id)
        target=Path(snapshot)/'effect.txt'
        target.write_text(command,encoding='utf8')
        return ExecResult(exec_id,0,'fixture effect stored',operation_id=exec_id)


class FixtureModel(ScriptedChatModel):
    def _generate(self,messages,*args,**kwargs):
        human=next((str(message.content) for message in reversed(messages) if isinstance(message,HumanMessage)),'')
        all_humans=' '.join(str(message.content) for message in messages if isinstance(message,HumanMessage))
        command='fixture-check' if 'quality-again' in all_humans else 'fixture-long' if 'long-stop' in human else 'printf fixture-approved'
        self.script=[AIMessage(content='',tool_calls=[call('execute',command=command)]),AIMessage(content='Fixture finished')]
        return super()._generate(messages,*args,**kwargs)


def create_app():
    if os.environ.get('HARNESS_T010_FIXTURE')!='1':raise RuntimeError('Test-only server requires explicit opt-in')
    import harness.core as core
    import harness.task_runtime as task_runtime
    import harness.runtime.docker as docker
    core.build_chat_model=lambda spec:FixtureModel(script=[])
    task_runtime.DockerRuntime=FixtureRuntime;docker.DockerRuntime=FixtureRuntime
    from server.app import create_app as actual
    app=actual()
    ids=json.loads(os.environ['T010_TASKS'])
    async def prepare():
        from server.storage import Store
        for name in ('approve','edit','reject','mode'):
            app.state.harness.controller.execute(ids[name])
            await app.state.harness.manager.wait(Store().task(ids[name])['thread_id'])
    from contextlib import asynccontextmanager
    original_lifespan=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(app):
        async with original_lifespan(app):
            await prepare()
            yield
    app.router.lifespan_context=lifespan
    @app.post('/fixture/start-stop')
    async def start_stop():
        return app.state.harness.controller.execute(ids['long-stop'])
    @app.post('/fixture/quality')
    async def quality():
        from types import SimpleNamespace
        from langchain_core.messages import ToolMessage
        from server.storage import Store
        from harness.gateway import ToolGateway
        from harness.verification.budget import RepairBudget
        store=Store();first=store.task(ids['quality-end']);workspace=store.workspace(first['workspace_id'])
        profile={'profile_hash':'fixture-quality','commands':[{'id':'tests','command':'fixture-check','required':True}]}
        with store.db.write() as db:db.execute('UPDATE workspaces SET profile=? WHERE id=?',(json.dumps(profile),workspace['id']))
        for name in ('quality-end','quality-again','quality-edit'):
            task_id=ids[name]
            store.decide_plan(task_id,expected_revision=store.plan(task_id)['revision'],approve=True)
            assembly=task_runtime.open_task_runtime(app.state.harness.workspace,store,task_id,read_only=False,max_seconds=60)
            backend=assembly.backend.default
            gateway=ToolGateway(store,task_id,app.state.harness.workspace.rules_file,runtime_available=True,runtime_id=assembly.runtime_id,backend=backend)
            async def execute(request):
                output=await backend.aexecute(request.tool_call['args']['command'])
                return ToolMessage(content=output.output,tool_call_id=request.tool_call['id'])
            try:
                baseline=SimpleNamespace(tool_call={'name':'execute','args':{'command':'fixture-check'},'id':'fixture-baseline'})
                assert gateway.requires_review(baseline)
                review=gateway.approvals.list(task_id)[-1]
                gateway.approvals.decide(task_id,review['id'],fingerprint=review['action_hash'],revision=review['revision'],decision='approve')
                await gateway.dispatch(baseline,execute)
                # An explicit fixture mutation exercises the real working-copy
                # hashes; no original project file or host shell is involved.
                assert not backend.edit('/notes.md','fixture','modified fixture').error
                await gateway.dispatch(SimpleNamespace(tool_call={'name':'execute','args':{'command':'fixture-check'},'id':'fixture-current'}),execute)
                store.set_task_status(task_id,'verifying')
                budget=RepairBudget(store)
                budget.claim(task_id,key='fixture-one',expected_revision=1,reason='fixture failure')
                budget.claim(task_id,key='fixture-two',expected_revision=2,reason='fixture failure')
                store.set_task_status(task_id,'awaiting_decision')
            finally:assembly.close()
        return {'prepared':True}
    @app.post('/fixture/quality-stale')
    async def stale_quality():
        from server.storage import Store
        working=task_runtime.task_directory(Store(),ids['quality-end'])/'working'
        (working/'notes.md').write_text('fixture edit after verification',encoding='utf8')
        return {'changed':True}
    @app.post('/fixture/quality-outcome')
    async def quality_outcome(mode:str):
        if mode not in {'passed','timed_out','skipped'}:raise ValueError('Unknown fixture outcome')
        from types import SimpleNamespace
        from langchain_core.messages import ToolMessage
        from server.storage import Store
        from harness.gateway import ToolGateway
        from harness.verification.results import CheckResults,CheckTarget
        from harness.verification.observe import manifest_hash
        store=Store();task_id=ids['quality-again'];store.set_task_status(task_id,'verifying')
        assembly=task_runtime.open_task_runtime(app.state.harness.workspace,store,task_id,read_only=False,max_seconds=60)
        backend=assembly.backend.default
        try:
            assert not backend.edit('/notes.md',backend.read('/notes.md').file_data['content'],'fixed fixture' if mode=='passed' else 'fixture timeout' if mode=='timed_out' else 'fixture skipped').error
            if mode=='skipped':
                target=CheckTarget('working_copy',manifest_hash(assembly.workspace.root),'fixture-quality',assembly.runtime_id)
                CheckResults(store).record(task_id,target=target,check_id='tests',outcome='skipped',command='fixture-check',output='fixture check deliberately skipped')
            else:
                gateway=ToolGateway(store,task_id,app.state.harness.workspace.rules_file,runtime_available=True,runtime_id=assembly.runtime_id,backend=backend)
                async def execute(request):
                    result=await backend.aexecute('fixture-check')
                    return ToolMessage(content=result.output,tool_call_id=request.tool_call['id'])
                await gateway.dispatch(SimpleNamespace(tool_call={'name':'execute','args':{'command':'fixture-check'},'id':'fixture-outcome-'+mode}),execute)
        finally:assembly.close()
        if mode=='passed':app.state.harness.controller._finish(task_id,phase='execute',stop_reason='completed')
        else:store.set_task_status(task_id,'awaiting_decision')
        return {'prepared':mode}
    @app.post('/fixture/changed-check-inputs')
    async def changed_check_inputs_fixture():
        from server.storage import Store
        working=task_runtime.task_directory(Store(),ids['quality-edit'])/'working'
        tests=working/'tests';tests.mkdir(exist_ok=True)
        (tests/'test_review.py').write_text('assert False',encoding='utf8')
        return {'changed':True}
    @app.post('/fixture/changed-profile')
    async def changed_profile_fixture():
        from server.storage import Store
        store=Store();task=store.task(ids['quality-edit'])
        with store.db.write() as db:db.execute('UPDATE workspaces SET profile=? WHERE id=?',(json.dumps({'profile_hash':'fixture-changed-profile','commands':[]}),task['workspace_id']))
        return {'changed':True}
    return app
