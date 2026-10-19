const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

function fixture(){
  const timers=new Map();let next=0,uid=0;
  const context=vm.createContext({BridgeI18n:{t:s=>s},BridgeHost:{hasNativeLayout:()=>false},BridgeLayout:{prefersTouchInput:()=>true,isCompactViewport:()=>true},navigator:{userAgent:'iPhone Mobile'},
    uuid:()=>String(++uid),document:{hidden:false,body:{},querySelector:()=>null,activeElement:null},window:{getSelection:()=>({toString:()=>''})},
    setTimeout:(fn,ms)=>{timers.set(++next,{fn,ms});return next;},clearTimeout:id=>timers.delete(id)});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/features/workspace/terminal-panel.js'),'utf8')+';globalThis.Panel=TerminalPanel;',context);
  const requests=[];
  const node=(tag,cl,text)=>({tag,cl,textContent:text||'',hidden:false,children:[],append(...values){this.children.push(...values);},replaceChildren(){this.children=[];}});
  const input={value:'',selectionStart:0,selectionEnd:0,focus(){this.focused=true;},setRangeText(value,start,end){this.value=this.value.slice(0,start)+value+this.value.slice(end);this.selectionStart=this.selectionEnd=start+value.length;this.onselect?.();}};
  const panel=Object.create(context.Panel.prototype);
  Object.assign(panel,{id:'pty-id',running:true,disposed:false,operations:[],completionVersion:0,composing:false,input,
    completions:node(),status:node(),retry:node(),send:node(),term:{options:{},focus(){this.focused=true;}},tab:{body:{contains:()=>false}},session:{},
    workbench:{node,button:(label,click)=>Object.assign(node('button','',label),{click}),isVisible:()=>true,request:(url,body)=>{requests.push(body);return Promise.resolve({});}},url:()=>'/terminal?mode=pty'});
  return {panel,requests,timers,context,node};
}
async function tick(){await new Promise(resolve=>setImmediate(resolve));}

test('short keyboard burst batches in order and retains inputId after uncertain response',async()=>{
  const f=fixture();let calls=0;
  f.panel.workbench.request=async(url,body)=>{f.requests.push({...body});if(++calls===1)throw Error('lost acknowledgement');return {};};
  f.panel.enqueue('a');f.panel.enqueue('😀');f.panel.enqueue('b');
  assert.equal(f.panel.operations.length,1);assert.equal(f.panel.operations[0].data,'a😀b');
  await f.panel.flush();assert.equal(f.panel.inputError,true);
  const id=f.panel.operations[0].id;f.panel.inputError=false;await f.panel.flush();
  assert.deepEqual(f.requests.map(r=>r.inputId),[id,id]);assert.equal(f.panel.operations.length,0);
});

test('continuous typing flushes from the first key rather than postponing the batch',async()=>{
  const f=fixture();f.panel.enqueue('a');const timer=f.panel.flushTimer;
  for(let i=0;i<20;i++)f.panel.enqueue('b');
  assert.equal(f.panel.flushTimer,timer);assert.equal(f.timers.size,1);
  const scheduled=f.timers.get(timer);assert.equal(scheduled.ms,12);scheduled.fn();await tick();
  assert.equal(f.requests[0].data,'a'+'b'.repeat(20));
});

test('input waits for the latest pending resize before reaching the PTY',async()=>{
  const f=fixture();let finishResize;
  f.panel.workbench.request=async(url,body)=>{
    f.requests.push({...body});
    if(body.action==='resize')return new Promise(resolve=>finishResize=resolve);
    return {};
  };
  f.panel.queueResize(90,24);f.panel.queueResize(120,32);f.panel.enqueue('DIRECT_ok');
  const pending=f.panel.flush();await tick();
  assert.deepEqual(f.requests.map(item=>item.action),['resize']);
  assert.deepEqual([f.requests[0].cols,f.requests[0].rows],[120,32]);
  finishResize({});await pending;
  assert.deepEqual(f.requests.map(item=>item.action),['resize','input']);
  assert.equal(f.requests[1].data,'DIRECT_ok');
});

test('flush checks the current layout before sending its first input',async()=>{
  const f=fixture();f.panel.layout=()=>f.panel.queueResize(132,39);
  f.panel.workbench.request=async(url,body)=>{f.requests.push({...body});return {};};
  f.panel.enqueue('DIRECT_ok');await f.panel.flush();
  assert.deepEqual(f.requests.map(item=>item.action),['resize','input']);
  assert.deepEqual([f.requests[0].cols,f.requests[0].rows],[132,39]);
});

