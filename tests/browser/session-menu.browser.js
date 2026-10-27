// Run only in an isolated page with production SessionMenu and its styles loaded.
async function runSessionMenuBrowserChecks(){
  const check=(value,message)=>{if(!value)throw Error(message);};
  const anchor=document.createElement('button');anchor.textContent='Synthetic session';document.body.append(anchor);
  const calls=[],notices=[],menu=new SessionMenu({notify:text=>notices.push(text)});
  const context=()=>({title:'合成会话',subtitle:'Codex · fixture',pinned:false,nativeOrganization:true,
    details:[['会话 ID','synthetic-session',true],['工作目录','D:\\Synthetic\\Project',true]],
    pin:value=>calls.push(['pin',value]),rename:title=>calls.push(['rename',title]),
    organization:change=>{if(change)calls.push(['organization',change]);return Promise.resolve({projectId:'project-a',sectionId:null,projects:[{id:'project-a',name:'当前项目'},{id:'project-b',name:'目标项目'}],sections:[{id:'section-b',name:'目标分区'}],status:'confirmed'});},
    archive:()=>calls.push(['archive']),link:'codex://threads/synthetic',isCurrent:()=>true});
  window.BridgeClipboard={copyWithFeedback:(get,button)=>{check(!button.disabled,'clipboard must receive an enabled trusted-click target');calls.push(['copy',get()]);return Promise.resolve(true);}};
  const click=async label=>{const button=[...menu.box.querySelectorAll('button')].find(node=>node.textContent===label);check(button,'missing action: '+label);button.click();await new Promise(resolve=>setTimeout(resolve,0));};
  try{
    menu.show(context(),{element:anchor,x:innerWidth-1,y:innerHeight-1});
    const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
    check(getComputedStyle(menu.box).animationName===(reduced?'none':innerWidth<=640?'sm-sheet-in':'sm-menu-in'),'menu uses the expected motion preference');
    await Promise.all(menu.box.getAnimations().map(animation=>animation.finished.catch(()=>{})));
    let rect=menu.box.getBoundingClientRect();check(rect.left>=-1&&rect.right<=innerWidth+1&&rect.bottom<=innerHeight+1,'menu must fit the viewport: '+JSON.stringify({left:rect.left,right:rect.right,bottom:rect.bottom,width:innerWidth,height:innerHeight}));
    check(!menu.box.textContent.includes('完成时通知'),'notification action is excluded');
    await click('复制深度链接');check(calls.at(-1)[1]==='codex://threads/synthetic','link copy preserves identity');
    await click('项目');check(menu.box.querySelector('[aria-pressed=true]').textContent.includes('当前项目'),'native selection is marked');
    await click('目标项目');check(calls.at(-1)[1].targetId==='project-b'&&calls.at(-1)[1].expectedId==='project-a','native project move preserves prior identity');
    menu.show(context(),{element:anchor});await click('分区');await click('目标分区');check(calls.at(-1)[1].kind==='section','native section uses the shared menu');
    menu.show(context(),{element:anchor});
    await click('置顶会话');check(calls.at(-1)[1]===true&&menu.box.textContent.includes('取消置顶'),'pin updates immediately');
    menu.box.querySelector('[aria-label="修改聊天名称"]').click();
    const input=menu.box.querySelector('input');input.value='<b>新的名称</b>';menu.box.querySelector('form').requestSubmit();await new Promise(resolve=>setTimeout(resolve,0));
    check(menu.box.querySelector('strong').textContent==='<b>新的名称</b>'&&!menu.box.querySelector('b'),'rename uses text, preserves title and escapes markup');
    await click('会话详情');const copy=menu.box.querySelector('[aria-label="复制 会话 ID"]');check(copy,'ID copy remains available in details');copy.click();await new Promise(resolve=>setTimeout(resolve,0));check(calls.at(-1)[1]==='synthetic-session','ID copy retains original ID');await click('返回会话菜单');
    await click('停止任务并归档…');check(calls.every(row=>row[0]!=='archive'),'archive requires confirmation');await click('取消');check(calls.every(row=>row[0]!=='archive'),'cancel never archives');
    await click('停止任务并归档…');await click('确认归档');check(calls.filter(row=>row[0]==='archive').length===1,'archive dispatches exactly once');
    menu.show({...context(),archived:true},{element:anchor});await click('恢复会话');check(calls.filter(row=>row[0]==='archive').length===2,'restore dispatches directly');
    const before=calls.length;menu.show({...context(),isCurrent:()=>false},{element:anchor});await click('置顶会话');check(calls.length===before&&menu.box.querySelector('[role="alert"]'),'stale authentication blocks write');
    let resolve;menu.show({...context(),organization:()=>new Promise(done=>{resolve=done;})},{element:anchor});await click('项目');await click('返回会话菜单');resolve({projects:[],sections:[]});await new Promise(done=>setTimeout(done,0));check(!menu.box.textContent.includes('移出项目'),'late native list never paints another view');
    menu.show({...context(),organization:()=>Promise.reject(Error('native unavailable'))},{element:anchor});await click('分区');check(menu.box.querySelector('[role="alert"]').textContent==='native unavailable','native read error is visible');
    menu.close();let navigated=0;anchor.addEventListener('click',()=>navigated++);menu.bind(anchor,context);
    anchor.dispatchEvent(new PointerEvent('pointerdown',{pointerType:'touch',button:0,clientX:1,clientY:1}));
    anchor.dispatchEvent(new PointerEvent('pointermove',{pointerType:'touch',clientX:30,clientY:1}));
    await new Promise(resolve=>setTimeout(resolve,600));check(!menu.box,'scroll movement cancels long press');
    anchor.dispatchEvent(new PointerEvent('pointerdown',{pointerType:'touch',button:0,clientX:1,clientY:1}));
    await new Promise(resolve=>setTimeout(resolve,600));check(menu.box?.open,'stationary long press opens menu');anchor.click();check(navigated===0,'long press consumes the navigation click');
    const exiting=menu.box;exiting.dispatchEvent(new Event('cancel',{cancelable:true}));
    check(!menu.box,'cancel releases the active menu immediately');
    check(reduced?!exiting.isConnected:exiting.open&&exiting.inert&&exiting.classList.contains('sm-closing'),'cancel respects motion preference and blocks actions during exit');
    await new Promise(resolve=>setTimeout(resolve,300));check(!exiting.isConnected,'exit removes its modal and backdrop');
    menu.show(context(),{element:anchor});menu.close();menu.show(context(),{element:anchor});const replacement=menu.box;
    await new Promise(resolve=>setTimeout(resolve,300));check(menu.box===replacement&&replacement.open,'old exit completion never closes a replacement menu');
    return {passed:true,width:innerWidth,calls:calls.length};
  }catch(error){menu.close();throw error;}
}
