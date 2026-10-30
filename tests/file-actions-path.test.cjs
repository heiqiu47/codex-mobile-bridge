'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function fixture(){
  const body={children:[],append(node){this.children.push(node);}};
  const document={body,addEventListener(){},createElement(tag){return {tag,children:[],dataset:{},append(...nodes){this.children.push(...nodes);},setAttribute(){},addEventListener(){},showModal(){this.open=true;},close(){this.open=false;}};}};
  const context={window:{},document,BridgeI18n:{t:x=>x},setTimeout,BridgeClipboard:{async copyWithFeedback(read){context.copied=await read();}}};
  vm.runInNewContext(fs.readFileSync('web/features/workspace/file-actions.js','utf8'),context);
  return context;
}
test('file and folder menus copy target metadata and retain download URLs',async()=>{
  for(const kind of ['file','directory']){
    const c=fixture(),session={},calls=[],absolutePath='C:\\target\\中文\\item';
    const workbench={current:session,url:(s,action,path)=>'/workspace/'+action+'?path='+path,request:async url=>{calls.push(url);return {absolutePath};}};
    c.window.BridgeFileActions.menu(workbench,session,{kind,name:'item',path:'中文/item'});
    const dialog=c.document.body.children[0],download=dialog.children.find(n=>n.tag==='a'),copy=dialog.children.find(n=>n.tag==='button');
    assert.equal(download.href,'/workspace/download?path=中文/item&explicit=1'+(kind==='directory'?'&archive=1':''));
    await copy.onclick();assert.equal(c.copied,absolutePath);assert.deepEqual(calls,['/workspace/info?path=中文/item']);
  }
});
test('a changed workspace cannot copy a stale target path',async()=>{
  const c=fixture(),session={},workbench={current:session,url:()=>'/info',request:async()=>{workbench.current={};return {absolutePath:'/secret'};}};
  c.window.BridgeFileActions.menu(workbench,session,{kind:'file',name:'item',path:'item'});
  await assert.rejects(c.document.body.children[0].children.find(n=>n.tag==='button').onclick());
  assert.equal(c.copied,undefined);
});

test('reference waits for authorized info and a changed session cannot receive it',async()=>{
 const c=fixture(),session={},references=[],composer={disabled:false},workbench={composer,current:session,url:()=>'/workspace/info',notify(){},request:async()=>({name:'file',path:'file',kind:'file'}),referenceFile:(s,info)=>{references.push(info);return true;}};
 c.window.BridgeFileActions.menu(workbench,session,{kind:'file',name:'file',path:'file'});
 const button=c.document.body.children[0].children.find(n=>n.textContent==='引用到消息');await button.onclick();assert.equal(references.length,1);
 workbench.current=session;c.window.BridgeFileActions.menu(workbench,session,{kind:'file',name:'file',path:'file'});
 workbench.request=async()=>{workbench.current={};return {name:'secret',path:'secret',kind:'file'};};
 await c.document.body.children[1].children.find(n=>n.textContent==='引用到消息').onclick();assert.equal(references.length,1);
});
