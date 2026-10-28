"""Windows owns the process tree: closing the engine also kills its jobs."""
import ctypes
from ctypes import wintypes as w


def bind(process):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    class Basic(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),('active',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
    class Counters(ctypes.Structure):
        _fields_=[(name,ctypes.c_ulonglong) for name in ('read','write','other','read_bytes','write_bytes','other_bytes')]
    class Limits(ctypes.Structure):
        _fields_=[('basic',Basic),('io',Counters),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
    kernel.CreateJobObjectW.restype=w.HANDLE
    kernel.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
    kernel.TerminateJobObject.argtypes=[w.HANDLE,w.UINT]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    handle=kernel.CreateJobObjectW(None,None)
    limits=Limits();limits.basic.flags=0x2000
    if not handle or not kernel.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle,w.HANDLE(int(process._handle))):
        error=ctypes.get_last_error()
        if handle:kernel.CloseHandle(handle)
        process.kill();process.wait()
        raise OSError(error,'Cannot track the local execution process tree')
    return kernel,handle


def close(job):
    kernel,handle=job
    kernel.TerminateJobObject(handle,1)
    kernel.CloseHandle(handle)
