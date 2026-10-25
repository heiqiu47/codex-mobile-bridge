"""Ledger-only queue projection and exact-version mutations; callers hold dispatch locks."""
import copy
import hashlib
import json
import uuid


def snapshot(rows, receipt_ids=(), hidden=(), scope=None):
    if len(receipt_ids) > 16:
        raise ValueError('最多查询 16 条消息')
    for identifier in receipt_ids:
        uuid.UUID(identifier)
    indexed = dict(rows)
    def receipt(identifier):
        entry = indexed.get(identifier, {})
        result = {'id': identifier, 'status': entry.get('status', 'notFound')}
        if entry.get('_editId'):
            result['editId'] = entry['_editId']
            result['edit'] = {'id': entry['_editId'], 'text': entry.get('text', ''), 'status': 'applied'}
        return result
    version = hashlib.sha256(json.dumps([scope, rows], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    def display(identifier, entry):
        return {'id': identifier, 'text': entry.get('text', ''), 'mode': entry.get('mode', 'queue'),
                'status': entry['status'], 'at': entry.get('at'),
                'attachments': entry.get('attachmentNames', []),
                **({'editId': entry['_editId']} if entry.get('_editId') else {})}
    visible = [(key, entry) for key, entry in rows if key not in hidden and not entry.get('goalActivation')]
    return {'version': version, 'queue': [display(k, v) for k, v in visible if v['status'] == 'queued'],
            'unknown': [display(k, v) for k, v in visible if v['status'] == 'unknown'],
            'receipts': [receipt(k) for k in receipt_ids],
            'capabilities': {'reorder': True, 'withdraw': True, 'edit': True}}


def mutate(rows, body, hidden=(), scope=None):
    current = snapshot(rows, hidden=hidden, scope=scope)
    if body.get('version') != current['version']:
        raise ValueError('消息队列已变化，请刷新后重试')
    action = body.get('action')
    allowed = {'action', 'version', 'ids'} if action == 'reorder' else {'action', 'version', 'id'}
    if action == 'edit':
        allowed |= {'text', 'editId'}
    if set(body) != allowed:
        raise ValueError('消息管理参数无效')
    visible = [row['id'] for row in current['queue']]
    result = {}
    if action == 'reorder':
        ids = body['ids']
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(ids) != len(visible) or set(ids) != set(visible):
            raise ValueError('消息队列已变化，请刷新后重试')
        entries = dict(rows)
        order = iter(ids)
        visible_ids = set(visible)
        reordered = []
        # Hidden goal activations keep their exact dispatch slots.
        for key, entry in rows:
            if key in visible_ids:
                key = next(order)
                entry = entries[key]
            reordered.append((key, entry))
        rows = reordered
    elif action in ('withdraw', 'ignore', 'edit'):
        identifier = body['id']; uuid.UUID(identifier)
        permitted = visible if action in ('withdraw', 'edit') else [r['id'] for r in current['unknown']]
        if identifier not in permitted:
            raise ValueError('此消息已离开队列或状态不可操作')
        rows = copy.deepcopy(rows)
        entry = dict(rows)[identifier]
        if action == 'edit':
            text = body['text']
            if not isinstance(text, str) or (not text.strip() and not entry.get('attachments')) or len(text) > 100000:
                raise ValueError('请输入 1–100000 字的消息')
            uuid.UUID(body['editId'])
            if entry.get('_editId') == body['editId']:
                raise ValueError('此编辑请求已处理，请刷新后核对')
            entry['text'] = text
            entry['_editId'] = body['editId']
        else:
            entry['status'] = 'cancelled' if action == 'withdraw' else 'ignored'
    else:
        raise ValueError('消息管理操作无效')
    revision = max((v.get('_managementRevision', 0) for _, v in rows), default=0) + 1
    rows = [(k, {**v, '_managementRevision': revision}) for k, v in rows]
    return rows, result
