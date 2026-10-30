const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {webcrypto,createHmac}=require('node:crypto');
const template=fs.readFileSync('bridge/clients/claude/connector.js','utf8');
const waitFor=async predicate=>{const end=Date.now()+3000;while(!predicate()){if(Date.now()>end)throw Error('timeout');await new Promise(resolve=>setTimeout(resolve,5));}};

for(const transport of ['cdp','file'])test(`${transport}: Code and Cowork rename verifies native identity without activation`,async()=>{
  const config={transport,cwd:'/synthetic',request:'request.json',response:'response.json',token:'fixture',generation:'fixture',reconnect:true,connectorRevision:13};
  const pack=value=>{const payload=JSON.stringify({generation:config.generation,...value});return JSON.stringify({payload,signature:createHmac('sha256',config.token).update(payload).digest('hex')});};
  let request=pack({seq:0,type:'idle'}),response,seq=0,wrongIdentity=false,ignoreWrite=false;
  const calls=[],rows={code:{sessionId:'code-id',cwd:'/synthetic',title:'Codex Bridge Connector'},cowork:{sessionId:'cowork-id',cwd:'/vm',userSelectedFolders:['/synthetic'],title:'Before'}};
  const surface=kind=>({
    async getAll(){return [rows[kind]];},
    async getSession(id){return {...rows[kind],sessionId:wrongIdentity?'other':id};},
    async updateSession(id,options){calls.push({kind,id,options:JSON.parse(JSON.stringify(options))});if(!ignoreWrite)rows[kind].title=options.title;},
    async readFileAtCwd(){return {contents:request};},
    async writeSessionFile(id,path,text){response=JSON.parse(JSON.parse(text).payload);return {hash:'fixture'};},
    async start(){throw Error('Rename must not start a session');},
    async sendMessage(){throw Error('Rename must not prompt a session');},
  });
  const window={'claude.web':{LocalSessions:surface('code'),LocalAgentModeSessions:surface('cowork')}};
  const running=vm.runInNewContext(template.replace('__BRIDGE_CONFIG__',JSON.stringify(config)),{window,crypto:webcrypto,TextEncoder,Uint8Array,Date,setTimeout:(fn,ms)=>setTimeout(fn,Math.min(ms,10)),clearTimeout,console});
  await waitFor(()=>transport==='cdp'?window.__claudeMobileBridge?.invoke:response?.connected);
  const invoke=async(surface,title)=>{
    const msg={type:'request',seq:++seq,surface,method:'mobileRename',args:[rows[surface].sessionId,{title}],expires:Date.now()/1000+10,token:config.token,generation:config.generation};
    if(transport==='cdp')return JSON.parse(JSON.stringify(await window.__claudeMobileBridge.invoke(msg)));
    request=pack(msg);await waitFor(()=>response?.seq===seq&&response.done);return response;
  };
  try{
    const capabilities=transport==='cdp'?window.__claudeMobileBridge.status().surfaces:response.surfaces;
    for(const kind of ['code','cowork']){
      assert.ok(capabilities[kind].includes('mobileRename'));
      const reply=await invoke(kind,'  用户标题  ');
      assert.deepEqual(reply.result,{status:'confirmed',scope:'native',result:{id:rows[kind].sessionId,title:'用户标题'}});
      assert.deepEqual(calls.at(-1),{kind,id:rows[kind].sessionId,options:{title:'用户标题',titleSource:'user'}});
    }
    const before=calls.length;
    for(const title of [null,{},'', 'x'.repeat(121),'a\nb','\na'])assert.ok((await invoke('code',title)).error);
    assert.equal(calls.length,before);
    wrongIdentity=true;assert.match((await invoke('code','Wrong identity')).error,/目标无法确认/);assert.equal(calls.length,before);
    wrongIdentity=false;ignoreWrite=true;
    assert.match((await invoke('code','Unknown outcome')).error,/结果待核对/);
    assert.equal(calls.length,before+1);
    assert.equal(rows.code.cwd,'/synthetic');assert.deepEqual(rows.cowork.userSelectedFolders,['/synthetic']);
  }finally{window.__claudeMobileBridge.stop();await running;}
});
