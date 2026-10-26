"""Actual Python/Node/TypeScript/package installation in the Bridge sandbox.

No provider, network, user files or host shell execution. HITL is tested in
the gateway suites; these tests prove the approved commands can actually run.
"""
import json
from pathlib import Path
import shutil
import uuid
import zipfile

import pytest

from harness.runtime.docker import DockerRuntime


@pytest.fixture
def sandbox(tmp_path):
    runtime = DockerRuntime()
    if not runtime.capability().available:
        pytest.skip('Bridge Docker image unavailable; coding toolchains not verified.')
    return runtime, tmp_path


def execute(sandbox, command):
    runtime, root = sandbox
    return runtime.execute(command, snapshot=root, exec_id='toolchain-' + uuid.uuid4().hex[:10], timeout=90)


def test_node_npm_test_and_offline_package_install(sandbox):
    _, root = sandbox
    (root / 'package.json').write_text(json.dumps({'name':'bridge-test','version':'1.0.0','scripts':{'test':'node check.js'}}))
    (root / 'check.js').write_text("const assert=require('node:assert/strict'); assert.equal(require('bridge-fixture').answer,42); console.log('REAL_NPM_TEST_PASSED');")
    package = root / 'fixture-package'
    package.mkdir()
    (package / 'package.json').write_text(json.dumps({'name':'bridge-fixture','version':'1.0.0','main':'index.js'}))
    (package / 'index.js').write_text('exports.answer=42;')
    result = execute(sandbox, 'node --version && npm --version && npm install --ignore-scripts --no-audit --no-fund --package-lock=false ./fixture-package && npm test')
    assert result.exit_code == 0, result.output
    assert 'REAL_NPM_TEST_PASSED' in result.output


def test_typescript_real_compilation_and_execution(sandbox):
    _, root = sandbox
    compiler = Path(__file__).resolve().parents[2] / 'node_modules/typescript'
    if not compiler.is_dir():
        pytest.skip('Install the frontend dependencies to verify the real TypeScript compiler.')
    shutil.copytree(compiler, root / 'typescript')
    (root / 'main.ts').write_text('const add = (a: number, b: number): number => a + b; if(add(2,3)!==5) throw Error("wrong result"); console.log("REAL_TYPESCRIPT_BUILD_PASSED");')
    result = execute(sandbox, 'node typescript/bin/tsc main.ts --strict --target es2022 --outDir compiled && node compiled/main.js')
    assert result.exit_code == 0, result.output
    assert 'REAL_TYPESCRIPT_BUILD_PASSED' in result.output


def test_python_pip_offline_install_and_execution(sandbox):
    _, root = sandbox
    entries = {
        'bridge_fixture/__init__.py': 'answer = 42\n',
        'bridge_fixture-0.1.dist-info/METADATA': 'Metadata-Version: 2.1\nName: bridge-fixture\nVersion: 0.1\n',
        'bridge_fixture-0.1.dist-info/WHEEL': 'Wheel-Version: 1.0\nGenerator: bridge-acceptance\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
    }
    record = 'bridge_fixture-0.1.dist-info/RECORD'
    entries[record] = ''.join(name + ',,\n' for name in [*entries, record])
    with zipfile.ZipFile(root / 'bridge_fixture-0.1-py3-none-any.whl', 'w') as wheel:
        for name, body in entries.items():
            wheel.writestr(name, body)
    result = execute(sandbox, 'python -m pip install --no-index --no-deps --target /workspace/vendor ./bridge_fixture-0.1-py3-none-any.whl && PYTHONPATH=/workspace/vendor python -c "import bridge_fixture; assert bridge_fixture.answer == 42; print(\'REAL_PIP_INSTALL_PASSED\')"')
    assert result.exit_code == 0, result.output
    assert 'REAL_PIP_INSTALL_PASSED' in result.output
