import test from 'node:test';
import assert from 'node:assert/strict';
import {historyPage as dshPage} from '../scripts/prototypes/dsh_history.mjs';
import {historyPage as claudePage} from '../scripts/prototypes/claude_desktop_history.mjs';

test('DSH reads one source page per explicit request, freezes revision and isolates cursors', async () => {
  const calls = [];
  const controller = {
    projections: async ({sessionId}) => {calls.push(['projection', sessionId]); return {asOfSeq: 10000};},
    page: async args => {
      calls.push(['page', args]);
      const end = args.beforeSeq ?? args.throughSeq + 1;
      return {records: Array.from({length: 20}, (_, i) => ({event: {seq: end - 20 + i}})), hasMore: true};
    },
  };
  const a = await dshPage(controller, 'computer/account', 'thread');
  assert.equal(calls.length, 2);
  const b = await dshPage(controller, 'computer/account', 'thread', {cursor: a.cursor});
  assert.equal(calls.length, 3);
  assert.equal(calls[2][1].throughSeq, 10000);
  assert.ok(b.records.at(-1).event.seq < a.records[0].event.seq);
  await assert.rejects(dshPage(controller, 'other-account', 'thread', {cursor: a.cursor}), /identity/);
  assert.equal(calls.length, 3);
});

test('DSH nonadvancing cursor fails instead of recursively retrieving full history', async () => {
  let count = 0;
  const controller = {page: async () => {count++; return {records: [{event: {seq: 10}}], hasMore: true};}};
  await assert.rejects(dshPage(controller, 'a', 't', {cursor: {scope: 'a', sessionId: 't', throughSeq: 20, beforeSeq: 10}}), /advance/);
  assert.equal(count, 1);
});

test('Claude uses native tail then UUID page; reports native full fallback honestly', async () => {
  const calls = [];
  const api = {
    getTranscriptTail: async (id, limit) => {calls.push(['tail', id, limit]); return {messages: [{uuid: 'm20'}], hasMore: true};},
    getTranscriptPage: async (...args) => {calls.push(['page', ...args]); return {messages: [{uuid: 'm19'}], hasMore: false, found: true, source: 'full'};},
    getTranscript: () => {throw Error('Full fallback forbidden');},
  };
  const first = await claudePage(api, 'computer/account', 'thread');
  const second = await claudePage(api, 'computer/account', 'thread', {cursor: first.cursor});
  assert.deepEqual(calls, [['tail', 'thread', 20], ['page', 'thread', 'm20', 20]]);
  assert.equal(second.nativeSource, 'full');
  assert.equal(second.sourceWorkBounded, false);
  await assert.rejects(claudePage(api, 'other', 'thread', {cursor: first.cursor}), /identity/);
});

test('Claude unsupported API and stale anchors never activate or fetch full transcript', async () => {
  const missing = await claudePage({getTranscript: () => {throw Error('unexpected');}}, 'a', 't');
  assert.equal(missing.supported, false);
  const api = {getTranscriptTail: async () => {}, getTranscriptPage: async () => ({messages: [], hasMore: false, found: false})};
  await assert.rejects(claudePage(api, 'a', 't', {cursor: {scope: 'a', sessionId: 't', beforeUuid: 'm'}}), /stale/);
});
