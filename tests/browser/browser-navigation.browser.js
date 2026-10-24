/* Inject only into CMB_NAVIGATION_FIXTURE=1 CMB_FIXTURE_ONLY=1 synthetic server. */
window.checkBrowserNavigation=async function(){
  const assert=(value,message)=>{if(!value)throw Error(message);results.push(message);};
  const until=async predicate=>{for(let i=0;i<100;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,40));}throw Error('Navigation fixture timed out');};
  const results=[],sid='12345678-1234-4234-9234-123456789012',wsl='wsl:'+'a'.repeat(32);
  const cases=[['codex',sid,'local'],['codex','12345678-1234-4234-9234-123456789014','local'],['codex','12345678-1234-4234-9234-123456789015','fixture-ssh'],['codex',sid,wsl],['claude','claude-fixture','local'],['deepseek','deepseek-fixture','local']];
  for(const [provider,id,host] of cases){
    if(document.getElementById('app').classList.contains('chat-open')){if(isCodexClient(clientNavigation.provider))document.getElementById('back').click();else desktopSessions.backToList();await until(()=>!history.state?.route);}
    await clientNavigation.choose(provider,{activate:false});
    if(provider==='codex')await openChat(id,host);else await desktopSessions.open(id);
    const input=provider==='codex'?document.getElementById('message'):desktopSessions.input;
    const wb=provider==='codex'?workbench:desktopSessions.workbench,session=wb.current;
    input.value='浏览器草稿 '+provider+' '+host;input.dispatchEvent(new Event('input',{bubbles:true}));const draft=input.value;
    const length=history.length,dialog=document.createElement('dialog');document.body.append(dialog);dialog.showModal();
    history.back();await until(()=>!document.getElementById('app').classList.contains('chat-open'));
    assert(!dialog.open,provider+'/'+host+' back closes detail dialog');dialog.remove();
    assert(wb.sessions.get(session.key)===session,provider+'/'+host+' back retains workbench state');
    history.forward();await until(()=>document.getElementById('app').classList.contains('chat-open')&&(provider==='codex'?currentId===id:desktopSessions.sid===id));
    await until(()=>input.value===draft);assert(input.value===draft,provider+'/'+host+' Forward restores draft');
    assert(wb.current===session,provider+'/'+host+' Forward reuses workbench');assert(history.length===length,provider+'/'+host+' Forward adds no history');
    // Synthetic tool bodies exercise the real workbench without starting a PTY
    // or reading files. Returning to the list must not dispose their resources.
    for(const kind of ['files','terminal']){
      const body=document.createElement('div');body.textContent='Synthetic '+kind;
      let disposed=0;const tab={id:kind,name:kind,body};
      if(kind==='terminal')tab.terminal={dispose(){disposed++;}};
      session.files.push(tab);wb.select(kind);
      assert(wb.panel.contains(body),provider+'/'+host+' '+kind+' is displayed');
      history.back();await until(()=>!document.getElementById('app').classList.contains('chat-open'));
      assert(session.active===kind&&session.files.includes(tab)&&disposed===0,provider+'/'+host+' Back retains '+kind);
      history.forward();await until(()=>document.getElementById('app').classList.contains('chat-open')&&!browserNavigation.restoring);
      assert(wb.current===session&&wb.panel.contains(body)&&disposed===0,provider+'/'+host+' Forward restores '+kind);
      await wb.close(kind);
    }
  }
  return {passed:results.length,results};
};
