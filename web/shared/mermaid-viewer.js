'use strict';
(() => {
  const t = text => typeof BridgeI18n === 'undefined' ? text : BridgeI18n.t(text);
  const pointers = new Map();
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  let dialog, canvas, image, sourcePanel, status, closeButton, sourceButton, copyButton;
  let controls, zoomOut, zoomIn, fitButton, percentage, observer, opener, entry, activeImage;
  let width = 0, height = 0, zoom = 1, x = 0, y = 0, frame = 0, gesture, lastTap, generation = 0;

  const imageReady = () => dialog?.open && sourcePanel.hidden && image?.complete && image.naturalWidth > 0 && width > 0;
  function paint() {
    frame = 0;
    if (!imageReady()) return;
    const limitX = Math.max(0, (width * zoom - canvas.clientWidth + 24) / 2);
    const limitY = Math.max(0, (height * zoom - canvas.clientHeight + 24) / 2);
    x = clamp(x, -limitX, limitX); y = clamp(y, -limitY, limitY);
    image.style.width = width + 'px'; image.style.height = height + 'px';
    image.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px) scale(${zoom})`;
    percentage.textContent = Math.round(zoom * 100) + '%';
    zoomOut.disabled = zoom <= 1; zoomIn.disabled = zoom >= 8; fitButton.disabled = zoom === 1;
    canvas.classList.toggle('is-zoomed', zoom > 1);
  }
  function schedule() { if (!frame) frame = requestAnimationFrame(paint); }
  function clearPointers() {
    const captured = [...pointers.keys()]; pointers.clear(); gesture = lastTap = null;
    for (const id of captured) if (canvas.hasPointerCapture(id)) canvas.releasePointerCapture(id);
    canvas.classList.remove('is-dragging');
  }
  function cleanup() {
    generation++;
    if (frame) cancelAnimationFrame(frame); frame = 0;
    observer?.disconnect(); clearPointers();
    if (image) { image.onload = image.onerror = null; image.remove(); }
    image = null; entry = null; activeImage = null;
    width = height = x = y = 0; zoom = 1;
  }
  function measure() {
    if (!dialog.open || !image?.naturalWidth || !activeImage || !sourcePanel.hidden) return;
    const ratio = Math.min(1, Math.max(1, canvas.clientWidth - 24) / activeImage.width,
      Math.max(1, canvas.clientHeight - 24) / activeImage.height);
    const nextWidth = activeImage.width * ratio, nextHeight = activeImage.height * ratio;
    if (width) { x *= nextWidth / width; y *= nextHeight / height; }
    width = nextWidth; height = nextHeight; clearPointers(); schedule();
  }
  function point(event) {
    const bounds = canvas.getBoundingClientRect();
    return {x:event.clientX - bounds.left - bounds.width / 2, y:event.clientY - bounds.top - bounds.height / 2};
  }
  function changeZoom(value, from = {x:0,y:0}, to = from) {
    if (!imageReady()) return;
    const next = clamp(value, 1, 8), ratio = next / zoom;
    x = to.x - (from.x - x) * ratio; y = to.y - (from.y - y) * ratio; zoom = next;
    if (frame) cancelAnimationFrame(frame); paint();
  }
  function reset() { clearPointers(); zoom = 1; x = y = 0; schedule(); }
  function baseline() {
    const values = [...pointers.values()];
    if (values.length === 2) gesture = {
      mid:{x:(values[0].x + values[1].x) / 2, y:(values[0].y + values[1].y) / 2},
      distance:Math.hypot(values[1].x - values[0].x, values[1].y - values[0].y)
    };
    else gesture = values[0] ? {point:{x:values[0].x,y:values[0].y}} : null;
    canvas.classList.toggle('is-dragging', !!values.length && zoom > 1);
  }
  function pointerDown(event) {
    if (!imageReady() || event.button !== 0 || pointers.size >= 2) return;
    event.preventDefault();
    const p = point(event);
    pointers.set(event.pointerId, {...p,start:p,time:performance.now(),moved:false,type:event.pointerType});
    canvas.setPointerCapture(event.pointerId);
    if (pointers.size > 1) { lastTap = null; for (const value of pointers.values()) value.moved = true; }
    baseline();
  }
  function pointerMove(event) {
    const prior = pointers.get(event.pointerId); if (!prior || !imageReady()) return;
    event.preventDefault(); const p = point(event);
    pointers.set(event.pointerId, {...prior,...p,moved:prior.moved || Math.hypot(p.x - prior.start.x, p.y - prior.start.y) > 8});
    const before = gesture; baseline();
    if (pointers.size === 2 && before?.distance > 0) changeZoom(zoom * gesture.distance / before.distance, before.mid, gesture.mid);
    else if (pointers.size === 1 && before?.point && zoom > 1) { x += p.x - before.point.x; y += p.y - before.point.y; schedule(); }
  }
  function pointerEnd(event) {
    const prior = pointers.get(event.pointerId); if (!prior) return;
    const tap = event.type === 'pointerup' && prior.type === 'touch' && pointers.size === 1 &&
      !prior.moved && performance.now() - prior.time < 350;
    pointers.delete(event.pointerId);
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    baseline();
    if (tap) {
      if (lastTap && performance.now() - lastTap.time < 350 && Math.hypot(prior.x - lastTap.x, prior.y - lastTap.y) < 24) {
        changeZoom(zoom === 1 ? 2 : 1, prior); lastTap = null;
      } else lastTap = {...prior,time:performance.now()};
    } else lastTap = null;
  }
  async function exactSource() {
    if (!entry) throw Error(t('读取源码失败，请重试。'));
    if (typeof entry.exactSource === 'string') return entry.exactSource;
    if (entry.getSource) {
      const current = entry, value = await current.getSource();
      if (current !== entry || typeof value !== 'string') throw Error(t('读取源码失败，请重试。'));
      current.exactSource = value;
      return value;
    }
    if (typeof entry.source === 'string') return entry.exactSource = entry.source;
    throw Error(t('读取源码失败，请重试。'));
  }
  async function showSource() {
    if (!sourcePanel.hidden) {
      sourcePanel.hidden = true; canvas.hidden = false; controls.hidden = false; sourceButton.setAttribute('aria-pressed', 'false');
      sourceButton.textContent = t('源码'); measure(); return;
    }
    const current = generation;
    sourceButton.disabled = true;
    try {
      const value = await exactSource();
      if (current !== generation || !dialog.open) return;
      if (sourcePanel.textContent !== value) sourcePanel.textContent = value;
      sourcePanel.hidden = false; canvas.hidden = true; controls.hidden = true;
      clearPointers(); sourceButton.setAttribute('aria-pressed', 'true'); sourceButton.textContent = t('查看图表');
      status.textContent = '';
    } catch (error) { if (current === generation) status.textContent = error.message || t('读取源码失败，请重试。'); }
    finally { if (current === generation) sourceButton.disabled = false; }
  }
  function relabel() {
    dialog.setAttribute('aria-label', t('图表'));
    if (image) image.alt = t('图表');
    closeButton.textContent = '× ' + t('关闭'); closeButton.setAttribute('aria-label', t('关闭图表预览'));
    sourceButton.textContent = sourcePanel.hidden ? t('源码') : t('查看图表');
    copyButton.textContent = t('复制源码');
    zoomOut.textContent = '−'; zoomIn.textContent = '+';
    zoomOut.setAttribute('aria-label', t('缩小图表')); zoomIn.setAttribute('aria-label', t('放大图表'));
    fitButton.textContent = t('适应屏幕'); percentage.setAttribute('aria-label', t('图表缩放比例'));
  }
  function create() {
    dialog = document.createElement('dialog'); dialog.id = 'mermaid-preview-dialog'; dialog.className = 'mermaid-preview';
    dialog.setAttribute('aria-label', t('图表'));
    const toolbar = document.createElement('div'); toolbar.className = 'mermaid-preview-toolbar';
    const button = (id, action) => { const node = document.createElement('button'); node.id = 'mermaid-preview-' + id;
      node.type = 'button'; node.onclick = action; return node; };
    closeButton = button('close', () => dialog.close()); closeButton.dataset.close = dialog.id; closeButton.autofocus = true;
    sourceButton = button('source', showSource); sourceButton.setAttribute('aria-pressed', 'false');
    copyButton = button('copy', () => window.BridgeClipboard?.copy(exactSource, copyButton));
    copyButton.className = 'code-copy';
    toolbar.append(closeButton, sourceButton, copyButton);
    canvas = document.createElement('div'); canvas.className = 'mermaid-preview-canvas';
    sourcePanel = document.createElement('pre'); sourcePanel.className = 'mermaid-preview-source'; sourcePanel.hidden = true;
    sourcePanel.tabIndex = 0;
    controls = document.createElement('div'); controls.className = 'mermaid-preview-controls';
    zoomOut = button('zoom-out', () => changeZoom(zoom / 1.25));
    zoomIn = button('zoom-in', () => changeZoom(zoom * 1.25));
    fitButton = button('fit', reset);
    percentage = document.createElement('output'); percentage.id = 'mermaid-preview-scale';
    controls.append(zoomOut, percentage, zoomIn, fitButton);
    status = document.createElement('p'); status.id = 'mermaid-preview-status'; status.setAttribute('role', 'status');
    dialog.append(toolbar, canvas, sourcePanel, controls, status); document.body.append(dialog);
    observer = new ResizeObserver(measure);
    canvas.addEventListener('pointerdown', pointerDown); canvas.addEventListener('pointermove', pointerMove);
    for (const type of ['pointerup','pointercancel','lostpointercapture']) canvas.addEventListener(type, pointerEnd);
    canvas.addEventListener('wheel', event => {
      if (!imageReady()) return;
      event.preventDefault(); clearPointers();
      const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas.clientHeight : 1);
      changeZoom(zoom * Math.exp(-clamp(pixels, -1000, 1000) * .002), point(event));
    }, {passive:false});
    canvas.addEventListener('dblclick', event => {
      if (event.sourceCapabilities?.firesTouchEvents || !imageReady()) return;
      event.preventDefault(); clearPointers(); changeZoom(zoom === 1 ? 2 : 1, point(event));
    });
    dialog.addEventListener('keydown', event => {
      if (event.target === sourcePanel || event.target.tagName === 'BUTTON' && (event.key === ' ' || event.key === 'Enter')) return;
      if (event.key === '+' || event.key === '=') { event.preventDefault(); changeZoom(zoom * 1.25); }
      else if (event.key === '-') { event.preventDefault(); changeZoom(zoom / 1.25); }
      else if (event.key === '0') { event.preventDefault(); reset(); }
      else if (imageReady() && ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) {
        event.preventDefault();
        x += event.key === 'ArrowLeft' ? 40 : event.key === 'ArrowRight' ? -40 : 0;
        y += event.key === 'ArrowUp' ? 40 : event.key === 'ArrowDown' ? -40 : 0; schedule();
      }
    });
    dialog.addEventListener('close', () => {
      if (dialog.open) return;
      cleanup(); sourcePanel.textContent = ''; sourcePanel.hidden = true; canvas.hidden = false; controls.hidden = false; status.textContent = '';
      if (opener?.isConnected) opener.focus({preventScroll:true}); opener = null;
    });
    document.addEventListener('bridge-language', () => { if (dialog.open) relabel(); });
  }
  window.BridgeMermaidViewer = {
    closeScope(scope) { if (scope && entry?.scope === scope && dialog?.open) dialog.close(); },
    open(value) {
      if (!value?.image || typeof value.image.url !== 'string' ||
          !/^(?:blob:|data:image\/svg\+xml[,;])/.test(value.image.url) ||
          !(Number(value.image.width) > 0 && Number(value.image.height) > 0)) return false;
      if (!dialog) create();
      cleanup(); entry = {source:value.source, getSource:value.getSource, scope:value.scope};
      activeImage = {width:Number(value.image.width),height:Number(value.image.height)};
      opener = value.opener || document.activeElement;
      sourcePanel.textContent = ''; sourcePanel.hidden = true; canvas.hidden = false; controls.hidden = false;
      sourceButton.disabled = false; sourceButton.setAttribute('aria-pressed', 'false');
      percentage.textContent = '100%'; zoomOut.disabled = zoomIn.disabled = fitButton.disabled = true;
      canvas.classList.remove('is-zoomed'); status.textContent = t('正在加载图表…'); relabel();
      const current = image = document.createElement('img'); current.alt = t('图表'); current.draggable = false;
      current.onload = () => { if (image === current && dialog.open) { status.textContent = ''; measure(); } };
      current.onerror = () => { if (image === current && dialog.open) { current.hidden = true; status.textContent = t('图表加载失败，请关闭后重试。'); } };
      canvas.replaceChildren(current);
      if (!dialog.open) dialog.showModal();
      observer.observe(canvas); current.src = value.image.url;
      return true;
    }
  };
})();
