"""Read console events in an isolated terminal; never invokes a model or client."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys


class COORD(C.Structure):
    _fields_ = [('x', C.c_short), ('y', C.c_short)]


class MOUSE(C.Structure):
    _fields_ = [('pos', COORD), ('buttons', W.DWORD), ('control', W.DWORD), ('flags', W.DWORD)]


class KEY(C.Structure):
    _fields_ = [('down', W.BOOL), ('repeat', W.WORD), ('vkey', W.WORD),
                ('scan', W.WORD), ('char', W.WCHAR), ('control', W.DWORD)]


class EVENT(C.Union):
    _fields_ = [('key', KEY), ('mouse', MOUSE)]


class RECORD(C.Structure):
    _fields_ = [('type', W.WORD), ('event', EVENT)]


kernel = C.WinDLL('kernel32', use_last_error=True)
kernel.GetStdHandle.argtypes = [W.DWORD]; kernel.GetStdHandle.restype = W.HANDLE
kernel.GetConsoleMode.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
kernel.SetConsoleMode.argtypes = [W.HANDLE, W.DWORD]
kernel.ReadConsoleInputW.argtypes = [W.HANDLE, C.POINTER(RECORD), W.DWORD, C.POINTER(W.DWORD)]
source, sink = kernel.GetStdHandle(-10), kernel.GetStdHandle(-11)
input_mode, output_mode = W.DWORD(), W.DWORD()
assert kernel.GetConsoleMode(source, C.byref(input_mode))
assert kernel.GetConsoleMode(sink, C.byref(output_mode))
mode = (input_mode.value | 0x18) & ~0x240  # mouse/window input, no QuickEdit or VT input
if sys.argv[2] == 'vt': mode |= 0x200
assert kernel.SetConsoleMode(source, mode)
assert kernel.SetConsoleMode(sink, output_mode.value | 4)
try:
    print('\x1b[?1000h\x1b[?1006hMOUSE_READY', flush=True)
    events = []; chars = ''
    while not chars.endswith('q'):
        record, count = RECORD(), W.DWORD()
        assert kernel.ReadConsoleInputW(source, C.byref(record), 1, C.byref(count))
        if record.type == 2:
            item = record.event.mouse
            events.append([item.pos.x, item.pos.y, item.buttons, item.flags])
        elif record.type == 1 and record.event.key.down:
            chars += record.event.key.char
    Path(sys.argv[1]).write_text(json.dumps({'mouse': events, 'text': chars}), encoding='utf-8')
finally:
    print('\x1b[?1000l\x1b[?1006l', end='', flush=True)
    kernel.SetConsoleMode(source, input_mode.value)
    kernel.SetConsoleMode(sink, output_mode.value)
print('MOUSE_DONE', flush=True)
