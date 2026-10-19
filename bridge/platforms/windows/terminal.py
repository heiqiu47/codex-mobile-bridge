"""Windows 10 1809+ transport with an app-local Microsoft ConPTY host."""
import codecs
import collections
import ctypes as C
from ctypes import wintypes as W
import hashlib
import ntpath
import os
import struct
from pathlib import Path

from bridge.resources import project_root
import queue
import subprocess
import sys
import threading
import time
import uuid

from bridge.platforms.posix.terminal import TerminalSession, default_shell, dimensions


class COORD(C.Structure):
    _fields_ = [('X', C.c_short), ('Y', C.c_short)]


class STARTUPINFO(C.Structure):
    _fields_ = [('cb', W.DWORD), ('lpReserved', W.LPWSTR), ('lpDesktop', W.LPWSTR),
                ('lpTitle', W.LPWSTR), ('dwX', W.DWORD), ('dwY', W.DWORD),
                ('dwXSize', W.DWORD), ('dwYSize', W.DWORD), ('dwXCountChars', W.DWORD),
                ('dwYCountChars', W.DWORD), ('dwFillAttribute', W.DWORD), ('dwFlags', W.DWORD),
                ('wShowWindow', W.WORD), ('cbReserved2', W.WORD), ('lpReserved2', C.c_void_p),
                ('hStdInput', W.HANDLE), ('hStdOutput', W.HANDLE), ('hStdError', W.HANDLE)]


class STARTUPINFOEX(C.Structure):
    _fields_ = [('StartupInfo', STARTUPINFO), ('lpAttributeList', C.c_void_p)]


class PROCESS_INFORMATION(C.Structure):
    _fields_ = [('hProcess', W.HANDLE), ('hThread', W.HANDLE), ('dwProcessId', W.DWORD), ('dwThreadId', W.DWORD)]


class PROCESSENTRY32W(C.Structure):
    _fields_ = [('dwSize', W.DWORD), ('cntUsage', W.DWORD), ('th32ProcessID', W.DWORD),
                ('th32DefaultHeapID', C.c_void_p), ('th32ModuleID', W.DWORD),
                ('cntThreads', W.DWORD), ('th32ParentProcessID', W.DWORD),
                ('pcPriClassBase', W.LONG), ('dwFlags', W.DWORD), ('szExeFile', W.WCHAR * 260)]


def _process_snapshot(kernel):
    kernel.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = W.HANDLE
    kernel.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(PROCESSENTRY32W)]
    kernel.Process32NextW.argtypes = [W.HANDLE, C.POINTER(PROCESSENTRY32W)]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if not snapshot or snapshot == C.c_void_p(-1).value: raise OSError('无法核验终端进程')
    try:
        item = PROCESSENTRY32W(); item.dwSize = C.sizeof(item); result = []
        if not kernel.Process32FirstW(snapshot, C.byref(item)): raise OSError('无法核验终端进程')
        while True:
            result.append((item.th32ProcessID, item.th32ParentProcessID, item.szExeFile))
            if not kernel.Process32NextW(snapshot, C.byref(item)): break
        return result
    finally: kernel.CloseHandle(snapshot)


def _shell_pid(kernel, bootstrap_pid, shell):
    entries = _process_snapshot(kernel)
    children = [(pid, name) for pid, parent, name in entries if parent == bootstrap_pid]
    if len(children) != 1 or children[0][1].casefold() != ntpath.basename(shell).casefold():
        raise ValueError('无法确认终端 shell 进程')
    pid = children[0][0]
    if any(parent == pid for _, parent, _ in entries):
        raise ValueError('前台程序运行时无法确认 shell 当前目录')
    return pid


