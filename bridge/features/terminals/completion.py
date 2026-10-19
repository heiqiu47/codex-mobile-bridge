"""Read-only path suggestions for a terminal draft. Also embedded in the SSH helper."""
import ntpath
import os
import re
import shlex

MAX_DRAFT = 4096
MAX_SCAN = 2000
MAX_CANDIDATES = 80


def _offset(text, units):
    if type(units) is not int or units < 0: raise ValueError('无效光标位置')
    total = 0
    for index, char in enumerate(text):
        if total == units: return index
        total += 2 if ord(char) > 0xffff else 1
        if total > units: raise ValueError('光标位于字符中间')
    if total == units: return len(text)
    raise ValueError('无效光标位置')


def _units(text):
    return len(text.encode('utf-16-le')) // 2


def _word(text, cursor, windows):
    # Scan the entire draft so a later operator or unfinished quote cannot
    # turn a suggestion into part of an ambiguous shell expression.
    start = 0; spans = []; quote = None; escaped = False; decoded = ''
    for index, char in enumerate(text):
        if escaped:
            decoded += char; escaped = False; continue
        if windows:
            if char == '^':
                raise ValueError('此命令包含暂不支持的 shell 转义')
            if char == '"': quote = None if quote else '"'; continue
            if char in '%!': raise ValueError('此命令包含暂不支持的 shell 展开或操作符')
            if quote is None and char in '&|<>()': raise ValueError('此命令包含暂不支持的 shell 操作符')
        else:
            if char == '\\' and quote != "'": escaped = True; continue
            if char in "'\"":
                if quote == char: quote = None; continue
                if quote is None: quote = char; continue
            if quote != "'" and char in '$`*?[]{};|&<>()':
                raise ValueError('此命令包含暂不支持的 shell 展开或操作符')
        if char.isspace() and quote is None:
            if index > start: spans.append((start, index))
            start = index + 1; decoded = ''
    if escaped: raise ValueError('路径末尾的转义尚未完成')
    if start < len(text): spans.append((start, len(text)))
    selected = next(((begin, end) for begin, end in spans if begin <= cursor <= end), None)
    if selected is None:
        if cursor < len(text) and not text[cursor].isspace():
            raise ValueError('请将光标放在路径参数内')
        return cursor, cursor, ''
    begin, end = selected
    # Decode the selected token only through the cursor. The complete token
    # is replaced, so a suffix after the cursor cannot silently change it.
    raw = text[begin:cursor]; value = ''; quote = None; escaped = False
    for char in raw:
        if escaped: value += char; escaped = False; continue
        if windows:
            if char == '"': quote = None if quote else '"'; continue
        else:
            if char == '\\' and quote != "'": escaped = True; continue
            if char in "'\"":
                if quote == char: quote = None; continue
                if quote is None: quote = char; continue
        value += char
    if escaped: raise ValueError('路径末尾的转义尚未完成')
    return begin, end, value


def complete_path(session, text, selection_start):
    if not isinstance(text, str) or len(text) > MAX_DRAFT or '\x00' in text or '\n' in text or '\r' in text:
        raise ValueError('仅支持最多 4096 字符的单行终端草稿')
    cursor = _offset(text, selection_start)
    if session.done.is_set(): raise ValueError('终端已关闭，请重新打开')
    cwd = session.current_cwd()
    windows = ntpath.basename(session.shell).lower() in ('cmd', 'cmd.exe')
    start, end, typed = _word(text, cursor, windows)
    path = ntpath if windows else os.path
    separator = '\\' if windows else '/'
    head, prefix = path.split(typed)
    expand_tilde = not windows and text[start:start + 1] not in ("'", '"')
    if expand_tilde and typed == '~': head, prefix = '~/', ''
    if windows:
        if typed.startswith('~') or (head and not path.isabs(head) and path.splitdrive(head)[0]):
            raise ValueError('暂不支持此 Windows 路径形式')
        directory = path.join(cwd, head) if head else cwd
    else:
        directory = os.path.expanduser(head) if expand_tilde and head.startswith('~') else head
        directory = path.join(cwd, directory) if not path.isabs(directory) else directory
    if len(directory) > 4096: raise ValueError('路径过长')
    candidates = []; scanned = 0; truncated = False
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                scanned += 1
                if scanned > MAX_SCAN: truncated = True; break
                if not (entry.name.casefold().startswith(prefix.casefold()) if windows else entry.name.startswith(prefix)): continue
                if windows and any(char in entry.name for char in '%!^"'): continue
                is_dir = entry.is_dir()
                raw = path.join(head, entry.name) + (separator if is_dir else '')
                if windows:
                    inserted = raw if re.fullmatch(r'[A-Za-z0-9_./\\:\-]+', raw) else '"' + raw + '"'
                else:
                    inserted = shlex.quote(os.path.expanduser(raw) if expand_tilde else raw)
                candidates.append({'label': entry.name + (separator if is_dir else ''), 'insertText': inserted,
                                   'isDirectory': is_dir})
                if len(candidates) > MAX_CANDIDATES: truncated = True; candidates.pop(); break
    except (OSError, ValueError): raise ValueError('无法读取当前路径，请检查目录是否仍可访问') from None
    candidates.sort(key=lambda item: (not item['isDirectory'], item['label'].casefold()))
    return {'cwd': cwd, 'replaceStart': _units(text[:start]), 'replaceEnd': _units(text[:end]),
            'candidates': candidates, 'truncated': truncated}
