// Run on a page with mermaid-viewer.js/css and BridgeClipboard loaded.
async function runMermaidViewerTests() {
  const checks = [], check = (value, label) => { if (!value) throw Error(label); checks.push(label); };
  const settle = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const wait = async fn => { for (let i = 0; i < 100; i++) { if (fn()) return; await new Promise(r => setTimeout(r, 20)); } throw Error('Mermaid viewer did not settle'); };
  const source = 'flowchart TD\n  A["<script>中文</script>"] --> B\n' + '  B --> A\n'.repeat(120);
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400"><rect width="600" height="400" fill="white"/><text x="30" y="80">Mermaid fixture</text></svg>';
  const url = 'data:image/svg+xml;base64,' + btoa(svg);
  const opener = document.createElement('button'); opener.textContent = 'Open diagram'; document.body.append(opener);
  let sourceReads = 0, copied;
  const clipboard = window.BridgeClipboard;
  window.BridgeClipboard = {copy:async (getText, button) => { copied = await getText(); button.textContent = 'copied'; }};
  const open = async () => {
    BridgeMermaidViewer.open({image:{url,width:600,height:400},source:'incomplete',getSource:async()=>{ sourceReads++; return source; },opener});
    await wait(() => document.querySelector('#mermaid-preview-dialog')?.open && !document.querySelector('#mermaid-preview-zoom-in')?.disabled);
    await settle();
  };
  try {
    await open();
    const dialog = document.querySelector('#mermaid-preview-dialog'), canvas = dialog.querySelector('.mermaid-preview-canvas');
    const button = id => dialog.querySelector('#mermaid-preview-' + id);
    const scale = () => Number(dialog.querySelector('#mermaid-preview-scale').textContent.replace('%','')) / 100;
    check(scale() === 1 && canvas.querySelector('img').tagName === 'IMG', 'Diagram opens as an image fitted to its viewport');
    button('zoom-in').click(); await settle(); check(scale() > 1, 'Zoom button enlarges diagram');
    button('fit').click(); await settle(); check(scale() === 1, 'Fit restores baseline');
    const box = canvas.getBoundingClientRect();
    const captures = new Set(), originalCapture = canvas.setPointerCapture, originalRelease = canvas.releasePointerCapture, originalHas = canvas.hasPointerCapture;
    canvas.setPointerCapture = id => captures.add(id); canvas.releasePointerCapture = id => captures.delete(id); canvas.hasPointerCapture = id => captures.has(id);
    const pointer = (type,id,x,y) => canvas.dispatchEvent(new PointerEvent(type,{pointerId:id,pointerType:'touch',button:0,
      clientX:box.left+box.width/2+x,clientY:box.top+box.height/2+y,bubbles:true,cancelable:true}));
    pointer('pointerdown',1,-40,0); pointer('pointerdown',2,40,0);
    pointer('pointermove',1,-80,0); pointer('pointermove',2,80,0); await settle();
    check(Math.abs(scale()-2)<.02, 'Pinch scales diagram by pointer distance');
    pointer('pointerup',2,80,0);
    const vertical = canvas.querySelector('img').getBoundingClientRect().height > canvas.clientHeight;
    const beforePan = canvas.querySelector('img').getBoundingClientRect();
    pointer('pointermove',1,-80+(vertical?0:25),vertical?25:0); await settle();
    const afterPan = canvas.querySelector('img').getBoundingClientRect();
    check(Math.abs((vertical?afterPan.top-beforePan.top:afterPan.left-beforePan.left)-25)<1, 'One remaining touch pans after pinch');
    pointer('pointercancel',1,-80+(vertical?0:25),vertical?25:0); check(captures.size===0, 'Pointer cancellation releases capture');
    canvas.setPointerCapture=originalCapture; canvas.releasePointerCapture=originalRelease; canvas.hasPointerCapture=originalHas;
    button('fit').click(); await settle();
    canvas.dispatchEvent(new WheelEvent('wheel',{clientX:box.left+box.width/2,clientY:box.top+box.height/2,deltaY:-180,bubbles:true,cancelable:true}));
    await settle(); check(scale() > 1, 'Wheel zoom works inside modal');
    button('source').click(); await wait(() => !dialog.querySelector('.mermaid-preview-source').hidden);
    const pre = dialog.querySelector('.mermaid-preview-source');
    check(pre.textContent === source && !pre.querySelector('script') && sourceReads === 1, 'Source view uses exact async text without HTML insertion');
    pre.scrollTop = 220; const sourceScroll = pre.scrollTop;
    check(sourceScroll > 0, 'Long source has independent scrolling');
    button('copy').click(); await wait(() => copied === source); check(copied === source, 'Copy uses exact async source');
    check(canvas.hidden, 'Source view hides diagram interaction');
    button('source').click(); await settle(); check(!canvas.hidden && scale() > 1, 'Returning to diagram preserves zoom');
    button('source').click(); await wait(() => !pre.hidden);
    check(pre.scrollTop === sourceScroll && sourceReads === 1, 'Reopening source preserves scroll and cached exact text');
    button('source').click(); await settle(); check(scale() > 1, 'Returning again preserves diagram zoom');
    opener.remove(); await settle(); check(dialog.open, 'Chat rerender does not close viewer');
    dialog.close(); await settle(); check(!dialog.open, 'Viewer closes normally after opener removal');
    document.body.append(opener); opener.focus(); await open();
    check(scale() === 1, 'Reopening starts fitted');
    button('close').click(); await settle(); check(document.activeElement === opener, 'Close restores focus to connected opener');
    const scope={};
    BridgeMermaidViewer.open({image:{url,width:600,height:400},source,scope,opener});
    BridgeMermaidViewer.closeScope({});
    check(dialog.open,'Invalidating another scope does not close the viewer');
    BridgeMermaidViewer.closeScope(scope);await settle();
    check(!dialog.open && !canvas.querySelector('img'),'Invalidating the owning scope clears the fullscreen image');
  } finally { window.BridgeClipboard = clipboard; opener.remove(); }
  return checks;
}
