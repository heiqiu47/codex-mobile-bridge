'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {ComposerDrafts}=require('../web/features/chat/composer-drafts.js');
const {MessageManagementBinding}=require('../web/features/chat/message-management-binding.js');
function storage(){const values=new Map();return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,String(value)),removeItem:key=>values.delete(key)};}
const baseScope={gateway:'gateway',provider:'codex',account:'account',host:'local',session:'chat'};
const body={text:'old message',mode:'send',skills:['skill'],attachments:['attachment']};
class Panel {constructor(options){this.options=options;}open(){return this.options.load(this.options.scope());}}
function fixture({request,local=storage(),temporary=storage()}={}){
 const drafts=new ComposerDrafts(local,{});let tail=Promise.resolve();drafts.coordinate=update=>{const task=tail.then(()=>update(true));tail=task.catch(()=>{});return task;};
 let target={scope:{...baseScope},drafts,temporary,temporaryKey:'pending:local|chat',url:'/messages?host=local',sendUrl:'/send?host=local',uuid:()=> 'editor-id'},changed=0;
 const calls=[],response={version:'v',queue:[],unknown:[],receipts:[],capabilities:{reorder:true,withdraw:true,edit:true},draftAccountIdentity:baseScope.account};
 const binding=new MessageManagementBinding({target:()=>target,Panel,request:async(url,value)=>{calls.push({url,value});return request?request(url,value):response;},notify(){},translate:value=>value,beforeOpen(){},onChanged(){changed++;}});
 return {binding,drafts,local,temporary,calls,response,scope:target.scope,get target(){return target;},set target(value){target=value;},get changed(){return changed;}};
}

test('background reconciliation is read-only, deduplicated and recovers an accepted v2.1.4 blocker',async()=>{
 let finish;const ui=fixture({request:()=>new Promise(resolve=>finish=resolve)});ui.drafts.begin(ui.scope,body,'legacy/id?');
 ui.drafts.save(ui.scope,{text:'current draft',quotes:[{text:'current quote'}],skills:['new-skill']});
 const before=JSON.stringify(ui.drafts.load(ui.scope)),first=ui.binding.reconcile(),second=ui.binding.reconcile();assert.equal(first,second);
 assert.equal(ui.calls.length,1);assert.equal(ui.calls[0].value,undefined);assert.match(ui.calls[0].url,/id=legacy%2Fid%3F/);assert.doesNotMatch(ui.calls[0].url,/enqueue|action=/);
 finish({...ui.response,receipts:[{id:'legacy/id?',status:'accepted'}]});await first;
 assert.equal(ui.drafts.pendingSend(ui.scope),null);assert.equal(JSON.stringify(ui.drafts.load(ui.scope)),before);
 assert.equal(ui.drafts.pending(ui.scope).id,'legacy/id?','An old page storage record is not deleted');
 assert.equal(await ui.binding.reconcile(),null);assert.equal(ui.calls.length,1,'No automatic replay or redundant read after recovery');
});

test('GET receipts recover old scoped session storage plus memory without dispatching queue work',async()=>{
 const ui=fixture(),record={id:'private',gateway:ui.scope.gateway,target:'local|chat',...body};
 ui.temporary.setItem(ui.target.temporaryKey,JSON.stringify(record));ui.drafts.temporaryPending.set(ui.target.temporaryKey,record);
 ui.response.receipts=[{id:'private',status:'accepted'}];await ui.binding.reconcile();
 assert.equal(ui.temporary.getItem(ui.target.temporaryKey),null);assert.equal(ui.drafts.temporaryPending.size,0);
 assert.equal(ui.calls.length,1);assert.equal(ui.calls[0].value,undefined);assert.doesNotMatch(ui.calls[0].url,/enqueue/);
});

for(const field of ['gateway','provider','account','host','session'])test(`a late receipt after ${field} change cannot consume pending state`,async()=>{
 let finish;const ui=fixture({request:()=>new Promise(resolve=>finish=resolve)}),old={...ui.scope};ui.drafts.begin(old,body,'old-id');
 const loading=ui.binding.load(old);ui.target={...ui.target,scope:{...old,[field]:'changed'}};
 finish({...ui.response,receipts:[{id:'old-id',status:'accepted'}]});await assert.rejects(loading,/切换/);
 assert.equal(ui.drafts.pendingSend(old).id,'old-id');assert.equal(ui.changed,0);assert.equal(ui.calls.length,1);assert.equal(ui.calls[0].value,undefined);
});

