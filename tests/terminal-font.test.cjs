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
  const button=(text,click,title)=>Object.assign(node('button','',text),{onclick:click,title});
  return {context,font:context.font,Command:context.Command,Pty:context.Pty,listeners,node,workbench:{node,button}};
}

test('one font choice reaches open PTY and command panels and persists for future panels',()=>{
  const storage=new Map(),a=tab(storage);
  const ptyPanel=Object.create(a.Pty.prototype);let fits=0;
  Object.assign(ptyPanel,{fontControl:a.font.control(a.workbench),input:{style:{}},term:{options:{fontSize:14}},layout:()=>fits++});
  const commandPanel=Object.create(a.Command.prototype);
  Object.assign(commandPanel,{fontControl:a.font.control(a.workbench),screen:{style:{}},command:{style:{},value:'draft'},prompt:{style:{}}});
  a.font.register(ptyPanel);a.font.register(commandPanel);
  const control=ptyPanel.fontControl;for(let i=14;i<20;i++)control.increase.onclick();
  assert.equal(storage.get('bridge-terminal-font-size'),'20');assert.equal(ptyPanel.term.options.fontSize,20);
  assert.equal(commandPanel.screen.style.fontSize,'20px');assert.equal(commandPanel.command.style.fontSize,'20px');
  assert.equal(commandPanel.command.value,'draft');assert.equal(fits,7);
  assert.equal(commandPanel.fontControl.value.textContent,'20px');
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

test('stepper changes exactly 1px, disables at 6 and 24, and rejects fractional values',()=>{
  const storage=new Map(),a=tab(storage),panel={fontControl:a.font.control(a.workbench),applyFontSize(size){this.size=size;a.font.paint(this.fontControl,size);}};
  a.font.register(panel);panel.fontControl.decrease.onclick();assert.equal(panel.size,13);
  a.font.set(6);assert.equal(panel.fontControl.decrease.disabled,true);assert.equal(panel.fontControl.increase.disabled,false);
  panel.fontControl.decrease.onclick();assert.equal(panel.size,6);
  a.font.set(24);assert.equal(panel.fontControl.increase.disabled,true);assert.equal(panel.fontControl.decrease.disabled,false);
  panel.fontControl.increase.onclick();assert.equal(panel.size,24);
  a.font.set(7.5);assert.equal(panel.size,24);assert.equal(storage.get('bridge-terminal-font-size'),'24');
});

test('legal historic sizes migrate without rounding and invalid stored values start at 14',()=>{
  for(const oldSize of ['12','14','16','18','20','24'])assert.equal(tab(new Map([['bridge-terminal-font-size',oldSize]])).font.size(),Number(oldSize));
  assert.equal(tab(new Map([['bridge-terminal-font-size','7']])).font.size(),7);
  for(const invalid of ['5','25','7.5','garbage'])assert.equal(tab(new Map([['bridge-terminal-font-size',invalid]])).font.size(),14);
});

test('mobile composer stays at least 16px while output uses the chosen size',()=>{
  const a=tab(new Map());
  const ptyPanel=Object.create(a.Pty.prototype);
  Object.assign(ptyPanel,{fontControl:a.font.control(a.workbench),input:{style:{}},term:{options:{}},layout(){}});
  ptyPanel.applyFontSize(6);assert.equal(ptyPanel.term.options.fontSize,6);assert.equal(ptyPanel.input.style.fontSize,'16px');
  const commandPanel=Object.create(a.Command.prototype);
  Object.assign(commandPanel,{fontControl:a.font.control(a.workbench),screen:{style:{}},command:{style:{}},prompt:{style:{}}});
  commandPanel.applyFontSize(6);assert.equal(commandPanel.screen.style.fontSize,'6px');assert.equal(commandPanel.command.style.fontSize,'16px');
});

test('disposing a terminal stops font updates without closing another terminal',()=>{
  const a=tab(new Map());
  const retired=Object.create(a.Pty.prototype),live=Object.create(a.Command.prototype);
  Object.assign(retired,{id:'existing-pty',key:'pty:x',fontControl:a.font.control(a.workbench),input:{style:{}},term:{options:{},dispose(){}},
    layout(){},workbench:{endpoint:()=>'/terminal?',request:async()=>({})},session:{},observer:{disconnect(){}}});
  Object.assign(live,{fontControl:a.font.control(a.workbench),screen:{style:{}},command:{style:{},value:'draft'},prompt:{style:{}}});
  a.font.register(retired);a.font.register(live);retired.dispose();a.font.set(18);
  assert.equal(retired.term.options.fontSize,14);assert.equal(live.screen.style.fontSize,'18px');
  assert.equal(retired.id,'existing-pty');assert.equal(live.command.value,'draft');
});
