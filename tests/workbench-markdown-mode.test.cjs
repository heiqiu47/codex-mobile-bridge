'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function fixture(defaultMode='reading'){
  let value=defaultMode;const scopes=[];
  const context={window:{BridgeMermaidCards:{createScope(){const scope={};scopes.push(scope);return scope;},clearScope(scope){if(scope)scope.disposed=true;}}},localStorage:{getItem:()=>value,setItem:(key,next)=>{value=next;}},BridgeSourceView:{create:info=>({info,body:{scrollTop:0,scrollLeft:0},querySelector(){return this.body;}}),locate:(node,start,end)=>node.location={start,end}},renderMarkdown:(node,text)=>node.replaceChildren({text}),BridgeI18n:{t:x=>x}};
  vm.createContext(context);vm.runInContext(fs.readFileSync('web/features/workspace/workbench.js','utf8'),context);
  const wb=Object.create(vm.runInContext('Workbench',context).prototype);
  wb.node=()=>({children:[],append(...nodes){this.children.push(...nodes);}});
  wb.button=(text,onclick)=>({text,onclick,setAttribute(key,value){this[key]=value;}});wb.scrollPositions=new WeakMap();
  const content={scrollTop:0,scrollLeft:0,replaceChildren(...nodes){this.children=nodes;this.firstChild=nodes[0];this.scrollTop=0;}};
  return {wb,content,scopes,context,defaultMode:()=>value};
}
test('Markdown mode preserves positions, raw source and global preference',()=>{
  const f=fixture(),tab={id:'file:a.md'},text='# raw\r\n```mermaid\ngraph TD\n```';
  const ui=f.wb.markdownPreview({key:'a'},tab,f.content,{name:'a.md',text});
  assert.equal(f.content.firstChild.text,text);f.content.scrollTop=71;f.content.scrollLeft=9;
  ui.modes.children[1].onclick();assert.equal(f.scopes[0].disposed,true);assert.equal(f.content.firstChild.info.text,text);assert.equal(f.defaultMode(),'source');
  f.content.scrollTop=32;const source=f.content.firstChild;source.wrap=true;source.body.scrollLeft=147;source.body.scrollTop=24;ui.modes.children[0].onclick();assert.equal(f.content.scrollTop,71);assert.equal(f.content.scrollLeft,9);
  ui.modes.children[1].onclick();assert.equal(f.content.scrollTop,32);assert.equal(f.content.firstChild,source);assert.equal(source.wrap,true);assert.equal(source.body.scrollLeft,147);assert.equal(source.body.scrollTop,24);tab.markdown.dispose();
});
test('reference location forces source without overwriting global reading default',()=>{
  const f=fixture(),tab={id:'file:a.md',sourceLocation:{start:3,end:5}};
  f.wb.markdownPreview({key:'a'},tab,f.content,{name:'a.md',text:'raw'});tab.showSourceLocation();
  assert.equal(f.content.firstChild.info.text,'raw');assert.equal(f.content.firstChild.location.start,3);assert.equal(f.defaultMode(),'reading');assert.equal(f.scopes.length,0);
});
