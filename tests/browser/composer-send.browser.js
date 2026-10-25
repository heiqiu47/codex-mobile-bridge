// Isolated synthetic page only. Two same-origin documents use real IndexedDB
// connections and localStorage. No gateway send endpoint or model is contacted.
window.runComposerSendCoordinationChecks=async function(){
  const checks=[],check=(value,label)=>{if(!value)throw Error(label);checks.push(label);};
  const frames=[],gateway='fixture-send-'+crypto.randomUUID();
  const scope={gateway,provider:'codex',account:'synthetic',host:'local',session:'synthetic'};
  const body={text:'same quoted text',mode:'send',skills:['skill'],attachments:['attachment']};
  const create=async()=>{
    const frame=document.createElement('iframe');frame.hidden=true;
    const loaded=new Promise(resolve=>frame.onload=resolve);frame.src='about:blank';document.body.append(frame);frames.push(frame);await loaded;
    return new ComposerDrafts(frame.contentWindow.localStorage,frame.contentWindow.indexedDB);
  };
  const a=await create(),b=await create();
  const reset=()=>localStorage.removeItem(a.key(scope,'pending-v2'));
  try{
    check(frames[0].contentDocument!==frames[1].contentDocument,'Two independent same-origin documents');
    const [first,second]=await Promise.all([a.beginSend(scope,body,'id-a','attempt-a'),b.beginSend(scope,body,'id-b','attempt-b')]);
    check(first.id===second.id,'Concurrent begins serialize and reuse one logical ID');
    check(a.pendingSend(scope).attempts.length===2,'Both attempts survive the read/write race');
    await a.settleSend(scope,first.id,'attempt-a','reject');
    check(b.pendingSend(scope).id===second.id&&b.pendingSend(scope).attempts.includes('attempt-b'),'Old rejection preserves the other document unknown ID');
    check((await b.beginSend(scope,{...body,mode:'queue'},'queue-id','attempt-queue')).blocked,'Unknown cannot become a fresh queued request');
    await b.settleSend(scope,second.id,'attempt-b','reject');
    check(a.pendingSend(scope)===null,'All explicitly rejected attempts release the logical pending');
    const queued=await b.beginSend(scope,{...body,mode:'queue'},'queue-id','attempt-queue');
    check(queued.id==='queue-id','Explicit queue change is possible after every rejection');
    const saved=a.save(scope,{text:'draft',quotes:[{text:'quote'}],skills:['skill']});
    await a.settleSend(scope,queued.id,'attempt-queue','confirm',saved.revision);
    check(a.pendingSend(scope)===null&&a.load(scope)===null,'Successful confirmation clears only its draft and pending');
    reset();
    const old=await a.beginSend(scope,body,'old-id','old-attempt');
    const newer=await b.beginSend(scope,body,'ignored-id','new-attempt');
    await b.settleSend(scope,newer.id,'new-attempt','reject');
    check(a.pendingSend(scope).attempts.includes('old-attempt'),'New rejection preserves the older in-flight attempt');
    await a.settleSend(scope,old.id,'old-attempt','reject');
    reset();
    const stale=await a.beginSend(scope,body,'stale-id','stale-attempt');
    const replacement=await b.beginSend(scope,{text:'new message'},'replacement-id','replacement-attempt');
    await Promise.all([a.settleSend(scope,stale.id,'stale-attempt','reject'),a.settleSend(scope,stale.id,'stale-attempt','confirm',0),a.settleSend(scope,stale.id,null,'ignore')]);
    check(b.pendingSend(scope).id===replacement.id,'Stale reject/confirm/ignore cannot remove a newer request');
    return {checks:checks.length,passed:checks,documents:2,syntheticSendCalls:0,realSendCalls:0};
  }finally{
    for(const kind of ['draft','pending','pending-v2'])localStorage.removeItem(a.key(scope,kind));
    for(const frame of frames)frame.remove();
  }
};