test('large 6px terminal fit stays within PTY limits before input',async()=>{
  const f=fixture();f.panel.screen={clientWidth:2560,clientHeight:1200};f.panel.tab.body.classList={toggle(){}};
  f.panel.fit={proposeDimensions:()=>({cols:910,rows:380})};
  Object.assign(f.panel.term,{cols:80,rows:24,resize(cols,rows){this.cols=cols;this.rows=rows;f.panel.queueResize(cols,rows);}});
  f.panel.workbench.request=async(url,body)=>{f.requests.push({...body});return {};};
  f.panel.enqueue('x');await f.panel.flush();
  assert.deepEqual(f.requests.map(item=>item.action),['resize','input']);
  assert.deepEqual([f.requests[0].cols,f.requests[0].rows],[500,300]);
  assert.equal(f.panel.term.cols,500);assert.equal(f.panel.term.rows,300);
  f.panel.fit.proposeDimensions=()=>({cols:1,rows:0});f.panel.layout();
  assert.equal(f.panel.term.cols,2);assert.equal(f.panel.term.rows,2);
});

test('a closed or restarted tab cannot send after waiting for resize',async()=>{
  for(const change of ['disposed','restarting','new-id']){
    const f=fixture();let finishResize;
    f.panel.workbench.request=async(url,body)=>{f.requests.push({...body});if(body.action==='resize')return new Promise(resolve=>finishResize=resolve);return {};};
    f.panel.queueResize(90,25);f.panel.enqueue('old input');const pending=f.panel.flush();await tick();
    if(change==='new-id')f.panel.id='replacement';else f.panel[change]=true;
    finishResize({});await pending;
    assert.deepEqual(f.requests.map(item=>item.action),['resize'],change);
  }
});

test('failed resize keeps input unsent and retry uses the same pending input',async()=>{
  const f=fixture();let fail=true;
  f.panel.workbench.request=async(url,body)=>{f.requests.push({...body});if(body.action==='resize'&&fail){fail=false;throw Error('resize failed');}return {};};
  f.panel.queueResize(100,30);f.panel.enqueue('x');const id=f.panel.operations[0].id;
  await f.panel.flush();assert.equal(f.panel.inputError,true);assert.deepEqual(f.requests.map(item=>item.action),['resize']);
  assert.equal(f.panel.operations[0].id,id);f.panel.inputError=false;await f.panel.flush();
  assert.deepEqual(f.requests.map(item=>item.action),['resize','resize','input']);assert.equal(f.requests[2].inputId,id);
});

test('single completion changes only the mobile draft and never sends input',async()=>{
  const f=fixture();f.panel.input.value='echo "😀/fo"';f.panel.input.selectionStart=f.panel.input.selectionEnd=12;
  f.panel.input.onselect=()=>f.panel.selectionChanged();
  f.panel.workbench.request=async(url,body)=>{f.requests.push(body);return {replaceStart:9,replaceEnd:11,candidates:[{label:'foo',insertText:'foo',isDirectory:false}]};};
  await f.panel.complete();
  assert.equal(f.panel.input.value,'echo "😀/foo"');assert.equal(f.requests[0].action,'complete');assert.equal(f.requests[0].selectionStart,12);
  assert.equal(f.panel.operations.length,0);
});

test('multiple, empty and stale completions preserve draft until a current choice',async()=>{
  const f=fixture();f.panel.input.value='cd ab';f.panel.input.selectionStart=f.panel.input.selectionEnd=5;
  f.panel.workbench.request=async()=>({replaceStart:3,replaceEnd:5,candidates:[{label:'abc/',insertText:'abc/'},{label:'abd/',insertText:'abd/'}],truncated:true});
  await f.panel.complete();assert.equal(f.panel.input.value,'cd ab');assert.equal(f.panel.completions.hidden,false);
  f.panel.completions.children[1].click();assert.equal(f.panel.input.value,'cd abc/');assert.equal(f.panel.operations.length,0);
  f.panel.workbench.request=async()=>({replaceStart:3,replaceEnd:7,candidates:[]});await f.panel.complete();
  assert.equal(f.panel.input.value,'cd abc/');assert.equal(f.panel.completions.children[0].textContent,'没有匹配的路径');
  let finish;f.panel.workbench.request=()=>new Promise(resolve=>finish=resolve);
  const pending=f.panel.complete();f.panel.input.value='edited';f.panel.clearCompletion();finish({replaceStart:0,replaceEnd:2,candidates:[{insertText:'bad'}]});await pending;
  assert.equal(f.panel.input.value,'edited');
});

