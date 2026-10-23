"""Read the native change time without scanning file contents."""

import ctypes
from ctypes import wintypes
import msvcrt


class _BasicInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_longlong) for name in
                ('creation', 'access', 'write', 'change')] + [('attributes', wintypes.DWORD)]


_query = ctypes.WinDLL('kernel32', use_last_error=True).GetFileInformationByHandleEx
_query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
_query.restype = wintypes.BOOL


def change_time(fd):
    # Python's Windows st_ctime is creation time, so it cannot detect an edit
    # whose size and last-write time have been restored.
    info = _BasicInfo()
    if not _query(msvcrt.get_osfhandle(fd), 0, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return info.change