def _process_cwd(kernel, pid, shell, job):
    if C.sizeof(C.c_void_p) != 8: raise ValueError('Windows 路径补全需要 64 位网关')
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    kernel.GetProcessTimes.argtypes = [W.HANDLE, *([C.POINTER(C.c_uint64)] * 4)]
    kernel.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)]
    handle = kernel.OpenProcess(0x0410, False, pid)
    if not handle: raise ValueError('无法读取终端 shell 进程')
    try:
        owned = W.BOOL()
        if not kernel.IsProcessInJob(handle, job, C.byref(owned)) or not owned.value:
            raise OSError('终端 shell 不属于此终端')
        def identity():
            path = C.create_unicode_buffer(32768); size = W.DWORD(len(path))
            if not kernel.QueryFullProcessImageNameW(handle, 0, path, C.byref(size)):
                raise OSError('无法确认终端 shell 路径')
            expected = ntpath.normcase(ntpath.normpath(shell))
            actual = ntpath.normcase(ntpath.normpath(path.value))
            if actual != expected: raise OSError('终端 shell 身份已变化')
            times = [C.c_uint64() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(C.byref(value) for value in times)):
                raise OSError('无法确认终端 shell 启动时间')
            return times[0].value
        started = identity()
        ntdll = C.WinDLL('ntdll', use_last_error=True)
        ntdll.NtQueryInformationProcess.argtypes = [W.HANDLE, W.DWORD, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
        ntdll.NtQueryInformationProcess.restype = C.c_long
        def read(address, size):
            if not address or not 0 < size <= 32768: raise OSError('终端当前目录地址无效')
            buffer = C.create_string_buffer(size); count = C.c_size_t()
            if not kernel.ReadProcessMemory(handle, C.c_void_p(address), buffer, size, C.byref(count)) or count.value != size:
                raise OSError('无法读取终端当前目录')
            return buffer.raw
        basic = C.create_string_buffer(48)
        if ntdll.NtQueryInformationProcess(handle, 0, basic, len(basic), None) != 0:
            raise OSError('无法读取终端 shell 状态')
        peb = struct.unpack_from('<Q', basic.raw, 8)[0]
        params = struct.unpack('<Q', read(peb + 0x20, 8))[0]
        unicode = read(params + 0x38, 16)
        length = struct.unpack_from('<H', unicode)[0]
        address = struct.unpack_from('<Q', unicode, 8)[0]
        if not length or length % 2 or length > 32768: raise OSError('终端当前目录格式无效')
        cwd = ntpath.normpath(read(address, length).decode('utf-16-le'))
        if identity() != started or not ntpath.isabs(cwd): raise OSError('无法确认终端当前目录')
        return cwd
    except (OSError, UnicodeError):
        raise ValueError('无法只读确认终端当前目录') from None
    finally: kernel.CloseHandle(handle)


class JOB_BASIC_LIMITS(C.Structure):
    _fields_ = [('process_time', C.c_int64), ('job_time', C.c_int64), ('flags', W.DWORD),
                ('minimum', C.c_size_t), ('maximum', C.c_size_t), ('active', W.DWORD),
                ('affinity', C.c_size_t), ('priority', W.DWORD), ('scheduling', W.DWORD)]


class JOB_IO_COUNTERS(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in ('reads', 'writes', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]


class JOB_EXTENDED_LIMITS(C.Structure):
    _fields_ = [('basic', JOB_BASIC_LIMITS), ('io', JOB_IO_COUNTERS),
                ('process_memory', C.c_size_t), ('job_memory', C.c_size_t),
                ('peak_process_memory', C.c_size_t), ('peak_job_memory', C.c_size_t)]


def _load_conpty(kernel):
    frozen = getattr(sys, 'frozen', False)
    folder = project_root() / ('conpty' if frozen else 'dist/conpty')
    # Source checkouts may use the inbox console until the build dependency is
    # prepared. A packaged or partial bundle must never silently fall back to
    # Windows 10's console, which drops mouse tracking and SGR input.
    if not folder.exists() and not frozen:
        return
    files = ['conpty.dll', *(arch + '/OpenConsole.exe' for arch in ('x64', 'arm64', 'x86'))]
    if not all((folder / name).is_file() for name in files):
        raise OSError('Windows 终端组件不完整，请重新安装网关')
    library = C.WinDLL(str(folder / 'conpty.dll'), use_last_error=True)
    for name in ('CreatePseudoConsole', 'ResizePseudoConsole', 'ClosePseudoConsole'):
        setattr(kernel, name, getattr(library, 'Conpty' + name))
    # Keep the DLL alive for the whole session; create/resize/close must use the
    # same implementation and HPCON layout.
    kernel._conpty_library = library


def api(conpty=False):
    kernel = C.WinDLL('kernel32', use_last_error=True)
    if conpty:
        _load_conpty(kernel)
    signatures = {
        'CreatePipe': (W.BOOL, [C.POINTER(W.HANDLE), C.POINTER(W.HANDLE), C.c_void_p, W.DWORD]),
        'SetConsoleCtrlHandler': (W.BOOL, [C.c_void_p, W.BOOL]),
        'CreatePseudoConsole': (C.c_long, [COORD, W.HANDLE, W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]),
        'ResizePseudoConsole': (C.c_long, [W.HANDLE, COORD]), 'ClosePseudoConsole': (None, [W.HANDLE]),
        'InitializeProcThreadAttributeList': (W.BOOL, [C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)]),
        'UpdateProcThreadAttribute': (W.BOOL, [C.c_void_p, W.DWORD, C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p]),
        'DeleteProcThreadAttributeList': (None, [C.c_void_p]),
        'CreateProcessW': (W.BOOL, [W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL, W.DWORD, C.c_void_p, W.LPCWSTR, C.POINTER(STARTUPINFOEX), C.POINTER(PROCESS_INFORMATION)]),
        'ReadFile': (W.BOOL, [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]),
        'WriteFile': (W.BOOL, [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]),
        'WaitForSingleObject': (W.DWORD, [W.HANDLE, W.DWORD]),
        'GetExitCodeProcess': (W.BOOL, [W.HANDLE, C.POINTER(W.DWORD)]),
        'TerminateProcess': (W.BOOL, [W.HANDLE, W.UINT]), 'CloseHandle': (W.BOOL, [W.HANDLE]),
        'CreateJobObjectW': (W.HANDLE, [C.c_void_p, W.LPCWSTR]),
        'SetInformationJobObject': (W.BOOL, [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]),
        'AssignProcessToJobObject': (W.BOOL, [W.HANDLE, W.HANDLE]),
        'ResumeThread': (W.DWORD, [W.HANDLE]),
    }
    for name, (restype, argtypes) in signatures.items():
        try: function = getattr(kernel, name)
        except AttributeError: raise ValueError('连续终端需要 Windows 10 1809 或更新版本') from None
        function.restype, function.argtypes = restype, argtypes
    return kernel


def checked(result):
    if not result:
        raise C.WinError(C.get_last_error())


def child_main(shell):
    # The Python bootstrap may retain redirected CRT descriptors after ConPTY
    # attaches. Pass fresh console handles to cmd and its external children.
    # The launcher may also inherit Ctrl+C ignore from its process group.
    checked(api().SetConsoleCtrlHandler(None, False))
    with open('CONIN$', 'rb', buffering=0) as source, open('CONOUT$', 'wb', buffering=0) as sink:
        raise SystemExit(subprocess.call([shell], stdin=source, stdout=sink, stderr=sink))


def cmd_working_directory(root):
    # CMD treats an extended local path as UNC and falls back to C:\Windows.
    # Use its drive spelling only when both names resolve to the same directory.
    if (len(root) >= 7 and root.startswith('\\\\?\\')
            and root[4] in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' and root[5:7] == ':\\'):
        ordinary = root[4:]
        try:
            if os.path.samefile(root, ordinary): return ordinary
        except OSError:
            pass
    return root


class WindowsTerminalSession(TerminalSession):
    def current_cwd(self):
        if self.done.is_set() or self.stopping.is_set(): raise ValueError('终端已关闭，请重新打开')
        pid = _shell_pid(self.kernel, self.bootstrap_pid, self.shell)
        cwd = _process_cwd(self.kernel, pid, self.shell, self.job)
        if _shell_pid(self.kernel, self.bootstrap_pid, self.shell) != pid or self.done.is_set():
            raise ValueError('无法确认终端当前目录')
        return cwd

    def __init__(self, root, cols=80, rows=24):
        dimensions(cols, rows)
        self.kernel = k = api(conpty=True)
        self.lock = threading.RLock(); self.changed = threading.Event(); self.input_lock = threading.Lock(); self.close_lock = threading.Lock()
        self.text = ''; self.end = 0; self.reason = ''; self.code = None
        self.done = threading.Event(); self.output_done = threading.Event(); self.stopping = threading.Event(); self.touched = time.monotonic()
        self.inputs = collections.OrderedDict(); self.writes = queue.Queue()
        self.shell = default_shell(); self.root = str(root)
        self.console = W.HANDLE(); self.process_handle = None; self.job = None
        input_read, self.input_write, self.output_read, output_write = (W.HANDLE() for _ in range(4))
        handles = [input_read, self.input_write, self.output_read, output_write]
        attributes = None; initialized = False; process = PROCESS_INFORMATION()
        try:
            # An unnamed, non-inheritable job owns only this terminal's tree.
            # Bind the suspended bootstrap before it can create the user's shell.
            self.job = k.CreateJobObjectW(None, None); checked(self.job)
            limits = JOB_EXTENDED_LIMITS(); limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE
            checked(k.SetInformationJobObject(self.job, 9, C.byref(limits), C.sizeof(limits)))
            checked(k.CreatePipe(C.byref(input_read), C.byref(self.input_write), None, 0))
            checked(k.CreatePipe(C.byref(self.output_read), C.byref(output_write), None, 0))
            if k.CreatePseudoConsole(COORD(cols, rows), input_read, output_write, 0, C.byref(self.console)) < 0:
                raise OSError('CreatePseudoConsole failed')
            size = C.c_size_t()
            k.InitializeProcThreadAttributeList(None, 1, 0, C.byref(size))
            attributes = C.create_string_buffer(size.value)
            checked(k.InitializeProcThreadAttributeList(attributes, 1, 0, C.byref(size))); initialized = True
            checked(k.UpdateProcThreadAttribute(attributes, 0, 0x00020016, self.console, C.sizeof(self.console), None, None))
            startup = STARTUPINFOEX(); startup.StartupInfo.cb = C.sizeof(startup)
            startup.lpAttributeList = C.cast(attributes, C.c_void_p)
            # The helper reconnects its standard handles before starting the user's shell.
            launcher = [sys.executable]
            if not getattr(sys, 'frozen', False): launcher.append(str(project_root() / 'desktop.py'))
            launcher.extend(['--terminal-child', self.shell])
            command = C.create_unicode_buffer(subprocess.list2cmdline(launcher))
            directory = cmd_working_directory(self.root) if ntpath.basename(self.shell).casefold() == 'cmd.exe' else self.root
            checked(k.CreateProcessW(sys.executable, command, None, None, False, 0x00080004, None, directory, C.byref(startup), C.byref(process)))
            self.process_handle = process.hProcess
            self.bootstrap_pid = process.dwProcessId
            checked(k.AssignProcessToJobObject(self.job, self.process_handle))
            checked(k.ResumeThread(process.hThread) != 0xffffffff)
        except Exception:
            if self.process_handle:
                # Assignment itself may have failed; retain the exact owned handle.
                k.TerminateProcess(self.process_handle, 1)
                k.WaitForSingleObject(self.process_handle, 5000)
                k.CloseHandle(self.process_handle); self.process_handle = None
            if self.job: k.CloseHandle(self.job); self.job = None
            if self.console.value: k.ClosePseudoConsole(self.console)
            for handle in handles:
                if handle.value: k.CloseHandle(handle)
            raise
        finally:
            if process.hThread: k.CloseHandle(process.hThread)
            if initialized: k.DeleteProcThreadAttributeList(attributes)
        k.CloseHandle(input_read); k.CloseHandle(output_write)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._writer, daemon=True).start()
        threading.Thread(target=self._wait, daemon=True).start()
        threading.Thread(target=self._idle, daemon=True).start()

    def _read(self):
        decoder = codecs.getincrementaldecoder('utf-8')('replace'); buffer = C.create_string_buffer(32768)
        try:
            while True:
                count = W.DWORD()
                if not self.kernel.ReadFile(self.output_read, buffer, len(buffer), C.byref(count), None) or not count.value: break
                self.append(decoder.decode(buffer.raw[:count.value]))
            self.append(decoder.decode(b'', final=True))
        finally:
            self.kernel.CloseHandle(self.output_read)
            self.output_done.set()

    def _wait(self):
        self.kernel.WaitForSingleObject(self.process_handle, 0xffffffff)
        code = W.DWORD(); self.kernel.GetExitCodeProcess(self.process_handle, C.byref(code)); self.code = code.value
        self._close_console()
        with self.close_lock:
            self.kernel.CloseHandle(self.process_handle); self.process_handle = None
        # Pipe EOF can precede process exit. A completed terminal must release
        # its working directory and drain all output before manager cleanup.
        self.output_done.wait()
        self.done.set(); self.changed.set()

    def _close_console(self):
        # ClosePseudoConsole may wait for output to drain; the reader stays alive.
        with self.close_lock:
            if self.console.value:
                self.stopping.set(); self.writes.put(None)
                # Closing ConPTY before the bootstrap attaches can miss its later
                # shell. The retained job closes that race without PID matching.
                if self.job: self.kernel.CloseHandle(self.job); self.job = None
                self.kernel.ClosePseudoConsole(self.console); self.console = W.HANDLE()

    def _writer(self):
        try:
            while True:
                job = self.writes.get()
                if job is None: break
                raw, result = job
                try:
                    if self.stopping.is_set(): raise OSError('终端已关闭，请重新打开')
                    offset = 0
                    while offset < len(raw):
                        count = W.DWORD(); data = C.create_string_buffer(raw[offset:])
                        checked(self.kernel.WriteFile(self.input_write, data, len(raw)-offset, C.byref(count), None))
                        if not count.value: raise OSError('Terminal input closed')
                        offset += count.value
                except OSError as error: result['error'] = error
                finally: result['done'].set()
        finally:
            self.kernel.CloseHandle(self.input_write)

    def write(self, identifier, data):
        uuid.UUID(str(identifier))
        if not isinstance(data, str) or not data or len(data.encode('utf-8')) > 16384: raise ValueError('无效终端输入')
        raw = data.encode('utf-8'); digest = hashlib.sha256(raw).digest()
        with self.input_lock:
            if self.done.is_set() or self.stopping.is_set(): raise ValueError('终端已关闭，请重新打开')
            result = self.inputs.get(identifier)
            if result is None:
                result = {'digest': digest, 'done': threading.Event()}; self.inputs[identifier] = result
                self.writes.put((raw, result))
            if result['digest'] != digest: raise ValueError('输入编号已用于其他内容')
            self.touched = time.monotonic()
            if not result['done'].wait(3): raise TimeoutError('终端输入拥堵，请重试')
            if result.get('error'): raise result['error']
            while len(self.inputs) > 256: self.inputs.popitem(last=False)
        return {'accepted': True}

    def resize(self, cols, rows):
        dimensions(cols, rows)
        with self.close_lock:
            if not self.console.value: return {'resized': False}
            if self.kernel.ResizePseudoConsole(self.console, COORD(cols, rows)) < 0: raise OSError('ResizePseudoConsole failed')
        return {'resized': True}

    def stop(self, reason='终端已关闭'):
        if self.done.is_set() or self.stopping.is_set(): return
        self.reason = reason
        threading.Thread(target=self._close_console, daemon=True).start()
