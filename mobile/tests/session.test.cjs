'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../android/assets/mobile-session.js'),'utf8');
function fixture({authenticated=false,frame=false}={}){
 const events={},calls=[],window={prompt:(...args)=>calls.push(args)};window.top=frame?{}:window;
  const document={visibilityState:'visible',addEventListener:(name,fn)=>events[name]=fn,getElementById:()=>({hidden:!authenticated})};
  const context={window,document};vm.runInNewContext(source,context);
  return {events,calls,document,inject:()=>vm.runInNewContext(source,context)};
}
test('Android persists session immediately after login without exposing credentials',()=>{
 const f=fixture();assert.equal(f.calls.length,0);f.events['bridge-authenticated']();
 assert.deepEqual(f.calls,[['codexbridge-session:__BRIDGE_CLIPBOARD_TOKEN__','']]);
});
test('an already authenticated page persists its renewed session; embedded frames cannot',()=>{
 assert.equal(fixture({authenticated:true}).calls.length,1);const f=fixture({frame:true});assert.equal(f.calls.length,0);assert.equal(f.events['bridge-authenticated'],undefined);
});
test('successful logout asks the native shell to clear only its binding',()=>{
 const f=fixture();f.events['bridge-logged-out']();
 assert.deepEqual(f.calls,[['codexbridge-logout:__BRIDGE_CLIPBOARD_TOKEN__','']]);
});
test('an authenticated page losing authorization asks for one guarded native recovery',()=>{
 const f=fixture({authenticated:true});f.events['bridge-auth-lost']();
 assert.deepEqual(f.calls.at(-1),['codexbridge-auth-lost:__BRIDGE_CLIPBOARD_TOKEN__','']);
});

test('visible chat signals carry only its routing identity and register once',()=>{
 const f=fixture();f.inject();f.events['bridge-chat-visible']({detail:{threadId:'chat',host:'desktop:claude',text:'private'}});
 assert.deepEqual(f.calls,[['codexbridge-chat-visible:__BRIDGE_CLIPBOARD_TOKEN__','{"threadId":"chat","host":"desktop:claude"}']]);
 for(const detail of [{},{threadId:'',host:'local'},{threadId:'x'.repeat(513),host:'local'},{threadId:'chat',host:null},{threadId:'chat',host:'x'.repeat(257)}])f.events['bridge-chat-visible']({detail});
 f.document.visibilityState='hidden';f.events['bridge-chat-visible']({detail:{threadId:'chat',host:'local'}});
 assert.equal(f.calls.length,1);
});

test('only the currently displayed and loaded chat requests notification cleanup',()=>{
 const appSource=fs.readFileSync(path.join(__dirname,'../../web/shell/app.js'),'utf8');
 const report=appSource.slice(appSource.indexOf('function reportVisibleChat(){'),appSource.indexOf('\ndesktopSessions.onDetailReady='));
 const events=[],app={hidden:false},document={hidden:false,dispatchEvent:event=>events.push(event.detail)};
 const context={document,$:()=>app,isCodexClient:value=>value==='codex',clientNavigation:{provider:'codex'},currentId:'chat-A',currentHost:'local',chatTimeline:{cached:false,meta:{loadingHistory:false}},visibleChat:()=>true,desktopSessions:{sid:'chat-B',provider:'claude',state:{},visibleActivity:()=>true},CustomEvent:class{constructor(type,options){this.detail=options.detail;}}};
 vm.createContext(context);vm.runInContext(report,context);
 const run=()=>vm.runInContext('reportVisibleChat()',context);
 run();assert.deepEqual(JSON.parse(JSON.stringify(events.pop())),{threadId:'chat-A',host:'local'});
 for(const [target,key,value] of [[document,'hidden',true],[app,'hidden',true],[context.chatTimeline,'cached',true],[context.chatTimeline.meta,'loadingHistory',true],[context,'visibleChat',()=>false]]){
  const prior=target[key];target[key]=value;run();target[key]=prior;assert.equal(events.length,0);
 }
 context.clientNavigation.provider='claude';run();assert.deepEqual(JSON.parse(JSON.stringify(events.pop())),{threadId:'chat-B',host:'desktop:claude'});
 context.desktopSessions.state=null;run();assert.equal(events.length,0);
 context.desktopSessions.state={};context.desktopSessions.visibleActivity=()=>false;run();assert.equal(events.length,0);
});
