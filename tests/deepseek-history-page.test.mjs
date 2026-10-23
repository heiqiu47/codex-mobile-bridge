import assert from 'node:assert/strict';
import test from 'node:test';
import {readHistoryPage} from '../bridge/clients/deepseek/host.mjs';

test('one native page per request and stable session revision', async () => {
  const calls=[];
  const controller={
    projections:async()=>({asOfSeq:80}),
    page:async request=>{
      calls.push(request);
      const end=request.beforeSeq??80;
      return {records:[{event:{seq:end-1,type:'user/message'}}],hasMore:end>1};
    }
  };
  const row={sessionId:'one'};
  const first=await readHistoryPage(controller,row,{historyLimit:12});
  assert.equal(calls.length,1);
  assert.equal(calls[0].maxMessages,12);
  assert.equal(calls[0].throughSeq,80);
  assert.equal(first.history.hasMore,true);
  await assert.rejects(readHistoryPage(controller,{sessionId:'other'},{historyBefore:first.history.before}),/历史游标无效/);
  const second=await readHistoryPage(controller,row,{historyBefore:first.history.before});
  assert.equal(calls.length,2);
  assert.equal(calls[1].throughSeq,80);
  assert.equal(calls[1].beforeSeq,79);
  assert.equal(second.rows[0].event.seq,78);
});

test('rejects nonadvancing native cursor', async () => {
  const controller={page:async()=>({records:[{event:{seq:12}}],hasMore:true})};
  const cursor=Buffer.from(JSON.stringify({sid:'one',seq:20,before:12})).toString('base64url');
  await assert.rejects(readHistoryPage(controller,{sessionId:'one'},{historyBefore:cursor}),/历史分页响应无效/);
});
