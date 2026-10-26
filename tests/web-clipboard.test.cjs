'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/features/chat/message-actions.js'),'utf8');
function fixture({clipboard,legacy=false,items=true}={}){
 const copied=[],errors=[],timers=[],events={};let document,selection=[];
 class Node{
  constructor(tag){this.tagName=tag;this.children=[];this.style={};this.value='';this.textContent='';this.disabled=false;this.isConnected=false;this.selectionStart=2;this.selectionEnd=4;this.selectionDirection='backward';}
  append(...nodes){for(const n of nodes){n.parent=this;n.isConnected=true;this.children.push(n);}}
  remove(){this.parent?.children.splice(this.parent.children.indexOf(this),1);this.isConnected=false;}
  closest(){return this.parent?.tagName==='dialog'?this.parent:null;}
  focus(){document.activeElement=this;}select(){document.activeElement=this;this.selectionStart=0;this.selectionEnd=this.value.length;}
  setSelectionRange(a,b,d){this.selectionStart=a;this.selectionEnd=b;this.selectionDirection=d;}
  setAttribute(){}showModal(){this.open=true;}close(){this.open=false;this.onclose?.();}
 }
 document={addEventListener(name,fn){(events[name]||=[]).push(fn);},removeEventListener(name,fn){events[name]=(events[name]||[]).filter(value=>value!==fn);},body:new Node('body'),createElement:t=>new Node(t),dispatchEvent:e=>errors.push(e.detail),getSelection:()=>({rangeCount:selection.length,getRangeAt:i=>selection[i],removeAllRanges(){selection=[];},addRange:r=>selection.push(r)}),execCommand:command=>{assert.equal(command,'copy');if(legacy)copied.push({text:document.activeElement.value,parent:document.activeElement.parent});return legacy;}};
 const draft=new Node('textarea');draft.value='keep my draft';document.body.append(draft);document.activeElement=draft;
 const button=new Node('button');button.textContent='Copy';document.body.append(button);
 const context=vm.createContext({window:{},document,navigator:{clipboard},ClipboardItem:items?class{constructor(data){this.data=data;}}:undefined,Blob,setTimeout:fn=>timers.push(fn),CustomEvent:class{constructor(type,init){this.type=type;this.detail=init.detail;}}});
 vm.runInContext(source,context);
 return {copyWithFeedback:(getText,notify)=>context.window.BridgeClipboard.copyWithFeedback(getText,button,notify),copy:getText=>context.window.BridgeClipboard.copy(getText,button),document,button,draft,copied,errors,timers,dialog:()=>document.body.children.find(n=>n.tagName==='dialog')};
}
test('ready text reaches Clipboard API within the click, without waiting for a microtask',async()=>{
 const writes=[],ui=fixture({clipboard:{writeText:text=>{writes.push(text);return Promise.resolve();}}});
 const pending=ui.copy(()=> '中文\n🙂');assert.deepEqual(writes,['中文\n🙂']);await pending;assert.equal(ui.button.textContent,'已复制');assert.equal(ui.dialog(),undefined);
});
test('plain HTTP copies synchronously and restores draft focus and selection',async()=>{
 const ui=fixture({legacy:true}),before=ui.document.body.children.length;
 const pending=ui.copy(()=> 'HTTP 中文\nnext');assert.equal(ui.copied.length,1);await pending;
 assert.equal(ui.copied[0].text,'HTTP 中文\nnext');assert.equal(ui.document.activeElement,ui.draft);assert.equal(ui.draft.value,'keep my draft');assert.deepEqual([ui.draft.selectionStart,ui.draft.selectionEnd,ui.draft.selectionDirection],[2,4,'backward']);assert.equal(ui.document.body.children.length,before);assert.equal(ui.dialog(),undefined);
});
test('delayed full text reserves ClipboardItem write during the click and reads only once',async()=>{
 let resolve,read=0;const writes=[],ui=fixture({clipboard:{write:items=>{writes.push(items);return items[0].data['text/plain'].then(()=>{});}}});
 const pending=ui.copy(()=>{read++;return new Promise(r=>resolve=r);});assert.equal(writes.length,1);
 resolve('full source\n中文');await pending;assert.equal(await (await writes[0][0].data['text/plain']).text(),'full source\n中文');assert.equal(read,1);assert.equal(ui.button.textContent,'已复制');
});
test('Clipboard API denial falls back to selection copy within an open dialog',async()=>{
 const ui=fixture({clipboard:{writeText:()=>Promise.reject(Error('NotAllowed'))},legacy:true});
 const modal=ui.document.createElement('dialog');ui.document.body.append(modal);modal.open=true;ui.button.remove();modal.append(ui.button);
 await ui.copy(()=> 'diagram source');assert.equal(ui.copied[0].parent,modal);assert.equal(modal.children.length,1);assert.equal(ui.button.textContent,'已复制');
});
test('only denied automatic copying shows the selectable dialog with a fresh-click retry',async()=>{
 const clipboard={writeText:()=>Promise.reject(Error('denied'))},ui=fixture({clipboard});await ui.copy(()=> 'ready text');
 const dialog=ui.dialog();assert.ok(dialog);const textarea=dialog.children.find(n=>n.tagName==='textarea');assert.equal(textarea.value,'ready text');assert.equal(ui.button.textContent,'Copy');
 const actions=dialog.children.find(n=>n.className==='copy-dialog-actions'),retry=actions.children[0];clipboard.writeText=text=>{assert.equal(text,'ready text');return Promise.resolve();};await retry.onclick();assert.equal(ui.dialog(),undefined);assert.equal(ui.button.textContent,'已复制');
});
test('failed source reads never copy partial data or show success',async()=>{
 const ui=fixture({clipboard:{write:items=>items[0].data['text/plain'].then(()=>{})}});await ui.copy(()=>Promise.reject(Error('source changed')));
 assert.deepEqual(ui.errors,['source changed']);assert.equal(ui.dialog(),undefined);assert.equal(ui.button.disabled,false);assert.equal(ui.button.textContent,'Copy');
});
test('HTTP retry uses the fresh click synchronously if the first copy was blocked',async()=>{
 const ui=fixture();await ui.copy(()=> 'loaded text');const dialog=ui.dialog();
 const retry=dialog.children.find(n=>n.className==='copy-dialog-actions').children[0];let copied=false;
 ui.document.execCommand=()=>{copied=true;return true;};
 const pending=retry.onclick();assert.equal(copied,true);await pending;assert.equal(ui.dialog(),undefined);assert.equal(ui.button.textContent,'已复制');
});
test('older browsers can copy resolved text without ClipboardItem and ignore duplicate clicks',async()=>{
 let resolve,reads=0;const writes=[],ui=fixture({items:false,clipboard:{writeText:text=>{writes.push(text);return Promise.resolve();}}});
 const pending=ui.copy(()=>{reads++;return new Promise(r=>resolve=r);});await ui.copy(()=>{reads++;return 'wrong';});resolve('complete');await pending;assert.deepEqual(writes,['complete']);assert.equal(reads,1);
});

test('acknowledged browser copying sends one success notification',async()=>{
 const ui=fixture({clipboard:{writeText:()=>Promise.resolve()}}),notices=[];
 await ui.copyWithFeedback(()=> 'ready',message=>notices.push(message));assert.deepEqual(notices,['已复制']);
});
test('manual browser fallback does not notify until its fresh-click retry succeeds',async()=>{
 const clipboard={writeText:()=>Promise.reject(Error('denied'))},ui=fixture({clipboard}),notices=[];
 await ui.copyWithFeedback(()=> 'ready',message=>notices.push(message));assert.deepEqual(notices,[]);
 clipboard.writeText=()=>Promise.resolve();const retry=ui.dialog().children.find(node=>node.className==='copy-dialog-actions').children[0];
 await retry.onclick();assert.deepEqual(notices,['已复制']);
});
