import os
import threading
import time
from pathlib import Path

import pytest
from harness.runtime.local import LocalRuntime


def test_local_python_node_and_clean_environment(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','must-not-reach-command')
    root=tmp_path/'project';root.mkdir()
    (root/'main.py').write_text('import os\nfrom pathlib import Path\nassert "OPENAI_API_KEY" not in os.environ\nPath("made.txt").write_text("own files")\nprint("LOCAL_PYTHON_OK")\n')
    runtime=LocalRuntime()
    result=runtime.execute('python main.py',snapshot=root,exec_id='local-python')
    assert result.exit_code==0,result.output
    assert 'LOCAL_PYTHON_OK' in result.output and (root/'made.txt').exists()
    result=runtime.execute('node -e "console.log(12345)"',snapshot=root,exec_id='local-node')
    assert result.exit_code==0 and '12345' in result.output
    assert runtime.capability().available and not runtime.processes


def test_cancel_and_timeout_are_real(tmp_path):
    runtime=LocalRuntime();(tmp_path/'wait.py').write_text('import time\ntime.sleep(60)')
    result=runtime.execute('python wait.py',snapshot=tmp_path,exec_id='timeout',timeout=.3)
    assert result.timed_out and not result.unknown
    results=[]
    worker=threading.Thread(target=lambda:results.append(runtime.execute('python wait.py',snapshot=tmp_path,exec_id='cancel')))
    worker.start()
    for _ in range(100):
        if 'cancel' in runtime.processes:break
        time.sleep(.02)
    assert runtime.cancel('cancel')
    worker.join(10)
    assert not worker.is_alive() and results[0].stopped


@pytest.mark.skipif(os.name!='nt',reason='Windows process jobs')
def test_engine_crash_kills_the_owned_process_tree(tmp_path):
    import ctypes
    import subprocess
    import sys
    from ctypes import wintypes as w
    script="from harness.runtime.local import LocalRuntime; import time; from pathlib import Path; r=LocalRuntime(); e=r.start('python -c \\\"import time;time.sleep(60)\\\"',snapshot=Path("+repr(str(tmp_path))+"),exec_id='crash-test'); print(e['process'].pid,flush=True); time.sleep(60)"
    worker=subprocess.Popen([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    handle=None
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
    kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    try:
        line=worker.stdout.readline().strip()
        assert line.isdigit(),worker.stderr.read()
        handle=kernel.OpenProcess(0x100000,False,int(line))
        assert handle
        worker.kill();worker.wait(timeout=5)
        assert kernel.WaitForSingleObject(handle,5000)==0
    finally:
        if worker.poll() is None:worker.kill();worker.wait()
        if handle:kernel.CloseHandle(handle)
