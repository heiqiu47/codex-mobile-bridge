'use strict';
(() => {
  const MAX_SOURCE = 30000, MAX_ENTRIES = 24, MAX_DATA = 6 * 1024 * 1024;
  const t = value => typeof BridgeI18n === 'undefined' ? value : BridgeI18n.t(value);
  const theme = () => document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
  function createScope() { return {cache:new Map(), pending:new Map(), bytes:0, views:new Map(), revision:0, disposed:false}; }
  function resetScope(scope) { if (!scope) return; window.BridgeMermaidViewer?.closeScope(scope); scope.cache.clear(); scope.pending.clear(); scope.views.clear(); scope.bytes=0; scope.revision++; }
  function clearScope(scope) { if (!scope) return; resetScope(scope); scope.disposed=true; }
  function remember(scope,key,image) {
    if (!scope || scope.disposed || image.url.length > MAX_DATA) return;
    const prior=scope.cache.get(key);
    if (prior) scope.bytes-=prior.url.length;
    scope.cache.delete(key); scope.cache.set(key,image); scope.bytes+=image.url.length;
    while (scope.cache.size > MAX_ENTRIES || scope.bytes > MAX_DATA) {
      const oldest=scope.cache.keys().next().value;
      scope.bytes-=scope.cache.get(oldest).url.length; scope.cache.delete(oldest);
    }
  }
  function create(source,{owner,index,getSource}) {
    const scope=owner.__mermaidScope, identity=owner.__mermaidIdentity;
    const viewKey=identity === undefined ? null : identity+'|'+index;
    const card=document.createElement('section'); card.className='mermaid-card';
    const toolbar=document.createElement('div'); toolbar.className='mermaid-card-toolbar';
    const make=(label,action)=>{const button=document.createElement('button');button.type='button';button.className='plain';button.dataset.i18n=label;button.textContent=t(label);button.onclick=action;return button;};
    const stage=document.createElement('div'); stage.className='mermaid-card-stage';
    const status=document.createElement('p'); status.className='mermaid-card-status';status.setAttribute('role','status');
    const pre=document.createElement('pre');pre.className='mermaid-card-source';const code=document.createElement('code');code.textContent=source;pre.append(code);
    let image=null, rendering=false, generation=0;
    const selected=scope?.views.get(viewKey)==='source'?'source':'diagram';
    let view=selected;
    const diagramButton=make('图表',()=>show('diagram'));
    const sourceButton=make('源码',()=>show('source'));
    const copyButton=make('复制源码',()=>window.BridgeClipboard?.copy(getSource,copyButton));
    const fullButton=make('全屏查看',()=>{
      if(image) window.BridgeMermaidViewer?.open({image,source,getSource,scope,opener:fullButton});
    });
    toolbar.append(diagramButton,sourceButton,copyButton,fullButton);
    card.append(toolbar,stage,status,pre);
    function show(next) {
      view=next;
      if(scope && viewKey!==null && !scope.disposed){
        scope.views.delete(viewKey);scope.views.set(viewKey,view);
        if(scope.views.size>200)scope.views.delete(scope.views.keys().next().value);
      }
      diagramButton.setAttribute('aria-pressed',String(view==='diagram'));
      sourceButton.setAttribute('aria-pressed',String(view==='source'));
      stage.hidden=view!=='diagram';status.hidden=view!=='diagram';pre.hidden=view!=='source';
      fullButton.hidden=view!=='diagram'||!image;
      if(view==='diagram')start();
    }
    function start() {
      if(rendering || image || !window.BridgeMermaidRenderer) return;
      if(source.length > MAX_SOURCE) {status.textContent=t('图表过大，请查看源码');return;}
      const renderer=window.BridgeMermaidRenderer, key=JSON.stringify([renderer.version,theme(),source]);
      const cached=scope?.cache.get(key);
      if(cached){scope.cache.delete(key);scope.cache.set(key,cached);display(cached);return;}
      rendering=true;status.textContent=t('正在生成图表…');
      const ticket=++generation;
      const revision=scope?.revision;
      let task=scope?.pending.get(key);
      if(!task){
        task=Promise.resolve().then(()=>renderer.render(source,{theme:theme()}));
        if(scope && !scope.disposed){
          scope.pending.set(key,task);
          task.then(result=>{if(!scope.disposed && scope.revision===revision && result?.url)remember(scope,key,result);}).catch(()=>{}).finally(()=>{if(scope.pending.get(key)===task)scope.pending.delete(key);});
        }
      }
      task.then(result=>{
        if(ticket!==generation || scope?.disposed || (scope && scope.revision!==revision))return;
        if(!result?.url || !Number.isFinite(result.width) || !Number.isFinite(result.height))throw Error('invalid diagram');
        display(result);
      }).catch(()=>{
        if(ticket===generation && !scope?.disposed && (!scope || scope.revision===revision))status.textContent=t('图表无法显示，请查看源码');
      }).finally(()=>{if(ticket===generation)rendering=false;});
    }
    function display(result) {
      image=result;
      const img=document.createElement('img');img.alt=t('图表');img.src=result.url;img.width=result.width;img.height=result.height;
      img.loading='lazy';img.decoding='async';img.onclick=()=>window.BridgeMermaidViewer?.open({image,source,getSource,scope,opener:img});
      img.tabIndex=0;img.setAttribute('role','button');img.setAttribute('aria-label',t('查看图表'));
      img.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();img.click();}};
      stage.replaceChildren(img);status.textContent='';fullButton.hidden=view!=='diagram';
    }
    card.__refreshMermaid=()=>{
      generation++;rendering=false;image=null;stage.replaceChildren();fullButton.hidden=true;
      if(view==='diagram')start();
    };
    card.__relabelMermaid=()=>{
      for(const button of toolbar.querySelectorAll('[data-i18n]'))button.textContent=t(button.dataset.i18n);
      const img=stage.querySelector('img');if(img){img.alt=t('图表');img.setAttribute('aria-label',t('查看图表'));}
    };
    show(view);
    return card;
  }
  new MutationObserver(records=>{
    if(records.some(record=>record.attributeName==='data-theme'))
      document.querySelectorAll('.mermaid-card').forEach(card=>card.__refreshMermaid?.());
  }).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
  document.addEventListener('bridge-language',()=>document.querySelectorAll('.mermaid-card').forEach(card=>card.__relabelMermaid?.()));
  window.BridgeMermaidCards={create,createScope,resetScope,clearScope};
})();
