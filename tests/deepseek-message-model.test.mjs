import test from 'node:test';
import assert from 'node:assert/strict';
import {historyRecords} from '../bridge/clients/deepseek/host.mjs';
const row=(seq,type,data={})=>({event:{seq,type,data}});
const header=(seq,model,effort)=>row(seq,'request/header',{header:{config:{provider:'deepseek',model,reasoningEffort:effort,apiKey:'PRIVATE'},system:'PRIVATE'},reason:'change'});
const reply=seq=>row(seq,'assistant/message',{message:{source:{provider:'deepseek',model:'chat'},content:[]}});
test('model and effort follow historical requests, excluding headers and pending model choices',async()=>{
 const rows=await historyRecords({},[header(0,'chat','high'),reply(1),row(2,'model/selection',{provider:'deepseek',model:'next',reasoningEffort:'low'}),reply(3),header(4,'next','low'),reply(5),header(6,'next',undefined),reply(7)]);
 assert.deepEqual(rows.map(r=>r.event.data.modelSelection),[{provider:'deepseek',model:'chat',reasoningEffort:'high'},{provider:'deepseek',model:'chat',reasoningEffort:'high'},{provider:'deepseek',model:'next',reasoningEffort:'low'},{provider:'deepseek',model:'next'}]);
 assert.ok(!JSON.stringify(rows).includes('PRIVATE'));assert.equal(rows.length,4);
});
test('a page beginning after the header uses a disposed cold observation and never later settings',async()=>{
 let disposed=0,observed=0;
 const ctx={sessionId:'fixture',get:name=>{assert.equal(name,'sessionQuery');return {observeSession:async(id,options)=>{observed++;assert.equal(id,'fixture');assert.equal(options.projectionMode,'none');return {events:[header(0,'chat','high'),header(20,'later','low')].map(r=>r.event),[Symbol.dispose]:()=>disposed++};}};}};
 const rows=await historyRecords(ctx,[row(7,'turn/start'),reply(8)]);
 assert.equal(rows[1].event.data.modelSelection.reasoningEffort,'high');assert.equal(disposed,1);assert.equal(observed,1);
 await historyRecords(ctx,[header(7,'chat','low'),reply(8)]);assert.equal(observed,1);
});
test('older hosts without the cold query retain messages without inventing effort',async()=>{
 const source=[reply(8)];assert.deepEqual(await historyRecords({},source),source);
});
