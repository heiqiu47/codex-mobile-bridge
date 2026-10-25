'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(){
 const ctx=vm.createContext({window:{},AbortController,URLSearchParams,BridgeI18n:{t:s=>s}});vm.runInContext(fs.readFileSync('web/features/chat/timeline.js','utf8'),ctx);
 const type=vm.runInContext('ChatTimeline',ctx),pending=[],rows=new Map([['recent',{row:{key:'recent'}}]]);
 const ui=Object.assign(Object.create(type.prototype),{cached:false,busy:false,hasMore:true,abort:new AbortController(),generation:1,before:'a.recent',epoch:'a',retryCount:0,rows,
  historyStatus(){},capture(){return {key:'recent',offset:0};},following:false,active:()=>true,
  rowVisible:row=>row.role!=='activity',nearTop:()=>true,
  read(action,params){return new Promise(resolve=>pending.push({action,params,resolve}));},
  apply(page,reset,history){if(reset){this.generation++;this.rows.clear();this.epoch=page.epoch;}for(const row of page.rows)this.rows.set(row.key,{row});this.before=page.before;this.hasMore=page.hasMore;}
 });
 return {ui,pending};
}
const page=(epoch,key,role='assistant',more=true)=>({epoch,rows:[{key,role}],before:epoch+'.'+key,hasMore:more});
const tick=()=>new Promise(r=>setImmediate(r));
test('history intent survives a live reset while page is in flight',async()=>{
 const {ui,pending}=fixture(),done=ui.loadOlder(100);
 ui.apply(page('b','recent'),true);
 pending.shift().resolve(page('a','old'));
 await tick();assert.equal(pending.length,1,'retry against current cursor rather than dropping user scroll');
 assert.equal(pending[0].params.before,'b.recent');pending.shift().resolve(page('b','older', 'assistant',false));await done;
 assert.ok(ui.rows.has('older'));assert.equal(ui.busy,false);
});
test('an on-demand page containing only hidden activity continues to an older reply',async()=>{
 const {ui,pending}=fixture(),done=ui.loadOlder(100);
 pending.shift().resolve(page('a','tool','activity'));await tick();
 assert.equal(pending.length,1,'hidden rows cannot strand a reader at scroll top');
 pending.shift().resolve(page('a','reply','assistant',false));await done;assert.ok(ui.rows.has('reply'));
});
test('empty page with more history does not lose the current cursor or loop forever',async()=>{
 const {ui,pending}=fixture(),done=ui.loadOlder(100);
 pending.shift().resolve({epoch:'a',rows:[],before:null,hasMore:true});await done;
 assert.equal(ui.before,'a.recent');assert.equal(ui.retryCount,100);assert.equal(pending.length,0);
});
