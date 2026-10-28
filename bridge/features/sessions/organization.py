"""Native sidebar metadata only: never load a thread or change its execution settings."""
import uuid
import ntpath


class OrganizationNotSent(ValueError):
    """Validation failed before any native metadata write."""


def validate_change(snapshot, change):
    if not isinstance(change, dict) or set(change) != {'kind', 'targetId', 'expectedId'}:
        raise OrganizationNotSent('会话分类设置无效')
    kind, target, expected = change['kind'], change['targetId'], change['expectedId']
    if kind not in ('project', 'section') or any(value is not None and
            (not isinstance(value, str) or not value or len(value) > 200) for value in (target, expected)):
        raise OrganizationNotSent('会话分类设置无效')
    candidates = snapshot['projects' if kind == 'project' else 'sections']
    if target is not None and target not in {row['id'] for row in candidates}:
        raise OrganizationNotSent('目标项目或分区已移除，请刷新后重试')
    current = snapshot[kind + 'Id']
    if current != target and current != expected:
        raise OrganizationNotSent('会话分类已在其他客户端更新，请刷新后重试')


def _same_cwd(left, right):
    if left == right:
        return True
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    # Native Windows storage uses extended paths; RPC removes that prefix.
    windows = any(value.startswith('\\\\') or len(value) > 2 and value[1] == ':' and value[2] in '/\\'
                  for value in (left, right))
    if not windows:
        return False
    def normalized(value):
        value = value.replace('\\', '/')
        if value[:8].casefold() in ('//?/unc/', '//./unc/'):
            value = '//' + value[8:]
        elif value.startswith(('//?/', '//./')):
            value = value[4:]
        return ntpath.normcase(ntpath.normpath(value))
    return normalized(left) == normalized(right)


def _pages(request, method):
    rows, seen, cursor = [], set(), None
    for _ in range(100):
        page = request(method, {'cursor': cursor, 'limit': 100})
        rows.extend(page['data'])
        cursor = page.get('nextCursor')
        if cursor is None:
            return rows
        if not isinstance(cursor, str) or cursor in seen:
            raise ValueError('原生侧边栏列表已变化，请刷新后重试')
        seen.add(cursor)
    raise ValueError('原生侧边栏列表过长，请在电脑端整理后重试')


def organization(request, identifier, change=None, *, expected_cwd=None):
    uuid.UUID(identifier)
    before = request('thread/read', {'threadId': identifier, 'includeTurns': False})['thread']
    if before.get('id') != identifier or expected_cwd is not None and not _same_cwd(before.get('cwd'), expected_cwd):
        raise OrganizationNotSent('原会话工作目录已变化，请刷新后重试')
    projects = _pages(request, 'project/list')
    sections = _pages(request, 'threadSection/list')
    if change is not None:
        validate_change({'projects': projects, 'sections': sections, 'projectId': before.get('projectId'),
                         'sectionId': (before.get('section') or {}).get('id')}, change)
        kind, target, expected = change['kind'], change['targetId'], change['expectedId']
        current = before.get('projectId') if kind == 'project' else (before.get('section') or {}).get('id')
        if current != target:
            fresh = request('thread/read', {'threadId': identifier, 'includeTurns': False})['thread']
            latest = fresh.get('projectId') if kind == 'project' else (fresh.get('section') or {}).get('id')
            if latest != current or any(fresh.get(key) != before.get(key) for key in ('id', 'cwd', 'modelProvider')):
                raise OrganizationNotSent('会话分类已在其他客户端更新，请刷新后重试')
            if kind == 'project':
                request('thread/metadata/update', {'threadId': identifier, 'projectId': target or ''})
            else:
                request('thread/section/move', {'threadId': identifier, 'sectionId': target})
        after = request('thread/read', {'threadId': identifier, 'includeTurns': False})['thread']
        actual = after.get('projectId') if kind == 'project' else (after.get('section') or {}).get('id')
        if actual != target or any(after.get(key) != before.get(key) for key in ('id', 'cwd', 'modelProvider')):
            raise ValueError('原生分类结果待核对，请刷新会话列表')
        before = after
    return {'id': identifier, 'projectId': before.get('projectId'),
            'identity': {key: before.get(key) for key in ('id', 'cwd', 'modelProvider')},
            'sectionId': (before.get('section') or {}).get('id'),
            'projects': [{'id': row['id'], 'name': row['name']} for row in projects],
            'sections': [{'id': row['id'], 'name': row['name']} for row in sections],
            'status': 'confirmed'}
