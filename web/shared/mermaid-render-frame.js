'use strict';
(() => {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const instance = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  let sequence = 0;
  let busy = false;
  window.addEventListener('message', async event => {
    if (event.source !== parent || event.data?.type !== 'bridge-mermaid-render' ||
        event.data.instance !== instance || busy) return;
    const {requestId, source, theme} = event.data;
    if (!Number.isSafeInteger(requestId) || typeof source !== 'string') return;
    busy = true;
    try {
      if (source.length > 65536 || /%%\s*\{|^\s*---\s*$/m.test(source))
        throw Error('Diagram configuration or size is unsupported');
      mermaid.initialize({startOnLoad:false, securityLevel:'strict', theme:theme === 'dark' ? 'dark' : 'default',
        htmlLabels:false, flowchart:{htmlLabels:false}, maxTextSize:65536, maxEdges:500});
      const result = await mermaid.render('bridge-mermaid-' + instance + '-' + ++sequence, source);
      if (typeof result.svg !== 'string' || result.svg.length > 2_000_000)
        throw Error('Diagram output is too large');
      parent.postMessage({type:'bridge-mermaid-result', instance, requestId, svg:result.svg}, '*');
    } catch (error) {
      parent.postMessage({type:'bridge-mermaid-result', instance, requestId,
        error:String(error?.message || 'Diagram render failed').slice(0, 500)}, '*');
    } finally {
      busy = false;
    }
  });
  parent.postMessage({type:'bridge-mermaid-ready', instance}, '*');
})();