test('unverified server account and unknown/notFound/network responses keep the original blocker',async()=>{
 const ui=fixture();ui.drafts.begin(ui.scope,body,'id');ui.response.draftAccountIdentity='other';
 await assert.rejects(ui.binding.load(ui.scope),/账号状态尚未确认/);assert.equal(ui.drafts.pendingSend(ui.scope).id,'id');
 ui.response.draftAccountIdentity=ui.scope.account;
 for(const status of ['unknown','notFound']){ui.response.receipts=[{id:'id',status}];await ui.binding.load(ui.scope);assert.equal(ui.drafts.pendingSend(ui.scope).id,'id');}
 assert.ok(ui.calls.every(call=>call.value===undefined));
 const offline=fixture({request:()=>{throw Error('offline');}});offline.drafts.begin(offline.scope,body,'offline-id');
 assert.equal(await offline.binding.reconcile(),null);assert.equal(offline.drafts.pendingSend(offline.scope).id,'offline-id');assert.equal(offline.calls.length,1);
});

test('same-ID attempt added while receipt is in flight survives snapshot reconciliation',async()=>{
 let finish;const ui=fixture({request:()=>new Promise(resolve=>finish=resolve)});await ui.drafts.beginSend(ui.scope,body,'id','old-attempt');
 const loading=ui.binding.load(ui.scope);await ui.drafts.beginSend(ui.scope,body,'unused','new-attempt');
 finish({...ui.response,receipts:[{id:'id',status:'accepted'}]});await loading;
 assert.equal(ui.drafts.pendingSend(ui.scope).attempts.length,2);
});

test('fresh page reload restores the unknown queue editor and querying never re-enqueues it',async()=>{
 const local=storage(),temporary=storage(),first=fixture({local,temporary});
 const editor={id:'editor-id',sourceId:'withdrawn-id',status:'unknown',body:{text:'independent manager draft',mode:'queue',skills:['skill'],attachments:['attachment']}};
 first.drafts.save(first.scope,{text:'chat composer draft',quotes:[{text:'chat quote'}]});await first.binding.saveEditor(first.scope,editor);
 const fresh=fixture({local,temporary});assert.deepEqual(fresh.binding.loadEditor(fresh.scope),editor);
 fresh.response.receipts=[{id:'editor-id',status:'notFound'},{id:'withdrawn-id',status:'cancelled'}];await fresh.binding.load(fresh.scope);
 assert.deepEqual(fresh.binding.loadEditor(fresh.scope),editor);assert.equal(fresh.drafts.load(fresh.scope).text,'chat composer draft');
 assert.equal(fresh.calls.length,1);assert.equal(fresh.calls[0].value,undefined);assert.match(fresh.calls[0].url,/id=editor-id/);assert.match(fresh.calls[0].url,/id=withdrawn-id/);assert.doesNotMatch(fresh.calls[0].url,/enqueue|\/send/);
 await fresh.binding.saveEditor(fresh.scope,null);assert.equal(fresh.binding.loadEditor(fresh.scope),null);assert.equal(fresh.drafts.load(fresh.scope).quotes[0].text,'chat quote');
});

test('queue editor storage and explicit actions are scoped and do not borrow the composer draft',async()=>{
 const ui=fixture(),editor={id:'editor',status:'draft',body:{text:'manager only',skills:[],attachments:[]}};ui.drafts.save(ui.scope,{text:'composer only'});
 await ui.binding.saveEditor(ui.scope,editor);const original={...ui.scope};ui.target={...ui.target,scope:{...original,account:'new-account'}};
 assert.equal(ui.binding.loadEditor(ui.target.scope),null);await assert.rejects(ui.binding.saveEditor(original,null),/切换/);
 assert.equal(ui.drafts.load(original).text,'composer only');assert.equal(ui.calls.length,0);
 ui.target={...ui.target,scope:original};await ui.binding.panel.options.edit(original,{id:'editor',version:'v',text:'manager only',editId:'attempt'});
 assert.equal(ui.calls.length,1);assert.equal(ui.calls[0].url,'/messages?host=local');assert.equal(ui.calls[0].value.id,'editor');assert.equal(ui.calls[0].value.action,'edit');assert.equal(ui.calls[0].value.text,'manager only');
 assert.equal(ui.drafts.load(original).text,'composer only');
});

