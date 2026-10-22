// Use only with bootstrap-fixture.py, then call and await this function.
async function runBootstrapBrowserChecks(){
  const state=await (await fetch('/__state')).json(),probe=window.__startupTest;
  const check=(value,message)=>{if(!value)throw Error(message);};
  const fatal=['shell-fatal','js-fatal','runtime','pair-unknown'].includes(state.case);
  const root=document.getElementById('bootstrap-status'),details=document.getElementById('bootstrap-details');
  check(probe,'Missing isolated fixture probe');
  check(probe.scenario===state.case,'Navigation has not committed to the expected fixture');
  const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(new URLSearchParams(location.search).get('motion')==='reduce')check(reducedMotion,'Reduced-motion regression requires browser media emulation');
  if(state.case==='bootstrap-missing'){
    check(!root.hidden&&getComputedStyle(root).visibility==='visible','Bootstrap outage must retain a visible fallback');
    check(!window.BridgeBootstrap,'The test must actually fail the bootstrap request');
  }else if(fatal){
    check(!root.hidden&&root.dataset.state==='failed','Expected a bounded terminal failure');
    check(!details.open&&!details.hidden,'Diagnostics must be available but collapsed');
    check(!/启动诊断|resource|Mozilla/.test(document.getElementById('bootstrap-message').textContent),'Diagnostics leaked into main copy');
    check(!probe.executed.includes('/app.js')||state.case==='pair-unknown','Dependent app executed after failure');
  }else{
    check(root.hidden&&!document.getElementById('login').hidden,'Expected recovered login');
    check(!probe.titles.some(title=>title.includes('尚未加载完成')),'Transient failure exposed the terminal page');
    check(probe.errors.length===0,'Unexpected runtime exception');
    check(probe.loadClipboard===true,'Native load hook ran before the clipboard definition');
    const scripts=[...document.scripts].filter(s=>s.bridgeStartupResource).map(s=>new URL(s.src).pathname).filter(p=>p!=='/message-actions.js');
    check(new Set(probe.executed).size===probe.executed.length,'A script executed more than once');
    check(scripts.every((name,i)=>i===0||probe.executed.indexOf(name)>probe.executed.indexOf(scripts[i-1])),'Classic script execution order changed');
    check(probe.executed.indexOf('/message-actions.js')<probe.executed.indexOf(scripts[0]),'Eager clipboard definition executed too late');
  }
  if(state.case==='slow'||state.case==='bootstrap-missing'){
    check(probe.visibilitySamples.some(s=>s.at<300&&!s.visible),'Missing hidden initial frame');
    check(!probe.visibilitySamples.some(s=>s.at<300&&s.visible),'Startup UI flashed before its delay');
    check(probe.visibilitySamples.some(s=>s.visible),'Startup never showed feedback');
  }
  // Without the failed shell CSS, the plain HTML fallback is visible; it is not the overlay.
  if(probe.readyAt<400)check(!probe.visibilitySamples.some(s=>s.styled&&s.visible),'Fast startup flashed');
  if(state.case==='shell-once')check(state.requests['/style.css']>=2,'Eager shell stylesheet was not retried');
  if(state.case==='shell-twice')check(state.requests['/style.css']>=3,'The repeated shell failure did not recover');
  // Chromium can fetch the parser-created link twice. Count link attempts, not HTTP retries.
  if(state.case.startsWith('shell-'))check(probe.shellLoads>=1&&probe.shellLoads<=3,'Shell stylesheet recovery exceeded its three-attempt limit');
  if(state.case==='shell-fatal')check(probe.shellLoads===3,'Shell stylesheet recovery stopped before its final attempt');
  if(state.case==='pair-unknown')check(state.writes.length===1&&state.writes[0]==='/api/pair','Pairing write was replayed');
  else check(state.writes.length===0,'Startup unexpectedly submitted a write');
  if(state.case==='external-script')check(probe.blockedScripts.includes('https://static.cloudflareinsights.com/beacon.min.js'),'Injected analytics was not blocked by CSP');
  return {case:state.case,passed:true,reducedMotion,shellLoads:probe.shellLoads,readyMs:Math.round(probe.readyAt||0),scriptsExecuted:probe.executed.length,
    requests:state.requests,writes:state.writes,firstVisibleMs:Math.round(probe.visibilitySamples.find(s=>s.visible)?.at||0)};
}
