'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/features/chat/list-sync.js'),'utf8');
const id='11111111-1111-4111-8111-111111111111',identity={provider:'codex',host:'local',id};
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function fixture({storage=new Map(),offline=false}={}){
 const calls=[],events={},timers=new Map();let changed=0,nextTimer=0;
 const store={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)};
 const context=vm.createContext({document:{hidden:false,addEventListener:(name,fn)=>events[name]=fn},window:{addEventListener:(name,fn)=>events[name]=fn},navigator:{onLine:!offline},localStorage:store,setTimeout:(fn,delay)=>{timers.set(++nextTimer,{fn,delay});return nextTimer;},clearTimeout:id=>timers.delete(id)});
 vm.runInContext(source,context);const Class=vm.runInContext('LocalSessionPins',context);
 const pins=new Class({storage:store,newId:()=> '22222222-2222-4222-8222-222222222222',onChange:()=>changed++,send:(target,body,token)=>new Promise((resolve,reject)=>calls.push({target,body,token,resolve,reject}))});
 const ack=call=>call.resolve({id:call.target.id,bridgePinned:call.body.pinned,clientId:call.body.clientId,revision:call.body.revision});
 return {pins,calls,ack,storage,events,timers,context,changed:()=>changed,online:()=>{context.navigator.onLine=true;events.online();}};
}
test('offline pin paints synchronously and survives reload before any gateway success',async()=>{
 const ui=fixture({offline:true});ui.pins.bind('verified-gateway');ui.pins.set(identity,true);
 assert.equal(ui.pins.value(identity,false),true);assert.equal(ui.pins.pending(identity),true);assert.equal(ui.calls.length,0);
 const reloaded=fixture({storage:ui.storage,offline:true});reloaded.pins.bind('verified-gateway');assert.equal(reloaded.pins.value(identity,false),true);assert.equal(reloaded.pins.pending(identity),true);
 reloaded.online();await settle();assert.equal(reloaded.calls.length,1);reloaded.ack(reloaded.calls[0]);await settle();assert.equal(reloaded.pins.pending(identity),false);
});
test('rapid intent changes serialize writes and stale list reads cannot undo the latest pin',async()=>{
 const ui=fixture();ui.pins.bind('gateway');ui.pins.set(identity,true);await settle();assert.equal(ui.calls.length,1);
 ui.pins.set(identity,false);const staleRead=ui.pins.capture();assert.equal(ui.pins.value(identity,true),false);assert.equal(ui.calls.length,1);
 ui.ack(ui.calls[0]);await settle();assert.equal(ui.calls.length,2);assert.equal(ui.calls[1].body.pinned,false);assert.ok(ui.calls[1].body.revision>ui.calls[0].body.revision);
 ui.ack(ui.calls[1]);await settle();assert.equal(ui.pins.pending(identity),false);
 ui.pins.observe(identity,true,staleRead);assert.equal(ui.pins.value(identity,true),false);
 ui.pins.observe(identity,false,ui.pins.capture());assert.equal(ui.pins.value(identity,true),true,'a later authoritative read may reflect another device once local intent is synced');
});
test('network failures remain pending and explicit latest intent cancels retry backoff',async()=>{
 const ui=fixture();ui.pins.bind('gateway');ui.pins.set(identity,true);await settle();ui.calls[0].reject(Object.assign(Error('offline'),{status:503}));await settle();
 assert.equal(ui.pins.pending(identity),true);assert.equal([...ui.timers.values()][0].delay,5000);
 ui.pins.set(identity,false);await settle();assert.equal(ui.timers.size,0);assert.equal(ui.calls.length,2);assert.equal(ui.calls[1].body.pinned,false);
});
test('logout and gateway changes isolate pending state and late acknowledgements',async()=>{
 const ui=fixture();ui.pins.bind('gatewayA');ui.pins.set(identity,true);await settle();const old=ui.calls[0];
 ui.pins.bind('gatewayB');assert.equal(ui.pins.value(identity,false),false);ui.pins.set(identity,false);await settle();ui.ack(old);await settle();assert.equal(ui.pins.pending(identity),true);
 ui.pins.suspend();assert.equal(ui.pins.current(old.token),false);ui.pins.bind('gatewayA');assert.equal(ui.pins.value(identity,false),true);assert.equal(ui.pins.pending(identity),true);
});
test('provider and execution host are separate; selected model account is not a presentation scope',()=>{
 const ui=fixture({offline:true});ui.pins.bind('gateway');ui.pins.set({...identity,account:'one'},true);
 assert.equal(ui.pins.value({...identity,account:'two'},false),true);
 assert.equal(ui.pins.value({...identity,host:'ssh:other'},false),false);assert.equal(ui.pins.value({...identity,provider:'claude'},false),false);
 ui.pins.set({provider:'deepseek',id:'session-native',host:'local'},true);assert.equal(ui.pins.value({provider:'deepseek',id:'session-native',host:'local'},false),true);
});
test('stale server revision is advanced without losing the latest pending intent',async()=>{
 const ui=fixture();ui.pins.bind('gateway');ui.pins.set(identity,true);await settle();const first=ui.calls[0];first.resolve({id,clientId:first.body.clientId,revision:8,bridgePinned:false});await settle();
 assert.equal(ui.calls.length,2);assert.equal(ui.calls[1].body.revision,9);assert.equal(ui.pins.value(identity,false),true);assert.equal(ui.pins.pending(identity),true);
});
test('late unauthorized pin response cannot log out a different authenticated scope',async()=>{
 const app=fs.readFileSync(path.join(__dirname,'../web/shell/app.js'),'utf8'),start=app.indexOf('async function api('),end=app.indexOf('\nconst workbench=',start);let lost=0;
 const context=vm.createContext({csrf:'new-token',fetch:async()=>({ok:false,status:401,json:async()=>({error:'expired'})}),hostUrl:value=>value,t:value=>value,authLost:()=>lost++});vm.runInContext(app.slice(start,end),context);
 await assert.rejects(vm.runInContext("api('/pin',{pinned:true},undefined,()=>false)",context));assert.equal(lost,0);
 await assert.rejects(vm.runInContext("api('/pin',{pinned:true},undefined,()=>true)",context));assert.equal(lost,1);
});

