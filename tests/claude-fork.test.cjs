'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');
async function fixture({fork=true}={}){
 const config={cwd:'/fixture',transport:'cdp',token:'fixture',generation:'run',connectorRevision:10},calls=[];
 let rows=[{type:'assistant',uuid:'native-row-uuid',message:{id:'sdk-id',content:[{type:'text',text:'Answer'}]}}];
 const api={getAll:async()=>[],getTranscript:async()=>rows,...fork?{forkSession:async(...args)=>{calls.push(args);return {sessionId:args[1]};}}:{}};
 const window={'claude.web':{LocalSessions:api,LocalAgentModeSessions:{...api}}};
 await vm.runInNewContext(fs.readFileSync('bridge/clients/claude/connector.js','utf8').replace('__BRIDGE_CONFIG__',JSON.stringify(config)),{window,console,crypto:webcrypto,TextEncoder,Uint8Array,Date,setTimeout,clearTimeout});
 let seq=0;
 return {calls,status:()=>window.__claudeMobileBridge.status(),rows:value=>{rows=value;},invoke:(surface,messageId,id='11111111-1111-4111-8111-111111111111',replay=false)=>window.__claudeMobileBridge.invoke({...config,surface,method:'mobileFork',args:['parent',{id,messageId}],seq:replay?seq:++seq,expires:Date.now()/1000+30})};
}
test('Claude branches only using a fresh native assistant UUID and never replays an operation',async()=>{
 const ui=await fixture();
 assert.ok(ui.status().surfaces.code.includes('mobileFork'));assert.equal(ui.status().surfaces.cowork.includes('mobileFork'),false);
 assert.match((await ui.invoke('code','sdk-id')).error,/原消息已不可用/);assert.equal(ui.calls.length,0);
 assert.match((await ui.invoke('code','native-row-uuid:text:0')).error,/原消息已不可用/);assert.equal(ui.calls.length,0);
 const result=await ui.invoke('code','native-row-uuid');assert.equal(result.result.sessionId,'local_11111111-1111-4111-8111-111111111111');
 assert.deepEqual(ui.calls,[['parent','local_11111111-1111-4111-8111-111111111111','native-row-uuid']]);
 assert.match((await ui.invoke('code','native-row-uuid',undefined,true)).error,/不会重复执行/);assert.equal(ui.calls.length,1);
 ui.rows([{type:'assistant',uuid:'native-row-uuid',isSidechain:true}]);assert.match((await ui.invoke('code','native-row-uuid')).error,/原消息已不可用/);assert.equal(ui.calls.length,1);
 assert.match((await ui.invoke('cowork','native-row-uuid')).error,/不支持/);assert.equal(ui.calls.length,1);
});
test('an older Claude native API has no advertised or callable mobile fork',async()=>{
 const ui=await fixture({fork:false});assert.equal(ui.status().surfaces.code.includes('mobileFork'),false);assert.match((await ui.invoke('code','native-row-uuid')).error,/不支持/);assert.equal(ui.calls.length,0);
});
test('Claude connector preserves the complete native trust category suffix for the shared refusal classifier',async()=>{
 const error="Error invoking remote method '$eipc_message$_5c55def3-2e9e-44fa-af10-a18b58800855_$_claude.web_$_LocalSessions_$_start': WorkspaceTrustError: Workspace requires trust approval before starting a session. [ccdErrorCategory:trust_required]";
 const config={cwd:'/fixture',transport:'cdp',token:'fixture',generation:'run',connectorRevision:10};
 const window={'claude.web':{LocalSessions:{getAll:async()=>[],start:async()=>{throw Error(error);}}}};
 await vm.runInNewContext(fs.readFileSync('bridge/clients/claude/connector.js','utf8').replace('__BRIDGE_CONFIG__',JSON.stringify(config)),{window,console,crypto:webcrypto,TextEncoder,Uint8Array,Date,setTimeout,clearTimeout});
 const result=await window.__claudeMobileBridge.invoke({...config,surface:'code',method:'start',args:[{}],seq:1,expires:Date.now()/1000+30});
 assert.equal(result.error,error);
});
