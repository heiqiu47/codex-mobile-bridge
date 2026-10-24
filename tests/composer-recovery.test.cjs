'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {ComposerDrafts}=require('../web/features/chat/composer-drafts.js');
function storage(){const values=new Map();return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,String(value)),removeItem:key=>values.delete(key)};}
const scope={gateway:'gateway',provider:'codex',account:'account',host:'local',session:'chat'};
const body={text:'old text',mode:'send',skills:['skill'],attachments:['attachment']};
function fixture(){
 const local=storage(),temporary=storage(),drafts=new ComposerDrafts(local,{});let tail=Promise.resolve();
 drafts.coordinate=update=>{const result=tail.then(()=>update(true));tail=result.catch(()=>{});return result;};
 return {local,temporary,drafts,options:{temporary},key:'pending:local|chat'};
}
const envelope=(id,status,extra={})=>({scope,receipts:[{id,status,...extra}]});

test('v2.1.4 v1 blocker resolves from exact accepted receipt without erasing later draft',async()=>{
 const {drafts}=fixture();drafts.begin(scope,body,'accepted-id');
 drafts.save(scope,{text:'later draft',quotes:[{text:'new quote'}],skills:['new-skill']});
 const records=drafts.pendingRecords(scope);assert.equal(records.length,1);assert.equal(records[0].source,'v1');
 assert.equal((await drafts.beginSend(scope,{...body,mode:'queue'},'new-id','attempt')).blocked,true);
 const result=await drafts.reconcilePending(scope,envelope('accepted-id','accepted'),{records});
 assert.equal(result.resolved.length,1);assert.equal(result.remaining.length,0);assert.equal(drafts.pendingSend(scope),null);
 assert.equal(drafts.pending(scope).id,'accepted-id','Do not delete a record still writable by an older page');
 assert.equal(drafts.load(scope).text,'later draft');assert.equal(drafts.load(scope).quotes[0].text,'new quote');
});

for(const status of ['accepted','cancelled','ignored','queued'])test(`authoritative ${status} consumes v2 plus its untracked v1 version only`,async()=>{
 const {drafts}=fixture();drafts.begin(scope,body,'id');await drafts.beginSend(scope,body,'unused','attempt');
 // v1 is already imported and guarded; v2 is the visible local blocker.
 const result=await drafts.reconcilePending(scope,envelope('id',status));assert.equal(result.resolved.length,1);
 assert.equal(drafts.pendingSend(scope),null);assert.equal(drafts.pending(scope).id,'id');
});

for(const status of ['unknown','notFound','not_found','failed',''])test(`${status||'missing'} receipt never clears or resends`,async()=>{
 const {drafts}=fixture();drafts.begin(scope,body,'id');const before=JSON.stringify(drafts.pendingRecords(scope));
 const result=await drafts.reconcilePending(scope,envelope('id',status));assert.equal(result.resolved.length,0);
 assert.equal(JSON.stringify(drafts.pendingRecords(scope)),before);
});

test('receipt id, verified scope, account and optional exact body/fingerprint must match',async()=>{
 const {drafts}=fixture();drafts.begin(scope,body,'id');
 const invalid=[envelope('other','accepted'),{...envelope('id','accepted'),scope:{...scope,account:'other'}},envelope('id','accepted',{account:'other'}),envelope('id','accepted',{body:{...body,text:'other'}}),envelope('id','accepted',{fingerprint:'other'})];
 for(const receipt of invalid)assert.equal((await drafts.reconcilePending(scope,receipt)).resolved.length,0);
 const reversed=Object.fromEntries(Object.entries(body).reverse());assert.equal((await drafts.reconcilePending(scope,envelope('id','accepted',{body:reversed,account:scope.account}))).resolved.length,1);
});

test('enumeration isolates gateway/account/host/session and validates legacy private metadata',()=>{
 const {drafts,temporary,key}=fixture();drafts.begin(scope,body,'current');
 temporary.setItem(key,JSON.stringify({id:'session',gateway:scope.gateway,target:'local|chat',...body}));
 drafts.temporaryPending.set(key,{id:'memory',gateway:scope.gateway,target:'local|chat',account:scope.account,...body});
 assert.deepEqual(drafts.pendingRecords(scope,{temporary}).map(record=>record.source),['v1','session','memory']);
 assert.equal(drafts.pendingRecords(scope,{temporary}).find(record=>record.source==='session').accountUnverified,true);
 for(const field of ['gateway','account','host','session']){
  const changed={...scope,[field]:'other'};
  // Old private records without account are eligible only after a verified receipt;
  // supplied account-tagged records must never cross accounts.
  if(field==='account')temporary.setItem(key,JSON.stringify({id:'session',gateway:scope.gateway,target:'local|chat',account:scope.account,...body}));
  assert.equal(drafts.pendingRecords(changed,{temporary,temporaryKey:key}).length,0);
 }
});

test('late authoritative response cannot consume a newer same-ID attempt version',async()=>{
 const {drafts}=fixture();await drafts.beginSend(scope,body,'id','first');const records=drafts.pendingRecords(scope);
 await drafts.beginSend(scope,body,'unused','second');
 assert.equal((await drafts.reconcilePending(scope,envelope('id','accepted'),{records})).resolved.length,0);
 assert.equal(drafts.pendingSend(scope).attempts.length,2);
});

