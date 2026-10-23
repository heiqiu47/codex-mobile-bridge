// Run only in the loopback bootstrap fixture. No real client/API is accessed.
async function runDesktopHistoryBrowserChecks(){
  const checks=[],calls=[],notices=[];
  const check=(value,label)=>{if(!value)throw Error(label);checks.push(label);};
  const until=async predicate=>{const end=performance.now()+3000;while(!predicate()){
    if(performance.now()>end)throw Error('History fixture timed out');
    await new Promise(resolve=>setTimeout(resolve,10));
  }};
  document.getElementById('login').hidden=true;
  const root=document.createElement('div');root.className='app';
  root.style.cssText='position:fixed;inset:0;background:var(--bg);z-index:10';
  document.body.append(root);
  const select=document.createElement('select');
  for(const name of ['codex','claude','deepseek'])select.add(new Option(name,name));
  let finishOlder;
  const message=i=>({id:String(i),role:'assistant',text:'History row '+i+'\n\n'+'Long visible text. '.repeat(30)});
  const recent={session:{id:'fixture',title:'History fixture',status:'active',requests:[],capabilities:{send:true}},
    connected:true,messages:Array.from({length:40},(_,i)=>message(40+i)),history:{hasMore:true,before:'older-fixture'},files:[]};
  const view=new DesktopSessionsView({root,select,notify:text=>notices.push(text),onSelect(){},csrf:()=>'',onUnauthorized(){},
    request:async(url,body)=>{
      calls.push({url,body});if(body)throw Error('Unexpected control request');
      if(url.includes('historyBefore='))return new Promise(resolve=>finishOlder=resolve);
      if(url.includes('/detail'))return recent;
      if(url.includes('/workspace'))return {entries:[],total:0,project:'/fixture'};
      return {sessions:[{id:'fixture',title:'History fixture',backend:'code'}]};
    }});
  try{
    await view.choose('claude');await view.open('fixture');clearTimeout(view.timer);
    check(view.lastMessages.length===40,'Recent page renders before any older read');
    view.input.value='Unsent draft';
    view.messages.scrollTop=0;
    const anchor=view.messages.querySelector('.message');
    const top=anchor.getBoundingClientRect().top;
    view.messages.querySelector('.ds-history-older').click();
    await until(()=>finishOlder);
    check(view.messages.querySelector('.ds-history-older').disabled,'Older page has a single in-flight request');
    check(view.state.status==='active'&&view.input.value==='Unsent draft','Pending history preserves state and draft');
    finishOlder({session:{id:'fixture',status:'idle',requests:[{id:'expired'}]},
      messages:Array.from({length:40},(_,i)=>message(i)),history:{hasMore:false,before:null},files:[{id:'old-file',path:'old.md',reference:'old.md'}]});
    await until(()=>!view.historyBusy);
    check(view.lastMessages.length===80,'Older messages prepend without duplicates');
    check(Math.abs(view.messageNodes.get('40').node.getBoundingClientRect().top-top)<3,'Prepending preserves the visible message position');
    check(view.state.status==='active'&&view.state.requests.length===0,'Old page cannot replace live state or approvals');
    check(view.sessionFiles.some(file=>file.id==='old-file'),'Old page file references remain available');
    view.applyDetail({...recent,messages:[...recent.messages,message(80)]});
    check(view.lastMessages.length===81&&view.lastMessages[0].id==='0','Recent refresh retains loaded older messages');
    check(view.input.value==='Unsent draft','History refresh does not overwrite draft');
    check(calls.every(call=>!call.body),'All fixture requests are read-only');
    check(notices.length===0,'No pagination errors');
    return {width:innerWidth,passed:checks.length,checks};
  }finally{view.clear();root.remove();}
}
