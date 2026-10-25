// Real DOM acceptance against a synthetic page; never contacts a live session.
async function checkChatFeedback(){
  const checks=[],check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
  const frame=()=>new Promise(resolve=>requestAnimationFrame(resolve));
  const until=async predicate=>{for(let i=0;i<150;i++){if(predicate())return;await frame();}throw Error('Feedback fixture timed out');};
  const root=document.createElement('section');root.style.cssText='position:fixed;inset:0;z-index:99999;background:white;padding:12px;overflow:auto';
  const viewport=document.createElement('div'),messages=document.createElement('div'),older=document.createElement('button'),newer=document.createElement('button'),input=document.createElement('textarea');
  viewport.style.cssText='height:400px;width:100%;overflow:auto;overflow-anchor:none';viewport.append(older,messages,newer);root.append(viewport,input);document.body.append(root);
  let scope={gateway:'fixture',provider:'codex',account:'one',host:'local',session:'one'},changes=0;
  const quotes=new ComposerQuotes({messages,input,container:root,scope:()=>scope,onChange:()=>changes++,onPrompt:()=>{}});
  const pending=[],row=(n,role='assistant')=>({key:'r'+n,order:n,role,kind:role==='activity'?'commandExecution':'agentMessage',version:'v1',text:'Reply '+n+' 中文 '+('sample '.repeat(50))});
  const page=(rows,epoch='a',hasMore=true)=>({rows,epoch,hasMore,before:epoch+'.'+rows[0]?.key,sequence:1,meta:{requests:[]},files:[]});
  const timeline=new ChatTimeline({elements:{viewport,container:messages,older,newer},url:action=>'/synthetic/'+action+'?fixture=1',request:url=>new Promise(resolve=>pending.push({url,resolve})),renderMeta:()=>{},renderText:(node,text)=>node.textContent=text,status:()=>{}});
  try{
    timeline.setVisibility({showReasoning:false,showProcess:false});
    timeline.apply(page(Array.from({length:20},(_,i)=>row(300+i))),true);await frame();await frame();
    viewport.scrollTop=0;await frame();await frame();
    // The user can already be at the top, so another gesture need not emit scroll.
    viewport.dispatchEvent(new WheelEvent('wheel',{deltaY:-100,bubbles:true}));await until(()=>pending.length===1);
    const anchor=timeline.capture();
    pending.shift().resolve(page(Array.from({length:100},(_,i)=>row(200+i,'activity'))));
    await until(()=>pending.length===1);check(timeline.busy,'Hidden activity continues within the same history request');
    pending.shift().resolve(page([row(199)]));await until(()=>!timeline.busy);await frame();await frame();
    check(messages.textContent.includes('Reply 199'),'Earlier visible reply appears without reopening the chat');
    check(Math.abs(timeline.nodes.get(anchor.key).node.getBoundingClientRect().top-viewport.getBoundingClientRect().top-anchor.offset)<2,'History prepend preserves the reading position');
    viewport.scrollTop=0;await frame();await frame();
    if(!pending.length){viewport.dispatchEvent(new WheelEvent('wheel',{deltaY:-100}));}
    await until(()=>pending.length===1);
    timeline.apply(page([row(300),row(301)],'b'),true);
    pending.shift().resolve(page([row(198)]));await until(()=>pending.length===1);
    check(new URL(pending[0].url,location.origin).searchParams.get('before')==='b.r300','A concurrent live reset retries with the current history cursor');
    pending.shift().resolve(page([row(299)],'b',false));await until(()=>!timeline.busy);
    check(timeline.rows.has('r299')&&!timeline.hasMore,'History retry completes in place after a live reset');
    input.value='Keep this draft 保留草稿';
    timeline.nodes.get('r299').node.querySelector('.message-quote').click();await until(()=>quotes.quotes.length===1);
    check(quotes.quotes[0].text===row(299).text,'Codex message quote reaches the composer');
    check(input.value==='Keep this draft 保留草稿'&&changes===1,'Quote adds context without replacing or submitting the draft');
    const delayed={...row(298),truncated:true};timeline.apply(page([delayed],'b',true),false,true);
    timeline.nodes.get('r298').node.querySelector('.message-quote').click();await until(()=>pending.length===1);
    scope={...scope,session:'two'};
    pending.shift().resolve({key:'r298',version:'v1',offset:0,text:'Full stale body',next:null});await frame();await frame();
    check(quotes.quotes.length===1&&input.value==='Keep this draft 保留草稿','Delayed quote cannot enter another chat draft');
    // A touch drag at the boundary must also load history with no scroll event.
    viewport.scrollTop=0;timeline.lastTop=0;await frame();await frame();
    if(pending.length){pending.shift().resolve(page([row(297)],'b',false));await until(()=>!timeline.busy);}
    timeline.hasMore=true;timeline.before='b.r297';timeline.suppress=false;
    const touch=(name,y)=>{const event=new Event(name);Object.defineProperty(event,'touches',{value:[{clientY:y}]});viewport.dispatchEvent(event);};
    touch('touchstart',100);touch('touchmove',140);await until(()=>pending.length===1);
    pending.shift().resolve(page([row(296)],'b',false));await until(()=>!timeline.busy);
    check(timeline.rows.has('r296'),'Touch intent at scrollTop zero loads earlier content');
    check(root.scrollWidth<=root.clientWidth,'Feedback controls fit the viewport');
    return {passed:checks.length,checks};
  }finally{timeline.dispose();root.remove();}
}
