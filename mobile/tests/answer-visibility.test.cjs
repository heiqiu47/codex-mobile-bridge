'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../shared/web/mobile-ui.js'),'utf8');

function fixture(){
  const events={},viewportEvents={},timers=new Map();let nextTimer=0,now=0;
  const emitter=target=>{const listeners=new Map();target.addEventListener=(name,handler)=>listeners.set(name,handler);
    target.removeEventListener=(name,handler)=>{if(listeners.get(name)===handler)listeners.delete(name);};
    target.emit=name=>listeners.get(name)?.();target.listenerCount=()=>listeners.size;return target;};
  const timeline=emitter({scrollTop:2357,isConnected:true,contains:field=>field.scroller===timeline,getBoundingClientRect:()=>({top:100,bottom:691})});
  const visualViewport={height:844,offsetTop:0,addEventListener:(name,handler)=>viewportEvents[name]=handler};
  const document={activeElement:null,styleSheets:[{href:'https://fixture.test/style.css',cssRules:[],insertRule(){}}],
    documentElement:{classList:{contains:()=>false,add(){},toggle(){}}},
    getElementById:id=>id==='app'?{hidden:false}:id==='timeline'?timeline:null,
    querySelector:()=>null,addEventListener:(name,handler)=>events[name]=handler};
  const window={visualViewport,innerHeight:844,prompt:()=>'',addEventListener(){}};
  class MutationObserver{observe(){}}
  vm.runInNewContext(source,{URL,location:{origin:'https://fixture.test'},document,window,MutationObserver,
    setTimeout:(handler,delay)=>{const id=++nextTimer;timers.set(id,{handler,due:now+delay});return id;},clearTimeout:id=>timers.delete(id)});
  const field=(kind,scroller,top,height=60)=>{
    const initialScroll=scroller.scrollTop;
    return emitter({scroller,isConnected:true,matches:()=>true,
      closest:selector=>selector==='#approvals'&&kind==='codex'?{}:
        selector==='.wb-side-approval'&&kind==='side'?{closest:()=>scroller}:
        selector==='.ds-question'&&kind==='desktop'?{closest:()=>scroller}:null,
      getBoundingClientRect:()=>({top:top-(scroller.scrollTop-initialScroll),bottom:top+height-(scroller.scrollTop-initialScroll),height})});
  };
  // Each auxiliary area has its own scroll position; no global page scrolling is allowed.
  const area=(top=100,bottom=347)=>{const scroller=emitter({scrollTop:0,isConnected:true,getBoundingClientRect:()=>({top,bottom})});scroller.contains=field=>field.scroller===scroller;return scroller;};
  const advance=ms=>{const end=now+ms;while(true){const entry=[...timers].filter(([,item])=>item.due<=end).sort((a,b)=>a[1].due-b[1].due||a[0]-b[0])[0];if(!entry)break;
    const [id,item]=entry;timers.delete(id);now=item.due;item.handler();}now=end;};
  return {document,events,visualViewport,viewportEvents,timeline,field,area,advance,timers};
}

test('focused Codex answer moves into the shortened timeline before typing',()=>{
  const f=fixture(),answer=f.field('codex',f.timeline,515);
  f.document.activeElement=answer;f.events.focusin({target:answer});f.advance(120);
  assert.equal(f.timeline.scrollTop,2357,'visible answer stays put before keyboard');
  f.timeline.getBoundingClientRect=()=>({top:100,bottom:347});f.visualViewport.height=500;
  f.viewportEvents.resize();f.advance(120);
  assert.equal(f.timeline.scrollTop,2597,'60px answer clears the clipped bottom by 12px');
  assert.equal(answer.listenerCount(),0);assert.equal(f.timeline.listenerCount(),0);assert.equal(f.timers.size,0);
  f.viewportEvents.resize();f.advance(120);assert.equal(f.timeline.scrollTop,2597,'visible answer stays put');
});

test('one focus does not move the answer again as keyboard resize continues',()=>{
  const f=fixture(),answer=f.field('codex',f.timeline,515);
  f.document.activeElement=answer;f.events.focusin({target:answer});f.advance(120);
  f.timeline.getBoundingClientRect=()=>({top:100,bottom:347});f.visualViewport.height=500;
  f.viewportEvents.resize();f.advance(120);
  assert.equal(f.timeline.scrollTop,2597);
  f.timeline.getBoundingClientRect=()=>({top:100,bottom:247});f.visualViewport.height=400;
  f.viewportEvents.resize();f.advance(120);
  assert.equal(f.timeline.scrollTop,2597,'continued keyboard resize must not reposition an already moved card');
});

