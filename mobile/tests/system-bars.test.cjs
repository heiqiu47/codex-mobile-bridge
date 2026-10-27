'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../shared/web/mobile-system-bars.js'),'utf8');
function page(){
  const events={},frames=[],calls=[],observed=[];
  const html={color:'rgb(255, 255, 255)'},body={color:'rgb(10, 20, 30)',parentElement:html};
  const top={color:'rgb(30, 40, 50)',parentElement:body},bottom={color:'rgb(240, 241, 242)',parentElement:body};
  for(const element of [html,body,top,bottom]){element.closest=()=>null;element.isConnected=true;}
  let hit=null,dialogs=[],now=0;
  let accepted=true,observer;
  const document={documentElement:html,body,getElementById:()=>body,querySelectorAll:()=>dialogs,querySelector:()=>dialogs[0]||null,elementFromPoint:(_x,y)=>typeof hit==='function'?hit():hit||(y===1?top:bottom),addEventListener:(name,callback)=>events[name]=callback};
  const window={addEventListener:(name,callback)=>events[name]=callback,prompt:(name,value)=>{calls.push([name,JSON.parse(value)]);return accepted?'saved':null;}};window.top=window;
  const context=vm.createContext({window,document,innerWidth:390,innerHeight:800,performance:{now:()=>now},getComputedStyle:(element,pseudo)=>({backgroundColor:pseudo==='::backdrop'?(element.backdrop||'rgba(0, 0, 0, 0)'):element.color,opacity:typeof element.backdropOpacity==='function'?element.backdropOpacity(now):element.backdropOpacity??'1',animationDuration:'0.2s'}),requestAnimationFrame:callback=>frames.push(callback),MutationObserver:class{constructor(callback){observer=callback;}observe(node,options){observed.push({node,options});}}});
  vm.runInContext(source,context);
  return {calls,events,top,bottom,observed,hit:(element,open=element?.getBoundingClientRect?[element]:[])=>{hit=element;dialogs=open;},flush:()=>{let count=0;while(frames.length){if(++count>100)throw Error('animation sampler never stopped');now+=16;frames.shift()(now);}},accept:value=>{accepted=value;},change:()=>observer([])};
}
test('shared theme sampler sends top and bottom colors once until they change',()=>{
  const ui=page();ui.flush();assert.deepEqual(ui.calls[0][1],{top:'#1e2832',bottom:'#f0f1f2'});
  ui.events.resize();ui.change();ui.flush();assert.equal(ui.calls.length,1);
  ui.bottom.color='rgb(0, 0, 0)';ui.events.resize();ui.flush();assert.equal(ui.calls[1][1].bottom,'#000000');
  assert.ok(ui.observed.every(value=>!value.options.subtree));
});
test('theme sampler retries after a native rejection and foreground return',()=>{
  const ui=page();ui.accept(false);ui.flush();assert.equal(ui.calls.length,1);
  ui.accept(true);ui.events.focus();ui.events.visibilitychange();ui.flush();assert.equal(ui.calls.length,2);
  ui.events.focus();ui.flush();assert.equal(ui.calls.length,2);
});
test('transparent elements use their opaque parent background',()=>{
  const ui=page();ui.top.color='rgba(255, 255, 255, 0)';ui.flush();assert.equal(ui.calls[0][1].top,'#0a141e');
});
function dialog(top,bottom){
 const node={color:'rgb(200, 210, 220)',isConnected:true,getBoundingClientRect:()=>({left:0,right:390,top,bottom})};
 node.closest=()=>node;node.contains=element=>element===node;return node;
}
test('bottom sheet preserves the page status color and colors only the covered bottom edge',()=>{
 const ui=page();ui.flush();ui.hit(dialog(400,800));ui.change();ui.flush();
 assert.deepEqual(ui.calls.at(-1)[1],{top:'#1e2832',bottom:'#c8d2dc'});
 ui.top.color='rgb(0, 0, 0)';ui.change();ui.flush();assert.equal(ui.calls.at(-1)[1].top,'#000000');
 ui.hit(null);ui.change();ui.flush();assert.deepEqual(ui.calls.at(-1)[1],{top:'#000000',bottom:'#f0f1f2'});
});
test('centered dialogs preserve both page edges while fullscreen dialogs color both edges',()=>{
 const ui=page();ui.flush();ui.hit(dialog(200,600));ui.change();ui.flush();assert.equal(ui.calls.length,1);
 ui.hit(dialog(0,800));ui.change();ui.flush();assert.deepEqual(ui.calls.at(-1)[1],{top:'#c8d2dc',bottom:'#c8d2dc'});
});
test('backdrop hits returning the page root or null preserve the page edge colors',()=>{
 for(const hit of [()=>({color:'rgb(255, 255, 255)',closest:()=>null}),()=>null]){
  const ui=page();ui.flush();ui.hit(hit,[dialog(400,800)]);ui.change();ui.flush();
  assert.deepEqual(ui.calls.at(-1)[1],{top:'#1e2832',bottom:'#c8d2dc'});
 }
});
test('bottom sheet dims status bar by its actual backdrop and restores it on close',()=>{
 const ui=page();ui.flush();const sheet=dialog(400,800);sheet.backdrop='rgba(0, 0, 0, 0.333333)';
 ui.hit(sheet);ui.change();ui.flush();
 assert.deepEqual(ui.calls.at(-1)[1],{top:'#141b21',bottom:'#c8d2dc'});
 ui.top.color='rgb(240, 240, 240)';ui.change();ui.flush();assert.equal(ui.calls.at(-1)[1].top,'#a0a0a0');
 ui.hit(null);ui.change();ui.flush();assert.equal(ui.calls.at(-1)[1].top,'#f0f0f0');
});
test('centered modal dims both uncovered edges using the backdrop opacity',()=>{
 const ui=page();ui.flush();const modal=dialog(200,600);modal.backdrop='rgba(0, 0, 0, 0.5)';
 ui.hit(modal);ui.change();ui.flush();assert.deepEqual(ui.calls.at(-1)[1],{top:'#0f1419',bottom:'#787979'});
});
test('animated backdrop updates native colors at a bounded rate and stops sampling afterward',()=>{
 const ui=page();ui.flush();const sheet=dialog(400,800);sheet.matches=()=>true;
 sheet.backdrop='rgba(0, 0, 0, 0.5)';sheet.backdropOpacity=time=>String(Math.min(1,time/200));
 ui.hit(sheet);ui.events.animationstart({target:sheet,pseudoElement:'::backdrop'});ui.flush();
 assert.equal(ui.calls.at(-1)[1].top,'#0f1419');
 assert.ok(ui.calls.length>3&&ui.calls.length<=10,'native updates are capped during the 200ms animation');
 const count=ui.calls.length;ui.flush();assert.equal(ui.calls.length,count);
});