test('recovery tombstone cannot hide another unknown written by an old page',async()=>{
 const {drafts}=fixture();drafts.begin(scope,body,'first');const record=drafts.pendingRecords(scope)[0];
 await drafts.ignoreLocalPending(scope,record);drafts.confirm(scope,'first',0);drafts.begin(scope,{...body,text:'second'},'second');
 assert.equal(drafts.pendingSend(scope).id,'second');assert.equal(drafts.pendingRecords(scope)[0].id,'second');
 assert.equal((await drafts.beginSend(scope,{...body,text:'second',mode:'queue'},'unused','attempt')).blocked,true);
 assert.equal((await drafts.ignoreLocalPending(scope,record)).resolved.length,0,'Old snapshot cannot ignore new v1');
});

test('v1 resolution preserves active v2 and a new unseen legacy version still blocks it',async()=>{
 const {drafts}=fixture();await drafts.beginSend(scope,body,'active','attempt');drafts.begin(scope,body,'legacy');
 const legacy=drafts.pendingRecords(scope).find(record=>record.source==='v1');await drafts.ignoreLocalPending(scope,legacy);
 assert.equal(drafts.pendingSend(scope).id,'active');drafts.confirm(scope,'legacy',0);drafts.begin(scope,{...body,text:'new legacy'},'legacy-new');
 assert.equal((await drafts.beginSend(scope,body,'unused','second')).blocked,true);
});

test('private session/memory recovery works without coordinator and never touches replacement records',async()=>{
 const {drafts,temporary,key}=fixture();const legacy={id:'private',gateway:scope.gateway,target:'local|chat',account:scope.account,...body};
 temporary.setItem(key,JSON.stringify(legacy));drafts.temporaryPending.set(key,legacy);const records=drafts.pendingRecords(scope,{temporary});
 drafts.coordinate=async()=>null;
 temporary.setItem(key,JSON.stringify({...legacy,id:'replacement'}));
 const result=await drafts.reconcilePending(scope,envelope('private','accepted'),{temporary,records});
 assert.deepEqual(result.resolved.map(record=>record.source),['memory']);assert.equal(JSON.parse(temporary.getItem(key)).id,'replacement');
 const replacement=drafts.pendingRecords(scope,{temporary})[0];const ignored=await drafts.ignoreLocalPending(scope,replacement,{temporary});assert.equal(ignored.resolved.length,1);
});

test('shared storage is unchanged when coordinator or durable write fails',async()=>{
 const {drafts}=fixture();drafts.begin(scope,body,'id');const before=JSON.stringify(drafts.pendingRecords(scope));
 drafts.coordinate=async()=>null;assert.equal((await drafts.reconcilePending(scope,envelope('id','accepted'))).resolved.length,0);
 drafts.coordinate=async update=>update(true);drafts.write=()=>false;assert.equal((await drafts.ignoreLocalPending(scope,drafts.pendingRecords(scope)[0])).resolved.length,0);
 assert.equal(JSON.stringify(drafts.pendingRecords(scope)),before);
});

test('an uncoordinated old-page write during recovery cannot be marked as consumed',async()=>{
 const {drafts}=fixture();drafts.begin(scope,body,'old');const records=drafts.pendingRecords(scope);
 const originalRead=drafts.read.bind(drafts);let v2Reads=0;
 drafts.read=key=>{if(key===drafts.key(scope,'pending-v2')&&++v2Reads===2)drafts.write(drafts.key(scope,'pending'),{id:'late-old-page',fingerprint:JSON.stringify(body),body});return originalRead(key);};
 const result=await drafts.reconcilePending(scope,envelope('old','accepted'),{records});
 assert.equal(result.resolved.length,1);assert.equal(result.remaining.find(record=>record.source==='v1').id,'late-old-page');
 assert.equal(drafts.pendingSend(scope).id,'late-old-page');
});

for(const provider of ['claude','deepseek'])test(`${provider} sync begin respects explicit recovery but a new old-page v1 still blocks`,async()=>{
 const {drafts}=fixture(),key={...scope,provider};drafts.begin(key,body,'old-id');drafts.save(key,{text:'current draft',quotes:[{text:'current quote'}]});
 const record=drafts.pendingRecords(key)[0];await drafts.ignoreLocalPending(key,record);
 assert.equal(drafts.pending(key).id,'old-id','Keep raw v1 for mixed-version recovery');
 assert.equal(drafts.begin(key,{...body,mode:'queue'},'new-id').id,'new-id');
 assert.equal(drafts.load(key).text,'current draft');
 // An older, uncoordinated page overwrites v1 after the recovery marker.
 drafts.write(drafts.key(key,'pending'),{id:'new-old-page',fingerprint:JSON.stringify(body),body});
 const changed=drafts.begin(key,{...body,mode:'queue'},'must-not-send');assert.equal(changed.blocked,true);assert.equal(changed.id,'new-old-page');
 assert.equal(drafts.load(key).quotes[0].text,'current quote');
});
