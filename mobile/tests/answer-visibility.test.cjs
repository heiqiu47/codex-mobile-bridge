'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../shared/web/mobile-ui.js'),'utf8');

function fixture(){
  const events={},viewportEvents={},frames=new Map();let nextFrame=0;
  const timeline={scrollTop:2357,isConnected:true,contains:field=>field.scroller===timeline,getBoundingClientRect:()=>({top:100,bottom:691})};
  const visualViewport={height:844,offsetTop:0,addEventListener:(name,handler)=>viewportEvents[name]=handler};
  const document={activeElement:null,styleSheets:[{href:'https://fixture.test/style.css',cssRules:[],insertRule(){}}],
    documentElement:{classList:{contains:()=>false,add(){},toggle(){}}},
    getElementById:id=>id==='app'?{hidden:false}:id==='timeline'?timeline:null,
    querySelector:()=>null,addEventListener:(name,handler)=>events[name]=handler};
  const window={visualViewport,innerHeight:844,prompt:()=>'',addEventListener(){}};
  class MutationObserver{observe(){}}
  vm.runInNewContext(source,{URL,location:{origin:'https://fixture.test'},document,window,MutationObserver,
    requestAnimationFrame:handler=>{const id=++nextFrame;frames.set(id,handler);return id;},cancelAnimationFrame:id=>frames.delete(id)});
  const field=(kind,scroller,top,height=60)=>{
    const initialScroll=scroller.scrollTop;
    return {scroller,isConnected:true,matches:()=>true,
      closest:selector=>selector==='#approvals'&&kind==='codex'?{}:
        selector==='.wb-side-approval'&&kind==='side'?{closest:()=>scroller}:
        selector==='.ds-question'&&kind==='desktop'?{closest:()=>scroller}:null,
      getBoundingClientRect:()=>({top:top-(scroller.scrollTop-initialScroll),bottom:top+height-(scroller.scrollTop-initialScroll),height})};
  };
  // Each auxiliary area has its own scroll position; no global page scrolling is allowed.
  const area=(top=100,bottom=347)=>{const scroller={scrollTop:0,isConnected:true,getBoundingClientRect:()=>({top,bottom})};scroller.contains=field=>field.scroller===scroller;return scroller;};
  const flush=()=>{for(const [id,handler] of [...frames]){frames.delete(id);handler();}};
  return {document,events,visualViewport,viewportEvents,timeline,field,area,flush,frames};
}

test('focused Codex answer moves into the shortened timeline before typing',()=>{
  const f=fixture(),answer=f.field('codex',f.timeline,515);
  f.document.activeElement=answer;f.events.focusin({target:answer});f.flush();
  assert.equal(f.timeline.scrollTop,2357,'visible answer stays put before keyboard');
  f.timeline.getBoundingClientRect=()=>({top:100,bottom:347});f.visualViewport.height=500;
  f.viewportEvents.resize();f.flush();
  assert.equal(f.timeline.scrollTop,2597,'60px answer clears the clipped bottom by 12px');
  f.viewportEvents.resize();f.flush();assert.equal(f.timeline.scrollTop,2597,'visible answer stays put');
});

test('side and desktop answers scroll only their own containers',()=>{
  const f=fixture();
  for(const kind of ['side','desktop']){
    const scroller=f.area(),answer=f.field(kind,scroller,360);
    f.document.activeElement=answer;f.events.focusin({target:answer});f.flush();
    assert.equal(scroller.scrollTop,85);
    assert.equal(f.timeline.scrollTop,2357);
    f.events.focusout({target:answer});
  }
});

test('blur cancels late scrolling; composer and partly visible large answers stay put',()=>{
  const f=fixture(),answer=f.field('codex',f.timeline,515);
  f.timeline.getBoundingClientRect=()=>({top:100,bottom:347});f.visualViewport.height=500;
  f.document.activeElement=answer;f.events.focusin({target:answer});f.events.focusout({target:answer});f.document.activeElement=null;f.flush();
  assert.equal(f.timeline.scrollTop,2357);
  const composer=f.field('composer',f.timeline,515);f.document.activeElement=composer;f.events.focusin({target:composer});f.viewportEvents.resize();f.flush();
  assert.equal(f.timeline.scrollTop,2357);
  const large=f.field('codex',f.timeline,200,500);f.document.activeElement=large;f.events.focusin({target:large});f.flush();
  assert.equal(f.timeline.scrollTop,2357,'a partly visible tall answer is not pulled to its top');
});
