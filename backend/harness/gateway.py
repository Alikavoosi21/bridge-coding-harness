"""The product's tool boundary, shared by framework HITL and tool dispatch."""
from __future__ import annotations

import json
import asyncio
from contextlib import nullcontext
from typing import Any

from langchain_core.messages import ToolMessage

from .permissions import build_policy, load_rules
from .policy import ActionContext, action_access


class ToolGateway:
    def __init__(self, store, task_id: str, rules_file, *, runtime_available: bool, runtime_id: str, cwd='/workspace', shell='/bin/sh', read_only=False, backend=None, script_root=None,skills_root=None):
        from server.storage.approvals import ApprovalStore
        self.store, self.task_id, self.rules_file = store, task_id, rules_file
        self.approvals = ApprovalStore(store)
        self.runtime_available, self.runtime_id = runtime_available, runtime_id
        self.cwd, self.shell = cwd, shell
        self.read_only = read_only
        self.permission_blocked = False
        self.backend = backend
        self.script_root=script_root if script_root is not None else getattr(backend,'cwd',None)
        self.skills_root=skills_root if skills_root is not None else getattr(backend,'skills_root',None)
        self._dispatch_lock=asyncio.Lock()

    def evaluate(self, call: dict[str, Any]):
        task = self.store.task(self.task_id)
        plan = task.get('plan')
        from .command_context import command_details,saved_profile
        profile=saved_profile(self.store,task)
        install,verifier,script=command_details(call,profile,self.script_root,skills_root=self.skills_root)
        if call['name']=='execute' and self.skills_root is not None:
            from .skills_registry import SkillRegistry
            from pathlib import Path
            pins=SkillRegistry(self.store).task_pins(self.task_id)
            expected={pin['name'] for pin in pins}
            untracked=any(path.name not in expected for path in Path(self.skills_root).iterdir())
            if untracked or any(not pin['valid'] for pin in pins):
                from server.errors import ApiError
                raise ApiError('recovery_required','A task skill pin changed; re-pin explicitly before execution.',status_code=409)
        from .network_access import current as network_permission
        network=network_permission(self.store,self.task_id) if call['name']=='execute' else None
        environment=('network:'+network['fingerprint'] if network else 'offline')+(':'+profile['profile_hash'] if profile.get('profile_hash') else '')
        if getattr(getattr(self.backend,'_runtime',None),'local',False):
            environment='local:'+str(profile.get('profile_hash') or '')
        context = ActionContext(call['name'], call.get('args') or {}, self.cwd, self.shell, self.runtime_id, environment, plan['revision'] if plan else 0,script=script)
        rules = build_policy(load_rules(self.rules_file), 'ask')
        from .permissions import WRITE_TOOLS,target_path
        from .verification.inputs import is_check_input,changed_check_inputs,covered_by_plan
        check_change=call['name'] in WRITE_TOOLS and is_check_input(target_path(call['name'],call.get('args') or {}),profile)
        access = action_access(rules, context, mode=task['mode'], read_only=task['read_only'] or self.read_only,
            plan_approved=bool(plan and plan['approved_revision']==plan['revision']),
            runtime_available=self.runtime_available, network=call['name']=='browse_page' or network is not None,
            installation=install,first_verifier=verifier and not self.approvals.has_consent(self.task_id,context.fingerprint()),check_change=check_change,
            skill_script=call['name']=='execute' and '/skills' in str((call.get('args') or {}).get('command','')),
            grant_matches=self.approvals.matching_grant(self.task_id,context.fingerprint()))
        if check_change and not covered_by_plan([target_path(call['name'],call.get('args') or {}).lstrip('/')],plan):access='deny'
        if verifier and self.script_root and not covered_by_plan(changed_check_inputs(self.script_root,profile),plan):access='deny'
        if (call['name'] in WRITE_TOOLS or call['name']=='execute') and plan and plan.get('profile_hash')!=profile.get('profile_hash'):access='deny'
        if task['status'] in {'closed','failed','cancelled','recovery_required','stopping'} or call['name']=='task':
            access='deny'
        from .permissions import READ_TOOLS
        if (task['read_only'] or self.read_only) and call['name'] not in READ_TOOLS | {'calculate','write_todos'}:
            access='deny'
        if access=='ask' and not (plan and plan['approved_revision']==plan['revision']):
            access='deny'
        return context, access

    def _effective(self, call):
        operation=self.store.action_by_invocation(self.task_id,'tool:'+str(call.get('id','')))
        if operation:
            latest=next((row for row in reversed(self.approvals.list(self.task_id)) if row['action_id']==operation['operation_id']),None)
            if latest and latest['revision']>1 and latest['request']:
                return {**call,'args':latest['request']['args']},latest
        return call,None

    def _identity(self, call, context):
        from server.errors import ApiError
        if not call.get('id'):
            raise ApiError('invalid_request','A stable tool call ID is required.',status_code=422)
        task = self.store.task(self.task_id)
        run_id = task['runs'][-1]['id'] if task['runs'] else None
        return self.store.ensure_action(self.task_id, 'tool:'+call['id'], context.fingerprint(), origin_run_id=run_id)

    def review_details(self, context):
        """Presentation from trusted policy adapters, never model claims of safety."""
        from .command_context import command_details,saved_profile
        from .permissions import WRITE_TOOLS,READ_TOOLS,target_path
        from .verification.inputs import is_check_input,changed_check_inputs
        task=self.store.task(self.task_id)
        install,verifier,_=command_details({'name':context.tool,'args':context.args},saved_profile(self.store,task),self.script_root,skills_root=self.skills_root)
        if context.tool=='browse_page' or context.environment_profile.startswith('network:'):reason='network'
        elif context.tool in WRITE_TOOLS and is_check_input(target_path(context.tool,context.args),saved_profile(self.store,task)):reason='check_change'
        elif install:reason='installation'
        elif context.tool=='execute' and '/skills' in str(context.args.get('command','')):reason='skill_script'
        elif verifier and self.script_root and changed_check_inputs(self.script_root,saved_profile(self.store,task)) and not self.approvals.has_consent(self.task_id,context.fingerprint()):reason='check_inputs_changed'
        elif verifier and not self.approvals.has_consent(self.task_id,context.fingerprint()):reason='first_verifier'
        else:reason='task_consent'
        effect='command' if context.tool=='execute' else 'file_write' if context.tool in WRITE_TOOLS else 'read' if context.tool in READ_TOOLS else 'connector'
        return {'reason':reason,'effect':effect,'path':target_path(context.tool,context.args) if effect in {'file_write','read'} else None,'sandbox_network':context.environment_profile.startswith('network:')}

    def requires_review(self, request) -> bool:
        """Predicate for the installed framework's HumanInTheLoopMiddleware."""
        call,edit=self._effective(request.tool_call)
        context, access = self.evaluate(call)
        if edit and edit['state']=='pending' and access!='deny':access='ask'
        if access != 'ask':
            return False
        operation = self._identity(call, context)
        if operation['state'] in {'unknown','failed','denied','succeeded','dispatching','running'}:
            return False  # dispatch below denies or returns the stored result
        review = self.approvals.request(self.task_id,'tool:'+call['id'],context,origin_run_id=operation['origin_run_id'],review_details=self.review_details(context))
        return review['state']=='pending'

    def interrupt_on(self, names):
        # Edits need a new review of a new invocation; do not let the framework
        # silently execute edited args using the original approval receipt.
        return {name:{'allowed_decisions':['approve','reject'],'when':self.requires_review} for name in names}

    @staticmethod
    def denied(call, reason):
        return ToolMessage(content=reason,tool_call_id=call.get('id',''),name=call['name'],status='error')

    async def dispatch(self, request, handler):
        # One task's mutations/commands cannot change script inputs while a
        # reviewed command is executing. The workspace lease excludes other writers.
        async with self._dispatch_lock:
            return await self._dispatch(request,handler)

    async def _dispatch(self, request, handler):
        """Revalidate then claim exactly one effect before invoking the adapter."""
        expected_task_revision=self.store.task(self.task_id)['revision']
        call,edit=self._effective(request.tool_call)
        context, access=self.evaluate(call)
        if edit and access!='deny':access='ask'
        if access=='deny':
            self.permission_blocked=True
            return self.denied(call,'Permission denied by the current task, plan, runtime or workspace rules. Stop this action, explain the blocker briefly, and wait for the user. Do not retry or rewrite the plan to work around it.')
        from .permissions import WRITE_TOOLS
        from .verification.observe import missing_baseline
        if call['name'] in WRITE_TOOLS or call['name']=='execute':
            from .command_context import command_details,saved_profile
            profile=saved_profile(self.store,self.store.task(self.task_id))
            install,verifier,_=command_details(call,profile,self.script_root,skills_root=self.skills_root)
            if not install and not verifier:
                missing=missing_baseline(self.store,self.task_id,self.runtime_id)
                if missing:
                    return self.denied(call,'This action was not executed. Run the configured baseline checks before changing files: '+json.dumps(missing,ensure_ascii=False)+'. Call execute with one of these exact command strings, without cd, prefixes or wrappers; its cwd is /workspace. This is a baseline prerequisite, not a rejected or pending approval. The exact check will request human consent when needed. A failing baseline is evidence, not a reason to skip it.')
        # Pure reads do not need an effect journal. Unknown/custom tools require review.
        from .permissions import READ_TOOLS
        if access=='allow' and call['name'] in READ_TOOLS | {'calculate','write_todos'}:
            return await handler(request)
        operation=self._identity(call,context)
        if operation['state']=='succeeded' and operation.get('result_ref'):
            return ToolMessage.model_validate(json.loads(operation['result_ref']))
        if operation['state'] in {'unknown','failed','denied','dispatching','running'}:
            if operation['state']=='denied':
                review=next((row for row in reversed(self.approvals.list(self.task_id)) if row['action_id']==operation['operation_id']),None)
                if review and review['decision']=='reject':
                    return self.denied(call,'The user rejected this action. '+str((review['request'] or {}).get('rejection_reason') or 'Do not retry unless the user asks.'))
            return self.denied(call,'This operation has already run or has an unknown result; automatic replay is refused.')
        if access=='ask':
            reviews=self.approvals.list(self.task_id)
            review=next((row for row in reversed(reviews) if row['action_id']==operation['operation_id']),None)
            if not review or review['action_hash']!=context.fingerprint() or review['decision']!='approve' or review['state']!='decided':
                return self.denied(call,'A durable human approval for this exact operation is required.')
        from .verification.observe import prepare_check,finish_check
        prepared_check=prepare_check(self.store,self.task_id,call,self.script_root,self.runtime_id)
        # BEGIN IMMEDIATE makes racing dispatches observe one claim.
        with self.store.db.write() as db:
            row=db.execute('SELECT state,args_hash FROM actions WHERE operation_id=?',(operation['operation_id'],)).fetchone()
            plan=db.execute('SELECT revision,approved_revision FROM plans WHERE task_id=?',(self.task_id,)).fetchone()
            task_revision=db.execute('SELECT revision FROM tasks WHERE id=?',(self.task_id,)).fetchone()[0]
            if task_revision!=expected_task_revision or row['state']!='pending' or row['args_hash']!=context.fingerprint() or not plan or plan['revision']!=context.plan_revision or plan['approved_revision']!=context.plan_revision:
                return self.denied(call,'The operation or its plan changed before dispatch.')
            db.execute("UPDATE actions SET state='dispatching',plan_revision=? WHERE operation_id=?",(context.plan_revision,operation['operation_id']))
        # Bind the canonical operation in a task-local context, including across
        # aexecute's worker thread, without sharing IDs between concurrent calls.
        try:
            scope=self.backend.operation_scope(operation['operation_id']) if self.backend and hasattr(self.backend,'operation_scope') else nullcontext()
            from .network_access import current as network_permission
            permission=network_permission(self.store,self.task_id) if call['name']=='execute' else None
            reviewed_network=context.environment_profile.split(':')[1] if context.environment_profile.startswith('network:') else None
            if call['name']=='execute' and reviewed_network!=(permission['fingerprint'] if permission else None):
                self.store.set_action_state(operation['operation_id'],'denied',error='Sandbox network permission changed before dispatch.')
                return self.denied(call,'Network permission changed; review this command again.')
            network_scope=self.backend.network_scope(permission['expiry'] if permission else None) if self.backend and hasattr(self.backend,'network_scope') else nullcontext()
            with scope,network_scope:
                if edit:
                    request=request.override(tool_call=call)
                result=await handler(request)
                receipt=getattr(self.backend,'last_receipt',None) if call['name']=='execute' else None
        except BaseException:
            self.store.set_action_state(operation['operation_id'],'unknown',error='Tool did not return a durable result.')
            raise
        if (call['name']=='execute' and receipt is None) or (receipt is not None and (receipt.unknown or receipt.operation_id != operation['operation_id'])):
            self.store.set_action_state(operation['operation_id'],'unknown',error='The runtime could not confirm the command result.')
            return result
        if not isinstance(result,ToolMessage):
            self.store.set_action_state(operation['operation_id'],'unknown',error='Tool result cannot be safely replayed.')
            return result
        if edit:
            result=result.model_copy(update={'content':'A human edited this tool call before execution.\n'+str(result.content)})
        state='failed' if result.status=='error' or (receipt is not None and (receipt.exit_code!=0 or receipt.stopped or receipt.timed_out)) else 'succeeded'
        public_receipt=None
        if receipt is not None:
            public_receipt=receipt.as_dict()
            output=receipt.output.encode('utf-8')
            public_receipt['output']=output[:65536].decode('utf-8',errors='ignore')
            public_receipt['truncated']=receipt.truncated or len(output)>65536
            public_receipt['cwd']=context.cwd
        self.store.set_action_state(operation['operation_id'],state,result_ref=result.model_dump_json(),receipt=public_receipt)
        if receipt is not None:finish_check(self.store,self.task_id,prepared_check,receipt)
        return result