test('side and desktop answers scroll only their own containers',()=>{
  const f=fixture();
  for(const kind of ['side','desktop']){
    const scroller=f.area(),answer=f.field(kind,scroller,360);
    f.document.activeElement=answer;f.events.focusin({target:answer});f.advance(120);
    assert.equal(scroller.scrollTop,85);
    assert.equal(f.timeline.scrollTop,2357);
    f.events.focusout({target:answer});
  }
});

test('blur cancels late scrolling; composer and partly visible large answers stay put',()=>{
  const f=fixture(),answer=f.field('codex',f.timeline,515);
  f.timeline.getBoundingClientRect=()=>({top:100,bottom:347});f.visualViewport.height=500;
  f.document.activeElement=answer;f.events.focusin({target:answer});f.events.focusout({target:answer});f.document.activeElement=null;f.advance(120);
  assert.equal(f.timeline.scrollTop,2357);
  const composer=f.field('composer',f.timeline,515);f.document.activeElement=composer;f.events.focusin({target:composer});f.viewportEvents.resize();f.advance(120);
  assert.equal(f.timeline.scrollTop,2357);
  const large=f.field('codex',f.timeline,200,500);f.document.activeElement=large;f.events.focusin({target:large});f.advance(120);
  assert.equal(f.timeline.scrollTop,2357,'a partly visible tall answer is not pulled to its top');
});

test('keyboard animation settles before the sole necessary move',()=>{
  const f=fixture(),answer=f.field('codex',f.timeline,515);
  f.document.activeElement=answer;f.events.focusin({target:answer});f.advance(120);
  f.timeline.getBoundingClientRect=()=>({top:100,bottom:447});f.visualViewport.height=600;f.viewportEvents.resize();
  f.advance(60);f.timeline.getBoundingClientRect=()=>({top:100,bottom:347});f.visualViewport.height=500;f.viewportEvents.resize();
  f.advance(119);assert.equal(f.timeline.scrollTop,2357,'intermediate keyboard geometry does not scroll');
  f.advance(1);assert.equal(f.timeline.scrollTop,2597);
  f.viewportEvents.scroll();f.advance(120);assert.equal(f.timeline.scrollTop,2597);
});

test('the focus window expires without forcing movement',()=>{
  const f=fixture(),answer=f.field('codex',f.timeline,515);
  f.document.activeElement=answer;f.events.focusin({target:answer});f.advance(120);
  f.advance(780);
  f.timeline.getBoundingClientRect=()=>({top:100,bottom:347});f.visualViewport.height=500;
  f.viewportEvents.resize();f.advance(100);assert.equal(f.timers.size,0,'deadline cancels a pending settle timer');
  f.advance(120);assert.equal(f.timeline.scrollTop,2357);
});

test('moving focus clears the prior field and gives the new field one window',()=>{
  const f=fixture(),first=f.field('codex',f.timeline,515),second=f.field('codex',f.timeline,600);
  f.document.activeElement=first;f.events.focusin({target:first});f.advance(60);
  f.document.activeElement=second;f.events.focusin({target:second});
  assert.equal(first.listenerCount(),0);assert.equal(f.timeline.listenerCount(),2);
  f.timeline.getBoundingClientRect=()=>({top:100,bottom:347});f.visualViewport.height=500;
  f.advance(120);assert.equal(f.timeline.scrollTop,2682);
  assert.equal(second.listenerCount(),0);assert.equal(f.timeline.listenerCount(),0);
  assert.equal(f.timers.size,0);
});

test('typing, composition, and direct scrolling cancel pending reposition',()=>{
  for(const event of ['beforeinput','compositionstart','input','touchmove','wheel']){
    const f=fixture(),answer=f.field('codex',f.timeline,515);
    f.document.activeElement=answer;f.events.focusin({target:answer});
    (event==='touchmove'||event==='wheel'?f.timeline:answer).emit(event);
    f.timeline.getBoundingClientRect=()=>({top:100,bottom:347});f.visualViewport.height=500;
    f.viewportEvents.resize();f.advance(1000);
    assert.equal(f.timeline.scrollTop,2357,event+' canceled automatic scroll');
    assert.equal(answer.listenerCount(),0,event+' removed field listeners');
    assert.equal(f.timeline.listenerCount(),0,event+' removed scroller listeners');
  }
});
