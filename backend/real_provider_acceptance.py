"""Bounded real-model acceptance, using only a disposable coding project.

Reads the default Bridge model without copying or printing its key. Never
approves network, installation or commands other than the fixture's check.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile

from server import settings
from server.storage import Store
from server.storage.approvals import ApprovalStore
from server.runs import RunManager
from harness import Workspace
from harness.models import probe_model, _redact
from harness.task_controller import TaskController
from harness.task_runtime import task_directory, runtime_descriptor
from harness.runtime.docker import DockerRuntime
from harness.verification.results import CheckResults
from harness.verification.observe import current_quality

ROOT = Path(__file__).resolve().parents[1]
LOCAL = os.environ.get('BRIDGE_ACCEPT_LOCAL')=='1'
OUTPUT = ROOT / ('checks/local-real-provider.json' if LOCAL else 'checks/phase-2/real-provider.json')


async def main():
    spec = settings.model_spec(None)
    report = {'passed': False, 'scope': 'Real configured provider + Deep Agents/LangGraph + '+('local execution' if LOCAL else 'Docker')+'; disposable Python project', 'checks': []}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    def check(name, value):
        report['checks'].append({'name': name, 'passed': bool(value)})
        if not value:
            raise RuntimeError(name)

    try:
        if spec is None or spec.base_url.startswith('demo:'):
            report['blocked'] = 'Configure and select a real model in Bridge settings.'
            return 3
        report['model'] = spec.model  # no endpoint or credential in the deliverable
        capability = await probe_model(spec, timeout=40)
        check('real provider tool-call probe', capability['demo'] is False and capability['tools'] is True)
        if LOCAL:
            from harness.runtime.local import LocalRuntime
            check('native runtime ready without Docker',LocalRuntime().capability().available)
        else:check('real Docker runtime available', DockerRuntime().capability().available)
        temporary = Path(tempfile.mkdtemp(prefix='provider-', dir=ROOT / '.test-runs'))
        # Captured spec stays in memory; only the fixture's product state moves.
        os.environ['HARNESS_HOME'] = str(temporary / 'home')
        workspace = Workspace.at(temporary / 'project').scaffold()
        original = 'def add(a, b):\n    return a - b\n'
        (workspace.root / 'main.py').write_text(original, encoding='utf-8')
        checker = 'from main import add\nassert add(2, 3) == 5\nassert add(-1, 1) == 0\nprint("REAL_PROVIDER_CHECK_PASSED")\n'
        (workspace.root / 'check.py').write_text(checker, encoding='utf-8')
        (workspace.root / 'README.md').write_text('Fix add in main.py. Run python check.py before and after the fix. Do not change check.py or install dependencies.', encoding='utf-8')
        store = Store()
        store.ensure_schema()
        profile = {'commands': [{'id': 'test', 'command': 'python check.py', 'source': 'check.py', 'required': True}]}
        profile['profile_hash'] = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
        ws = store.upsert_workspace(str(workspace.root), profile=json.dumps(profile))
        task = store.create_task(workspace_id=ws['id'], prompt='Fix the incorrect add function in main.py. Inspect the repository, propose a plan, reproduce the failing python check.py, make a focused fix and run python check.py again. Do not change check.py, README.md or install anything. Keep todos current and report actual check results.', mode='auto', read_only=False)
        report['task_id'] = task['id']
        with store.db.write() as db:
            db.execute('UPDATE execution_budgets SET max_model_calls=20,max_tool_calls=60,max_active_ms=240000 WHERE task_id=?', (task['id'],))
        manager = RunManager(workspace)
        controller = TaskController(manager, store, model_resolver=lambda: spec)

        async def wait():
            try:
                await asyncio.wait_for(manager.wait(task['thread_id']), timeout=180)
            except asyncio.TimeoutError:
                manager.runner.stop(task['thread_id'])
                raise RuntimeError('Real-provider segment timed out; not accepted.')

        print('Real provider: read-only planning', flush=True)
        controller.propose(task['id'])
        await wait()
        plan = store.plan(task['id'])
        check('model produced a durable plan', plan is not None and len(plan['steps']) > 0)
        # This is the reviewer decision: only main.py and the known check.
        plan = store.save_plan(task['id'], steps=plan['steps'], scope=['main.py'], checks=['python check.py'], profile_hash=profile['profile_hash'], expected_revision=plan['revision'])
        controller.approve(task['id'], plan['revision'])
        check('exact plan revision approved', store.plan(task['id'])['approved_revision'] == plan['revision'])
        print('Real provider: approved execution and correction', flush=True)
        controller.execute(task['id'])
        for _ in range(5):
            await wait()
            pending = [row for row in ApprovalStore(store).list(task['id']) if row['state'] == 'pending']
            if not pending:
                break
            for row in pending:
                request = row['request'] or {}
                check('approval limited to fixture test', request.get('tool') == 'execute' and request.get('args', {}).get('command') == 'python check.py')
                ApprovalStore(store).decide(task['id'], row['id'], fingerprint=row['action_hash'], revision=row['revision'], decision='approve')
            controller.resume(task['id'], [])
        task = store.task(task['id'])
        report['state'] = task['status']
        report['budget'] = {k: store.budget(task['id']).get(k) for k in ['model_calls', 'tool_calls', 'active_ms']}
        results = CheckResults(store).list(task['id'])
        report['check_receipts'] = [{'outcome': r['outcome'], 'phase': r['details'].get('phase'), 'command': r['details'].get('command')} for r in results]
        check('real failing check observed', any(r['outcome'] == 'failed' for r in results))
        check('real passing check observed', any(r['outcome'] == 'passed' for r in results))
        working = task_directory(store, task['id']) / 'working'
        descriptor = runtime_descriptor(store, task['id'])
        quality = current_quality(store, task['id'], working, descriptor['runtime_id'])
        check('exact working snapshot verified', quality is not None and quality['quality_status'] == 'verified_snapshot')
        check('controller completed', task['status'] == 'closed' and task['outcome'] == 'completed')
        check('model changed source', (working / 'main.py').read_text(encoding='utf-8') != original)
        check('test criteria preserved', (working / 'check.py').read_text(encoding='utf-8') == checker)
        check('original project untouched until apply', (workspace.root / 'main.py').read_text(encoding='utf-8') == original)
        check('worker released', store.worker_lease() is None)
        report['passed'] = True
        return 0
    except Exception as error:
        report['error'] = _redact(error, spec.api_key if spec else '')
        return 1
    finally:
        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
