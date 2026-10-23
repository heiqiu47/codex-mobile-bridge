// Capability-gated prototype over an existing LocalSessions API reference.
// Never opens a session, obtains a new owner, or calls getTranscript as fallback.
export async function historyPage(api, scope, sessionId, {limit = 20, cursor = null} = {}) {
  if (!scope || !sessionId || !Number.isInteger(limit) || limit < 1 || limit > 100)
    throw Error('Source identity and bounded page size required');
  if (cursor && (cursor.scope !== scope || cursor.sessionId !== sessionId))
    throw Error('History identity changed');
  if (typeof api?.getTranscriptTail !== 'function' || typeof api?.getTranscriptPage !== 'function')
    return {supported: false, reason: 'native-paging-unavailable'};
  const page = cursor
    ? await api.getTranscriptPage(sessionId, cursor.beforeUuid, limit)
    : await api.getTranscriptTail(sessionId, limit);
  if (!Array.isArray(page?.messages) || typeof page.hasMore !== 'boolean')
    throw Error('Unexpected native history response');
  if (cursor && page.found !== true) throw Error('Native history anchor is stale');
  const boundary = page.messages[0]?.uuid;
  if (page.hasMore && (typeof boundary !== 'string' || !boundary || boundary === cursor?.beforeUuid))
    throw Error('Native history cursor failed to advance');
  return {supported: true, messages: page.messages, nativeSource: page.source ?? 'tail',
    // A small reply does not prove bounded disk/CPU work inside Claude.
    sourceWorkBounded: false, authoritativeState: false,
    cursor: page.hasMore ? {scope, sessionId, beforeUuid: boundary} : null};
}