test('logout before dispatch prevents the queued write from using the next authentication',async()=>{
 const ui=fixture();ui.pins.bind('gateway');ui.pins.set(identity,true);ui.pins.suspend();await settle();assert.equal(ui.calls.length,0);
 ui.pins.bind('gateway');await settle();assert.equal(ui.calls.length,1);assert.equal(ui.calls[0].body.pinned,true);
});

test('a stalled gateway pin write is aborted so later intent can retry safely',async()=>{
 const app=fs.readFileSync(path.join(__dirname,'../web/shell/app.js'),'utf8'),start=app.indexOf('async function sendSessionPin('),end=app.indexOf('\nconst sessionPins=',start);let timeout,cleared=false,signal;
 const context=vm.createContext({AbortController,setTimeout:(run,ms)=>{assert.equal(ms,15000);timeout=run;return 1;},clearTimeout:()=>cleared=true,sessionPins:{current:()=>true},sessionUrl:()=>'/pin',api:(_path,_body,received)=>{signal=received;return new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('timeout'))));}});
 vm.runInContext(app.slice(start,end),context);const result=context.sendSessionPin(identity,{pinned:true},{});assert.equal(signal.aborted,false);timeout();await assert.rejects(result,/timeout/);assert.equal(cleared,true);
});

test('failed durable save does not paint success and a later retry persists the device identity',()=>{
 const ui=fixture({offline:true});ui.pins.bind('gateway');const write=ui.pins.storage.setItem;let fail=true;
 ui.pins.storage.setItem=(key,value)=>{if(fail){fail=false;throw Error('quota');}write(key,value);};
 assert.throws(()=>ui.pins.set(identity,true),/无法保存/);assert.equal(ui.pins.value(identity,false),false);assert.equal(ui.pins.pending(identity),false);
 ui.pins.set(identity,true);assert.equal(ui.storage.get('bridge-session-pins-client'),ui.pins.clientId);
 const reloaded=fixture({storage:ui.storage,offline:true});reloaded.pins.bind('gateway');assert.equal(reloaded.pins.pending(identity),true);
});
