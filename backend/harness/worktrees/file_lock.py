"""Windows file/parent handles for a bounded edit of an existing regular file.

Parents deny rename/delete while held; the file denies other writers and
replacement. No path-based reopen is used for the write. The durable edit
journal, rather than an atomic-replace claim, covers interruption mid-write.
"""
from contextlib import contextmanager
import os
import stat

from server.errors import ApiError
from .snapshot import validate_relative,excluded


@contextmanager
def locked_regular_file(root,path,*,create_new=False,delete_access=False):
    relative=validate_relative(path)
    if excluded(relative):raise ApiError('invalid_request','Excluded file cannot be edited.',status_code=422)
    if os.name!='nt':
        raise ApiError('runtime_unavailable','Exclusive file editing is currently supported on Windows only.',status_code=409)
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    create=kernel.CreateFileW
    create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    create.restype=wintypes.HANDLE
    close=kernel.CloseHandle;close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
    attributes=kernel.GetFileAttributesW;attributes.argtypes=[wintypes.LPCWSTR];attributes.restype=wintypes.DWORD
    invalid=ctypes.c_void_p(-1).value
    handles=[];file_handle=None;stream=None
    def acquire(file,access,sharing,flags,disposition=3):
        handle=create(str(file),access,sharing,None,disposition,flags,None)
        if handle==invalid:
            raise ApiError('workspace_busy','The file or a parent is unavailable or open for writing.',status_code=409)
        return handle
    try:
        # Include ancestors of storage root so a junction swap above root cannot
        # redirect the final open. OPEN_REPARSE_POINT opens a link itself.
        parents=list(reversed(root.absolute().parents))+[root.absolute()]
        cursor=root.absolute()
        for part in relative.parts[:-1]:
            cursor=cursor/part;parents.append(cursor)
        for parent in parents:
            if create_new and parent!=root and root in parent.parents and not parent.exists():
                parent.mkdir() # preceding parent is already held against replacement
            handle=acquire(parent,0x80,3,0x02200000) # READ_ATTRIBUTES, share READ|WRITE, BACKUP_SEMANTICS|OPEN_REPARSE_POINT
            handles.append(handle)
            attr=attributes(str(parent))
            if attr==0xFFFFFFFF or attr & 0x400 or not attr & 0x10:
                raise ApiError('invalid_request','An edit parent is not a regular directory.',status_code=422)
        target=root.joinpath(*relative.parts)
        file_handle=acquire(target,0xC0000000|(0x10000 if delete_access else 0),1,0x00200000,1 if create_new else 3)
        fd=msvcrt.open_osfhandle(int(file_handle),os.O_RDWR|os.O_BINARY)
        file_handle=None # ownership is now the Python descriptor
        stream=os.fdopen(fd,'r+b')
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or getattr(info,'st_file_attributes',0)&0x400:
            raise ApiError('invalid_request','Links and non-regular files cannot be edited.',status_code=422)
        yield stream
    finally:
        if stream is not None:stream.close()
        if file_handle is not None:close(file_handle)
        for handle in reversed(handles):close(handle)


def delete_locked_file(stream):
    """Delete exactly the open file on close, never reopen its path."""
    import ctypes,msvcrt
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    function=kernel.SetFileInformationByHandle
    function.argtypes=[wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID,wintypes.DWORD]
    function.restype=wintypes.BOOL
    flag=wintypes.BOOL(True)
    if not function(msvcrt.get_osfhandle(stream.fileno()),4,ctypes.byref(flag),ctypes.sizeof(flag)):
        raise OSError(ctypes.get_last_error(),'Cannot delete the locked file.')
