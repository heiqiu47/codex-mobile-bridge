'use strict';
(() => {
  const maxSvgLength = 2_000_000;
  const svgNamespace = 'http://www.w3.org/2000/svg';
  const allowed = new Set(['svg','g','defs','style','title','desc','path','rect','circle','ellipse',
    'line','polyline','polygon','text','tspan','marker','clipPath','mask','pattern',
    'linearGradient','radialGradient','stop','filter','feGaussianBlur','feOffset',
    'feColorMatrix','feComposite','feMerge','feMergeNode','feFlood','feBlend']);
  let frame = null;
  let ready = null;
  let instance = null;
  let pending = null;
  let sequence = 0;
  let queue = Promise.resolve();

  function safeCss(value) {
    if (/@import\b|@namespace\b/i.test(value)) return '';
    return value.replace(/url\s*\([^)]*\)/gi, match =>
      /^url\s*\(\s*['"]?#[A-Za-z0-9_.:-]+['"]?\s*\)$/i.test(match) ? match : 'none');
  }

  function imageFromSvg(raw) {
    if (typeof raw !== 'string' || raw.length > maxSvgLength || /<!DOCTYPE|<!ENTITY/i.test(raw))
      throw Error('Invalid diagram output');
    const document = new DOMParser().parseFromString(raw, 'image/svg+xml');
    const root = document.documentElement;
    if (root.namespaceURI !== svgNamespace || root.localName !== 'svg' ||
        document.getElementsByTagName('parsererror').length) throw Error('Invalid diagram SVG');
    function clean(element) {
      for (const child of Array.from(element.children)) {
        if (child.namespaceURI !== svgNamespace || !allowed.has(child.localName)) {
          child.remove();
          continue;
        }
        clean(child);
      }
      for (const attr of Array.from(element.attributes)) {
        const name = attr.name.toLowerCase();
        if (name.startsWith('on') || name === 'href' || name === 'xlink:href' ||
            /(?:javascript:|https?:|data:|\\)/i.test(attr.value)) element.removeAttributeNode(attr);
        else if (name === 'style') element.setAttribute(attr.name, safeCss(attr.value));
        else if (/url\s*\(/i.test(attr.value)) element.setAttribute(attr.name, safeCss(attr.value));
      }
      if (element.localName === 'style') element.textContent = safeCss(element.textContent);
    }
    clean(root);
    const viewBox = (root.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
    let width = viewBox.length === 4 ? viewBox[2] : Number.parseFloat(root.getAttribute('width'));
    let height = viewBox.length === 4 ? viewBox[3] : Number.parseFloat(root.getAttribute('height'));
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0 ||
        width > 20000 || height > 20000) throw Error('Invalid diagram size');
    width = Math.ceil(width);
    height = Math.ceil(height);
    root.setAttribute('width', String(width));
    root.setAttribute('height', String(height));
    const svg = new XMLSerializer().serializeToString(root);
    return {url:'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg), width, height};
  }

  function reset(error) {
    frame?.remove();
    frame = null;
    instance = null;
    if (pending) { clearTimeout(pending.timer); pending.reject(error); pending = null; }
    if (ready) { clearTimeout(ready.timer); ready.reject(error); ready = null; }
  }

  window.addEventListener('message', event => {
    if (!frame || event.source !== frame.contentWindow || event.origin !== 'null') return;
    const data = event.data;
    if (data?.type === 'bridge-mermaid-ready' && ready && /^[a-f0-9]{32}$/.test(data.instance)) {
      instance = data.instance;
      clearTimeout(ready.timer);
      ready.resolve();
      ready = null;
    } else if (data?.type === 'bridge-mermaid-result' && data.instance === instance &&
               pending && data.requestId === pending.requestId) {
      clearTimeout(pending.timer);
      const task = pending;
      pending = null;
      try {
        if (data.error) throw Error(String(data.error));
        task.resolve(imageFromSvg(data.svg));
      } catch (error) { task.reject(error); }
    }
  });

  function ensureFrame() {
    if (frame && instance) return Promise.resolve();
    if (ready) return ready.promise;
    frame = document.createElement('iframe');
    frame.setAttribute('sandbox', 'allow-scripts');
    frame.setAttribute('referrerpolicy', 'no-referrer');
    frame.setAttribute('aria-hidden', 'true');
    frame.tabIndex = -1;
    frame.style.cssText = 'position:absolute;width:1px;height:1px;opacity:0;pointer-events:none;border:0';
    const promise = new Promise((resolve, reject) => {
      ready = {resolve, reject, timer:setTimeout(() => reset(Error('Diagram renderer failed to load')), 15000)};
    });
    frame.src = (window.BridgeRelayBase || '') + '/mermaid-render-shell';
    (document.body || document.documentElement).append(frame);
    return promise;
  }

  function renderOne(source, options) {
    if (typeof source !== 'string' || source.length > 65536) return Promise.reject(Error('Diagram source is too large'));
    return ensureFrame().then(() => new Promise((resolve, reject) => {
      const requestId = ++sequence;
      pending = {requestId, resolve, reject, timer:setTimeout(() => reset(Error('Diagram render timed out')), 12000)};
      frame.contentWindow.postMessage({type:'bridge-mermaid-render', instance, requestId,
        source, theme:options?.theme === 'dark' ? 'dark' : 'default'}, '*');
    }));
  }

  window.BridgeMermaidRenderer = {
    version:'10.9.8',
    render(source, options = {}) {
      const result = queue.then(() => renderOne(source, options));
      queue = result.catch(() => {});
      return result;
    }
  };
})();
