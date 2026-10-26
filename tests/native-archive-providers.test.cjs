'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {webcrypto}=require('node:crypto');
async function claude({restore=true}={}){
 const config={cwd:'/fixture',transport:'cdp',token:'fixture',generation:'run',connectorRevision:12},calls=[];
 const root={sessionId:'root',isRunning:false,isArchived:false,pendingToolPermissions:[]},child={sessionId:'child',spawnedFrom:{sessionId:'root'},isRunning:false,isArchived:false};
 const unrelated={sessionId:'other',isRunning:true,isArchived:false};
 const api={getAll:async()=>[root,child,unrelated],getSession:async id=>[root,child,unrelated].find(row=>row.sessionId===id),interrupt:async id=>{calls.push(['interrupt',id]);[root,child,unrelated].find(row=>row.sessionId===id).isRunning=false;},loadArchivedSessions:async()=>{calls.push(['metadata']);},archive:async(...args)=>{calls.push(['archive',...args]);root.isArchived=true;child.isArchived=true;},...restore?{unarchive:async(...args)=>{calls.push(['unarchive',...args]);root.isArchived=false;}}:{}};
 const window={'claude.web':{LocalSessions:api,LocalAgentModeSessions:{...api}}};
 await vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../bridge/clients/claude/connector.js'),'utf8').replace('__BRIDGE_CONFIG__',JSON.stringify(config)),{window,crypto:webcrypto,TextEncoder,Uint8Array,Date,setTimeout,clearTimeout});
 let seq=0;
 return {root,child,calls,status:()=>window.__claudeMobileBridge.status(),invoke:(method,args=['root'],surface='code')=>window.__claudeMobileBridge.invoke({...config,surface,method,args,seq:++seq,expires:Date.now()/1000+30})};
}
test('Claude Code native archive is reversible and preserves worktree; Cowork does not inherit capability',async()=>{
 const ui=await claude();assert.ok(ui.status().surfaces.code.includes('mobileArchive'));assert.equal(ui.status().surfaces.cowork.includes('mobileArchive'),false);
 const state=await ui.invoke('mobileArchiveState');assert.equal(state.result.archiveSafe,true);assert.deepEqual(Object.keys(state.result.archiveFlags).sort(),['child','root']);
 assert.equal((await ui.invoke('mobileArchive',['root',{archived:true}])).result.status,'accepted');
 assert.equal((await ui.invoke('mobileArchive',['root',{archived:false}])).result.status,'accepted');
 assert.deepEqual(JSON.parse(JSON.stringify(ui.calls)),[['archive','root',{cleanupWorktree:false}],['unarchive','root']]);
 await ui.invoke('mobileList',[]);assert.deepEqual(ui.calls.at(-1),['metadata']);
 assert.match((await ui.invoke('mobileArchive',['root',{archived:true}],'cowork')).error,/不支持/);
});
test('Claude archive refuses descendants, pending input, background activity and unknown runtime before any native write',async()=>{
 const ui=await claude();ui.child.isRunning=true;
 assert.equal((await ui.invoke('mobileArchive',['root',{archived:true}])).result.archiveNotSent,true);ui.child.isRunning=false;
 for(const update of [{pendingToolPermissions:[{id:1}]},{heldInput:[{text:'queued'}]},{hasBackgroundActivity:true},{pendingLanyardConsent:{}},{isRunning:undefined}]){
  const prior={...ui.root};Object.assign(ui.root,update);
  // An empty consent object is still a pending consent, unlike an empty list.
  const reply=await ui.invoke('mobileArchive',['root',{archived:true}]);
  assert.equal(reply.result.archiveNotSent,true);
  for(const key of Object.keys(ui.root))delete ui.root[key];Object.assign(ui.root,prior);
 }
 assert.equal(ui.calls.length,0);
 const old=await claude({restore:false});assert.equal(old.status().surfaces.code.includes('mobileArchive'),false);
});
test('DSH legacy archive stays idle-only; confirmed archive stops and verifies before native write',async()=>{
 const {apply}=await import('../bridge/clients/deepseek/host.mjs');const fsp=require('node:fs/promises');
 await fsp.mkdir(path.join(__dirname,'../.tmp'),{recursive:true});const folder=await fsp.mkdtemp(path.join(__dirname,'../.tmp/dsh-archive-'));
 const endpoint=path.join(folder,'endpoint.json'),configPath=path.join(folder,'config.json');await fsp.writeFile(configPath,JSON.stringify({token:'fixture',endpoint}));
 const row={sessionId:'native',cwd:'/original',running:false,projections:{values:{}}},calls=[],disposers=[],handlers=new Map();let nativeBusy=false;
 const registry={archivedSessionIds:[],async archiveSession(sid,options){calls.push(['archive',sid,options]);if(nativeBusy){const error=Object.assign(new Error('active descendant'),{name:'WorkspaceActiveSessionError',sessionId:sid,activity:[{kind:'subagent'}]});throw error;}this.archivedSessionIds=[sid];},async unarchiveSession(sid){calls.push(['unarchive',sid]);this.archivedSessionIds=[];}};
 const ctx={sessionController:{list:async()=>({items:[row]})},workspaceRegistry:registry,permissionPresets:{catalog:()=>({options:[],defaultPreset:'workspace-write'})},agents:{list:()=>[]},on:(name,fn)=>handlers.set(name,fn),effect:setup=>disposers.push(setup())};
 try{
  await apply(ctx,{configPath});const {port}=JSON.parse(await fsp.readFile(endpoint,'utf8'));
  const invoke=async(action,body={})=>{const response=await fetch(`http://127.0.0.1:${port}/mobile`,{method:'POST',headers:{Authorization:'Bearer fixture','Content-Type':'application/json'},body:JSON.stringify({action,sid:'native',body})});return {status:response.status,value:await response.json()};};
  assert.equal((await invoke('archive-state')).value.capabilities.archive,true);
  assert.equal((await invoke('archive',{archived:true})).value.status,'accepted');assert.equal((await invoke('archive-state')).value.archived,true);
  assert.equal((await invoke('archive',{archived:false})).value.status,'accepted');assert.equal((await invoke('archive-state')).value.archived,false);
  assert.deepEqual(calls,[['archive','native',{}],['unarchive','native']]);
  row.running=true;assert.equal((await invoke('archive',{archived:true})).value.archiveNotSent,true);row.running=false;
  delete row.running;assert.equal((await invoke('archive',{archived:true})).value.archiveNotSent,true);row.running=false;
  const count=calls.length;nativeBusy=true;assert.equal((await invoke('archive',{archived:true})).value.archiveNotSent,true);assert.equal(registry.archivedSessionIds.length,0);assert.equal(calls.length,count+1);
  let resolve;const pending=handlers.get('approval/request')({agent:{id:'native'},toolName:'fixture'},()=>new Promise(done=>{resolve=done;}));
  assert.equal((await invoke('archive',{archived:true})).value.archiveNotSent,true);resolve('rejected');await pending;
  nativeBusy=false;row.running=true;calls.length=0;
  ctx.parallel=async(name,body)=>{calls.push(['stop',name,body.sessionId]);row.running=false;};
  ctx.waterfall=async(name,body)=>{calls.push(['read-activity',name,body.sessionId]);return [];};
  assert.equal((await invoke('archive',{archived:true,disconnect:true})).value.status,'accepted');
  assert.deepEqual(calls.map(call=>call[0]),['stop','read-activity','archive']);
  assert.deepEqual(calls[0],['stop','workspace/session-stop','native']);
  await invoke('archive',{archived:false});calls.length=0;row.running=true;
  ctx.parallel=async()=>{throw Error('stop lost');};
  assert.equal((await invoke('archive',{archived:true,disconnect:true})).status,400);
  assert.equal(calls.length,0);assert.equal(registry.archivedSessionIds.length,0);
  assert.ok(calls.every(call=>call[2]?.stopActivity!==true));
 }finally{for(const dispose of disposers.reverse())if(typeof dispose==='function')await dispose();await fsp.rm(folder,{recursive:true,force:true});}
});

test('confirmed Claude archive stops only the target subtree and keeps worktree',async()=>{
 const ui=await claude();ui.root.isRunning=true;ui.child.isRunning=true;
 const reply=await ui.invoke('mobileArchive',['root',{archived:true,disconnect:true}]);
 assert.equal(reply.result.status,'accepted');
 assert.deepEqual(JSON.parse(JSON.stringify(ui.calls)),[['interrupt','child'],['interrupt','root'],['archive','root',{cleanupWorktree:false}]]);
});
