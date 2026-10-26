'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/shell/app.js'),'utf8');
const code=source.slice(source.indexOf('function renderList(){'),source.indexOf('async function loadList('));
function fixture(){
 const nodes=new Map(),timers=new Map(),requests=[],dialogs=[],copies=[];let timer=0;
 const node=(tag='',cls='',textContent='')=>({tag,cls,textContent,dataset:{},children:[],events:{},classList:{add(){}},scrollTop:0,isConnected:true,append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},addEventListener(name,run){this.events[name]=run;},setAttribute(){},showModal(){this.open=true;},close(){this.open=false;this.events.close?.();},remove(){this.isConnected=false;}});
 const $=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};$('list-mode').value='recent';
 const context=vm.createContext({$,el:node,window:{BridgeSessionLinks:{text:identity=>'codex://threads/'+identity.id}},document:{body:{append:box=>dialogs.push(box)}},
   BridgeClipboard:{copyWithFeedback:async(get,item)=>{if(item.disabled)return;copies.push(get());}},BridgeI18n:{locale:()=> 'en-US'},t:s=>s,localStorage:{getItem(){return null;},setItem(){}},
   listRows:[],currentId:null,currentHost:'local',listHasMore:false,listRenderStamp:'',listComplete:true,listReadFinished:true,availableSources:[],
   renderActivity(){},sessionAccess:v=>v||{},sourceLabel:()=> 'APP',dateText:()=>'',toast:assert.fail,openChat:async()=>{},
   setTimeout:fn=>{timers.set(++timer,fn);return timer;},clearTimeout:id=>timers.delete(id),uuid:()=> 'request-id',
   api:async(url,body)=>{requests.push({url,body});return {status:'confirmed'};},sessionUrl:(id,action,host)=>`/${host}/${id}/${action}`,loadList:async()=>{}});
 vm.runInContext(code,context);
 const row=(id,recency,pinned=false)=>({id,host:'local',title:id,projectKey:'p',projectName:'Project',hostLabel:'Local',recency,bridgePinned:pinned,access:{}});
 return {context,$,node,row,requests,dialogs,copies,fireTimers(){const work=[...timers.values()];timers.clear();work.forEach(fn=>fn());}};
}
test('recent sections sort pinned and unpinned independently; project grouping ignores pins',()=>{
 const ui=fixture();ui.context.listRows=[ui.row('recent',30),ui.row('old-pin',1,true),ui.row('new-pin',20,true),ui.row('older',2)];
 ui.context.renderList();const rows=ui.$('sessions').children;
 assert.deepEqual(rows.map(n=>n.dataset.id||n.textContent),['置顶聊天','new-pin','old-pin','最近聊天','recent','older']);
 ui.$('list-mode').value='project';ui.context.renderList();
 assert.deepEqual(ui.$('sessions').children[0].children.slice(1).map(n=>n.dataset.id),['recent','new-pin','older','old-pin']);
});
test('right-click exposes pin, copy and native archive with original host',async()=>{
 const ui=fixture(),chat=ui.row('a',1);chat.host='remote';ui.context.listRows=[chat];ui.context.renderList();
 ui.$('sessions').children[0].events.contextmenu({preventDefault(){}});
 const box=ui.dialogs[0];assert.deepEqual(box.children.slice(1).map(n=>n.textContent),['置顶','复制深度链接','归档聊天']);
 await box.children[1].onclick();assert.equal(ui.requests[0].url,'/remote/a/pin');assert.equal(ui.requests[0].body.pinned,true);
 await box.children[2].onclick();assert.deepEqual(ui.copies,['codex://threads/a']);
 await box.children[3].onclick();assert.equal(ui.requests[1].url,'/remote/a/archive');assert.equal(ui.requests[1].body.archived,true);
});
test('long press suppresses navigation and movement cancels; archived menu restores',async()=>{
 const ui=fixture(),chat=ui.row('a',1,true);chat.archived=true;
 const button=ui.node('button');ui.context.bindSessionMenu(button,chat);
 button.events.pointerdown({pointerType:'touch',button:0,clientX:1,clientY:1});button.events.pointermove({clientX:30,clientY:1});ui.fireTimers();assert.equal(ui.dialogs.length,0);
 button.events.pointerdown({pointerType:'touch',button:0,clientX:1,clientY:1});ui.fireTimers();assert.equal(ui.dialogs.length,1);
 let stopped=false;button.events.click({preventDefault(){},stopImmediatePropagation(){stopped=true;}});assert.equal(stopped,true);
 const box=ui.dialogs[0];assert.equal(box.children[1].textContent,'取消置顶');assert.equal(box.children[3].textContent,'取消归档');await box.children[3].onclick();assert.equal(ui.requests[0].body.archived,false);
});