test('late completion failures from another tab or edited draft do not overwrite status',async()=>{
  const f=fixture();f.panel.input.value='cd x';f.panel.input.selectionStart=f.panel.input.selectionEnd=4;
  let reject,visible=true;f.panel.workbench.isVisible=()=>visible;
  f.panel.workbench.request=()=>new Promise((resolve,no)=>reject=no);
  let pending=f.panel.complete();visible=false;reject(Error('stale tab'));await pending;assert.equal(f.panel.status.textContent,'');
  visible=true;pending=f.panel.complete();f.panel.input.value='cd y';reject(Error('stale draft'));await pending;assert.equal(f.panel.status.textContent,'');
});

test('pending completion shows local feedback and duplicate Tab shares one request',async()=>{
  const f=fixture();f.panel.input.value='cd src';f.panel.input.selectionStart=f.panel.input.selectionEnd=6;
  let finish,calls=0;f.panel.workbench.request=()=>{calls++;return new Promise(resolve=>finish=resolve);};
  const pending=f.panel.complete();await f.panel.complete();
  assert.equal(calls,1);assert.equal(f.panel.completions.children[0].textContent,'正在补全…');
  finish({replaceStart:3,replaceEnd:6,candidates:[{label:'src/',insertText:'src/'}]});await pending;
  assert.equal(f.panel.input.value,'cd src/');assert.equal(f.panel.completions.hidden,true);
});

test('delayed unchanged select events preserve pending result and visible candidates',async()=>{
  const f=fixture();f.panel.input.value='cd tar';f.panel.input.selectionStart=f.panel.input.selectionEnd=6;
  let finish;f.panel.workbench.request=()=>new Promise(resolve=>finish=resolve);
  const pending=f.panel.complete(),version=f.panel.completionVersion;
  f.panel.selectionChanged();assert.equal(f.panel.completionVersion,version);
  finish({replaceStart:3,replaceEnd:6,candidates:[{label:'target/',insertText:'target/'},{label:'tasks/',insertText:'tasks/'}]});await pending;
  assert.equal(f.panel.completions.hidden,false);
  f.panel.selectionChanged();assert.equal(f.panel.completions.hidden,false);
  f.panel.input.selectionStart=f.panel.input.selectionEnd=5;f.panel.selectionChanged();
  assert.equal(f.panel.completions.hidden,true);
});

test('mobile landscape and iPad keep composer while narrow touch laptop stays direct',()=>{
  const f=fixture();f.context.BridgeLayout.isCompactViewport=()=>false;assert.equal(f.panel.mobile(),true);
  f.context.navigator={userAgent:'Macintosh',platform:'MacIntel',maxTouchPoints:5};assert.equal(f.panel.mobile(),true);
  f.context.navigator={userAgent:'Windows NT',platform:'Win32',maxTouchPoints:10};assert.equal(f.panel.mobile(),false);
});

test('desktop focus is purposeful and never steals selection, dialog, editor or IME',()=>{
  const f=fixture();f.context.navigator.userAgent='Desktop';
  assert.equal(f.panel.mobile(),false,'narrow touch-capable desktop keeps direct input');
  f.panel.focusOnSelect();assert.equal(f.panel.term.focused,true);
  f.panel.term.focused=false;f.panel.composing=true;f.panel.focusOnSelect();assert.equal(f.panel.term.focused,false);
  f.panel.composing=false;f.context.document.activeElement={matches:()=>true};f.panel.focusOnSelect();assert.equal(f.panel.term.focused,false);
  f.context.document.activeElement=null;f.context.window.getSelection=()=>({toString:()=> 'selected'});f.panel.focusOnSelect();assert.equal(f.panel.term.focused,false);
  f.context.window.getSelection=()=>({toString:()=>''});f.context.document.querySelector=()=>({});f.panel.focusOnSelect();assert.equal(f.panel.term.focused,false);
});

test('desktop shortcut and clear screen restore input focus without stealing an editor',()=>{
  const f=fixture();f.context.navigator.userAgent='Windows NT';f.panel.term.clear=()=>{};
  f.panel.shortcut('Tab','\t');assert.equal(f.panel.term.focused,true);assert.equal(f.panel.operations[0].data,'\t');
  f.panel.term.focused=false;f.panel.clearScreen();assert.equal(f.panel.term.focused,true);
  f.panel.term.focused=false;f.context.document.activeElement={matches:()=>true};f.panel.shortcut('Esc','\x1b');assert.equal(f.panel.term.focused,false);
});
