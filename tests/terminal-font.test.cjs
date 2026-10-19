const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/features/workspace/command-terminal-panel.js'),'utf8');
const pty=fs.readFileSync(path.join(__dirname,'../web/features/workspace/terminal-panel.js'),'utf8');

function tab(storage){
  const listeners={};
  const context=vm.createContext({BridgeI18n:{t:value=>value},document:{removeEventListener(){}},clearTimeout(){},sessionStorage:{removeItem(){}},localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},
    addEventListener:(type,fn)=>listeners[type]=fn});
  vm.runInContext(source+';globalThis.font=TerminalFont;globalThis.Command=CommandTerminalPanel;',context);
  vm.runInContext(pty+';globalThis.Pty=TerminalPanel;',context);
  const node=(tag,cls,text)=>({tag,cls,textContent:text||'',dataset:{},style:{},children:[],setAttribute(){},append(...items){this.children.push(...items);}});
  return {context,font:context.font,Command:context.Command,Pty:context.Pty,listeners,node};
}

test('one font choice reaches open PTY and command panels and persists for future panels',()=>{
  const storage=new Map(),a=tab(storage);
  const ptyPanel=Object.create(a.Pty.prototype);let fits=0;
  Object.assign(ptyPanel,{fontSelect:{},input:{style:{}},term:{options:{fontSize:14}},layout:()=>fits++});
  const commandPanel=Object.create(a.Command.prototype);
  Object.assign(commandPanel,{fontSelect:{},screen:{style:{}},command:{style:{},value:'draft'},prompt:{style:{}}});
  a.font.register(ptyPanel);a.font.register(commandPanel);
  const control=a.font.control({node:a.node});control.select.value='20';control.select.onchange();
  assert.equal(storage.get('bridge-terminal-font-size'),'20');assert.equal(ptyPanel.term.options.fontSize,20);
  assert.equal(commandPanel.screen.style.fontSize,'20px');assert.equal(commandPanel.command.style.fontSize,'20px');
  assert.equal(commandPanel.command.value,'draft');assert.equal(fits,2);
  const fresh=tab(storage);assert.equal(fresh.font.size(),20);
  const future={applyFontSize(size){this.size=size;}};fresh.font.register(future);assert.equal(future.size,20);
  a.font.unregister(ptyPanel);a.font.set(24);assert.equal(ptyPanel.term.options.fontSize,20);
});

test('storage event synchronizes browser tabs and invalid values restore the safe default',()=>{
  const storage=new Map(),a=tab(storage),b=tab(storage);
  const aPanel={applyFontSize(size){this.size=size;}},bPanel={applyFontSize(size){this.size=size;}};
  a.font.register(aPanel);b.font.register(bPanel);
  a.font.set(18);b.listeners.storage({key:'bridge-terminal-font-size',newValue:'18'});
  assert.equal(bPanel.size,18);
  b.listeners.storage({key:'other-setting',newValue:'24'});assert.equal(bPanel.size,18);
  b.listeners.storage({key:'bridge-terminal-font-size',newValue:'999'});assert.equal(bPanel.size,14);
  b.font.set('999');assert.equal(bPanel.size,14);assert.equal(storage.get('bridge-terminal-font-size'),'18');
  b.listeners.storage({key:'bridge-terminal-font-size',newValue:null});assert.equal(bPanel.size,14);
});

test('mobile composer stays at least 16px while output uses the chosen size',()=>{
  const a=tab(new Map());
  const ptyPanel=Object.create(a.Pty.prototype);
  Object.assign(ptyPanel,{fontSelect:{},input:{style:{}},term:{options:{}},layout(){}});
  ptyPanel.applyFontSize(12);assert.equal(ptyPanel.term.options.fontSize,12);assert.equal(ptyPanel.input.style.fontSize,'16px');
  const commandPanel=Object.create(a.Command.prototype);
  Object.assign(commandPanel,{fontSelect:{},screen:{style:{}},command:{style:{}},prompt:{style:{}}});
  commandPanel.applyFontSize(12);assert.equal(commandPanel.screen.style.fontSize,'12px');assert.equal(commandPanel.command.style.fontSize,'16px');
});

test('disposing a terminal stops font updates without closing another terminal',()=>{
  const a=tab(new Map());
  const retired=Object.create(a.Pty.prototype),live=Object.create(a.Command.prototype);
  Object.assign(retired,{id:'existing-pty',key:'pty:x',fontSelect:{},input:{style:{}},term:{options:{},dispose(){}},
    layout(){},workbench:{endpoint:()=>'/terminal?',request:async()=>({})},session:{},observer:{disconnect(){}}});
  Object.assign(live,{fontSelect:{},screen:{style:{}},command:{style:{},value:'draft'},prompt:{style:{}}});
  a.font.register(retired);a.font.register(live);retired.dispose();a.font.set(18);
  assert.equal(retired.term.options.fontSize,14);assert.equal(live.screen.style.fontSize,'18px');
  assert.equal(retired.id,'existing-pty');assert.equal(live.command.value,'draft');
});
