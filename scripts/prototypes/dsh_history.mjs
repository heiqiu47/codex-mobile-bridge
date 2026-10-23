// Prototype only: one native page per read; does not install or reload a plugin.
export async function historyPage(controller, scope, sessionId, {limit = 20, cursor = null} = {}) {
  if (!scope || !sessionId || !Number.isInteger(limit) || limit < 1 || limit > 100)
    throw Error('Source identity and bounded page size required');
  if (cursor && (cursor.scope !== scope || cursor.sessionId !== sessionId))
    throw Error('History identity changed');
  const signal = new AbortController().signal;
  const projection = cursor ? null : await controller.projections({sessionId}, signal);
  const throughSeq = cursor?.throughSeq ?? projection?.asOfSeq;
  if (!Number.isSafeInteger(throughSeq) || throughSeq < 0) throw Error('Missing history revision');
  const page = await controller.page({address: {kind: 'session', sessionId}, throughSeq,
    ...(cursor ? {beforeSeq: cursor.beforeSeq} : {}), maxMessages: limit}, signal);
  const records = page.records || [];
  const boundary = records[0]?.event?.seq;
  if (page.hasMore && (!Number.isSafeInteger(boundary) || cursor && boundary >= cursor.beforeSeq))
    throw Error('History cursor failed to advance');
  return {records, cursor: page.hasMore ? {scope, sessionId, throughSeq, beforeSeq: boundary} : null,
    readOnly: true, authoritativeState: false};
}