test('explicit local ignore makes no backend call and stale versions cannot remove a replacement',async()=>{
 const ui=fixture();ui.drafts.begin(ui.scope,body,'first');const record=ui.binding.records(ui.target)[0];
 ui.drafts.begin(ui.scope,{text:'new message'},'second');assert.equal((await ui.binding.ignoreLocal(ui.scope,record)).resolved.length,0);
 assert.equal(ui.drafts.pendingSend(ui.scope).id,'second');assert.equal(ui.calls.length,0);
 await ui.binding.ignoreLocal(ui.scope,ui.binding.records(ui.target)[0]);assert.equal(ui.drafts.pendingSend(ui.scope),null);assert.equal(ui.calls.length,0);
});

test('native-only providers never get background HTTP requests or queue mutations',async()=>{
 const ui=fixture();ui.target={...ui.target,url:null,sendUrl:null};ui.drafts.begin(ui.scope,body,'id');
 assert.equal(await ui.binding.reconcile(),null);assert.equal((await ui.binding.load(ui.scope)).capabilities.edit,false);
 await assert.rejects(ui.binding.panel.options.edit(ui.scope,{id:'id',version:'v',text:'text',editId:'attempt'}),/原生客户端管理/);await assert.rejects(ui.binding.change(ui.scope,'withdraw',{}),/原生客户端管理/);
 assert.equal(ui.calls.length,0);assert.equal(ui.drafts.pendingSend(ui.scope).id,'id');
});

const {MessageManagement}=require('../web/features/chat/message-management.js');
function realPanel(ui){
 const editor=ui.binding.loadEditor(ui.scope);
 return Object.assign(Object.create(MessageManagement.prototype),ui.binding.panel.options,{target:structuredClone(ui.scope),editor:structuredClone(editor),persistedEditor:structuredClone(editor),busy:false,closeButton:{},refreshButton:{},content:{},status:{},render(){}});
}
async function sharedPanels(requestA,requestB){
 const local=storage(),a=fixture({local,request:requestA}),b=fixture({local,request:requestB});b.drafts.coordinate=a.drafts.coordinate;
 const initial={id:'shared-id',sourceId:'shared-id',baseVersion:'v',operation:'edit',originalText:'same text',status:'editing',body:{text:'same text',attachments:['attachment'],skills:['skill']}};
 await a.binding.saveEditor(a.scope,initial);return {a,b,pa:realPanel(a),pb:realPanel(b)};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
for(const outcome of ['unknown','refused'])test(`real two-tab editor CAS admits one attempt and handles ${outcome} without unknown ID release`,async()=>{
 let resolve,reject;const {a,b,pa,pb}=await sharedPanels(()=>new Promise((done,fail)=>{resolve=done;reject=fail;}),()=>{throw Error('Second tab must not send');});
 const one=pa.submitEditor(),two=pb.submitEditor();while(!resolve)await tick();await two;
 assert.equal(a.calls.length,1);assert.equal(b.calls.length,0);assert.match(pb.status.textContent,/另一页面更新/);
 if(outcome==='unknown')resolve({status:'unknown'});else reject(Object.assign(Error('busy'),{status:400,code:'send_not_submitted'}));await one;
 const saved=a.binding.loadEditor(a.scope);assert.equal(saved.status,outcome==='refused'?'editing':'unknown');
 assert.equal(saved.id,'shared-id');
 await pb.submitEditor();assert.equal(b.calls.length,0,'A stale tab cannot claim the replacement or unknown record');
});

test('real late accepted reply cannot delete another tab newer queue editor',async()=>{
 let finish;const {a,b,pa}=await sharedPanels(()=>new Promise(resolve=>finish=resolve),()=>({status:'queued'}));
 const task=pa.submitEditor();while(!finish)await tick();const claimed=b.binding.loadEditor(b.scope);
 await b.binding.saveEditor(b.scope,null,claimed);
 const replacement={id:'replacement-id',status:'editing',body:{text:'new editor draft'}};await b.binding.saveEditor(b.scope,replacement,null);
 finish({queue:[{id:'shared-id',editId:claimed.attempt,text:'same text'}]});await task;
 assert.deepEqual(b.binding.loadEditor(b.scope),replacement);assert.match(pa.status.textContent,/另一页面更新/);assert.equal(a.calls.length,1);
});

test('claim save failure and unavailable coordinator prevent actual panel enqueue',async()=>{
 const {a,pa}=await sharedPanels(()=>{throw Error('Must not dispatch');},()=>{});a.drafts.write=()=>false;await pa.submitEditor();
 assert.equal(a.calls.length,0);assert.equal(pa.editor.status,'editing');assert.match(pa.status.textContent,/无法保存/);
 a.drafts.coordinate=async()=>null;await pa.submitEditor();assert.equal(a.calls.length,0);assert.equal(a.binding.loadEditor(a.scope).status,'editing');
});

test('two panels cannot start competing edits from the same empty local editor snapshot',async()=>{
 const local=storage(),a=fixture({local}),b=fixture({local});b.drafts.coordinate=a.drafts.coordinate;
 const pa=realPanel(a),pb=realPanel(b);pa.data=pb.data={version:'queue-version',draftAccountIdentity:a.scope.account};
 await Promise.all([pa.editRow({id:'queued',text:'original'}),pb.editRow({id:'queued',text:'original'})]);
 assert.equal(a.calls.length+b.calls.length,0);assert.match(pb.status.textContent,/另一页面更新/);assert.equal(a.binding.loadEditor(a.scope).sourceId,'queued');
});

test('binding open catches asynchronous load failures and notifies instead of rejecting',async()=>{
 const ui=fixture();let notified;ui.binding.notify=message=>notified=message;ui.binding.panel.open=async()=>{throw Error('load failed');};
 assert.equal(await ui.binding.open(),undefined);assert.equal(notified,'load failed');
});

test('unknown editor can only be explicitly ended, preserving chat draft and never resending',async()=>{
 const ui=fixture();const editor={id:'unknown-id',status:'unknown',attempt:'claim',body:{text:'possibly delivered'}};
 await ui.binding.saveEditor(ui.scope,editor);ui.drafts.save(ui.scope,{text:'chat draft'});const panel=realPanel(ui);
 panel.confirm=async()=>false;await panel.endUnknownEditor();assert.equal(ui.binding.loadEditor(ui.scope).id,'unknown-id');
 panel.confirm=async()=>true;await panel.endUnknownEditor();assert.equal(ui.binding.loadEditor(ui.scope),null);
 assert.equal(ui.drafts.load(ui.scope).text,'chat draft');assert.equal(ui.calls.length,0);
});

test('identityPending retries only bounded GET reads and eventually accepts verified identity',async()=>{
 let count=0;const ui=fixture({request:()=>++count===1?{draftAccountIdentity:'',identityPending:true}:{draftAccountIdentity:baseScope.account,receipts:[],queue:[]}});
 await ui.binding.load(ui.scope);assert.equal(ui.calls.length,2);assert.ok(ui.calls.every(call=>call.value===undefined));
});
test('identityPending exhausts after four reads and never retries a mutation',async()=>{
 const ui=fixture({request:()=>({draftAccountIdentity:'',identityPending:true})});await assert.rejects(ui.binding.load(ui.scope),/账号状态尚未确认/);assert.equal(ui.calls.length,4);assert.ok(ui.calls.every(call=>call.value===undefined));
 let mutations=0;const mutation=fixture({request:()=>{mutations++;throw Object.assign(Error('pending identity'),{status:409});}});
 await assert.rejects(mutation.binding.panel.options.edit(mutation.scope,{id:'id',version:'v',text:'new',editId:'attempt'}));assert.equal(mutations,1);
});
test('scope change during a readonly identity retry wait prevents the next request',async()=>{
 const ui=fixture({request:()=>({draftAccountIdentity:'',identityPending:true})}),old={...ui.scope};const task=ui.binding.load(old);
 await tick();ui.target={...ui.target,scope:{...old,account:'other'}};await assert.rejects(task,/切换/);assert.equal(ui.calls.length,1);
});
