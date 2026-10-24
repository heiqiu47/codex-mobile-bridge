'use strict';
(() => {
  const t = value => typeof BridgeI18n === 'undefined' ? value : BridgeI18n.t(value);
  const maxLength=64*1024;
  function read(source, offset = 0) {
    if(!source.startsWith('::code-comment{',offset) && !source.startsWith(':codex-followup[',offset))return null;
    const item=readBounded(source.slice(offset,offset+maxLength));
    if(item)item.end+=offset;
    return item;
  }
  function readBounded(source, offset = 0) {
    const comment = source.startsWith('::code-comment{', offset);
    const follow = !comment && /^:codex-followup\[([^\]\n]+)\]\{/.exec(source.slice(offset));
    if (!comment && !follow) return null;
    let cursor = offset + (comment ? 15 : follow[0].length);
    const attributes = {};
    while (cursor < source.length) {
      while (/\s/.test(source[cursor] || '') && cursor < source.length) cursor++;
      if (source[cursor] === '}') {
        const keys = Object.keys(attributes);
        if (comment ? !attributes.title || !attributes.body || !attributes.file || keys.some(key => !['title','body','file','start','end','priority'].includes(key)) : !attributes.prompt || keys.some(key => key !== 'prompt')) return null;
        if (comment && (['title','body','file'].some(key => typeof attributes[key] !== 'string') || ['start','end'].some(key => attributes[key] !== undefined && (!Number.isSafeInteger(attributes[key]) || attributes[key] < 1 || attributes[key] > 1000000)) || attributes.end !== undefined && (attributes.start === undefined || attributes.end < attributes.start) || attributes.priority !== undefined && (!Number.isInteger(attributes.priority) || attributes.priority < 0 || attributes.priority > 3))) return null;
        return {kind:comment ? 'comment' : 'followup', label:follow?.[1], attributes, source:source.slice(offset, cursor + 1), end:cursor + 1};
      }
      const key = /^([a-z]+)=/.exec(source.slice(cursor));
      if (!key || Object.hasOwn(attributes,key[1])) return null;
      cursor += key[0].length;
      let value;
      if (source[cursor] === '"') {
        cursor++; value=''; let closed=false;
        while(cursor < source.length) {
          const char=source[cursor++];
          if(char === '"') {closed=true;break;}
          if(char === '\\') {
            const next=source[cursor++];
            if(next === undefined)return null;
            value+=next === '"' || next === '\\' ? next : '\\'+next;
          } else value+=char;
        }
        if(!closed) return null;
      } else {
        const number=/^\d+/.exec(source.slice(cursor));
        if(!number) return null;
        value=Number(number[0]);cursor+=number[0].length;
      }
      attributes[key[1]]=value;
      if(source[cursor] !== '}' && !/\s/.test(source[cursor] || '')) return null;
    }
    return null;
  }
  function readState(state,offset) {
    if(!state.src.startsWith('::code-comment{',offset) && !state.src.startsWith(':codex-followup[',offset))return null;
    if(state.outputDirectiveBudget === undefined)state.outputDirectiveBudget=state.src.length*4+maxLength;
    if(state.outputDirectiveBudget <= 0)return null;
    const item=read(state.src,offset);
    state.outputDirectiveBudget-=item ? item.end-offset : Math.min(maxLength,state.src.length-offset);
    return item;
  }
  function button(label, action) {
    const node=document.createElement('button');node.type='button';node.className='plain';node.textContent=t(label);node.onclick=action;return node;
  }
  function isReviewTarget(reference) {
    try {const url=new URL(reference);return url.protocol === 'codex:' && url.hostname === 'review' && (!url.pathname || url.pathname === '/') && !url.username && !url.password && !url.port;} catch {return false;}
  }
  function reviewUrl(reference) {
    try {
      const url=new URL(reference);
      if(url.protocol !== 'codex:' || url.hostname !== 'review' || url.pathname && url.pathname !== '/' || url.username || url.password || url.port) return null;
      const pr=new URL(url.searchParams.get('pr'));
      return pr.protocol === 'https:' && pr.hostname === 'github.com' && !pr.username && !pr.password && !pr.port && /^\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/pull\/[1-9]\d*\/?$/.test(pr.pathname) && !pr.search && !pr.hash ? pr.href : null;
    } catch {return null;}
  }
  function review(reference) {
    if(!isReviewTarget(reference))return;
    const box=document.createElement('dialog');box.className='output-review-dialog';
    const title=document.createElement('h3');title.textContent=t('代码审查链接');
    const source=document.createElement('p');source.textContent=reference;
    const desktop=document.createElement('a');desktop.href=reference;desktop.textContent=t('在 Codex 桌面打开');
    const head=document.createElement('div');head.className='output-review-heading';head.append(title,button('关闭',()=>box.close()));
    const actions=document.createElement('div');actions.className='output-review-actions';
    actions.append(desktop,button('复制链接',event=>window.BridgeClipboard?.copy(()=>reference,event.currentTarget)));
    box.append(head,source,actions);
    const mapped=reviewUrl(reference);
    if(mapped){const link=document.createElement('a');link.href=mapped;link.target='_blank';link.rel='noopener noreferrer';link.textContent=t('在 GitHub 查看 PR');actions.append(link);}
    box.addEventListener('close',()=>box.remove());document.body.append(box);box.showModal();
  }
  function create(item, resolve) {
    if(item.kind === 'followup') {
      const action=button(item.label,event=>event.currentTarget.dispatchEvent(new CustomEvent('bridge-compose-prompt',{bubbles:true,detail:{text:item.attributes.prompt}})));
      action.textContent=item.label;action.className+=' output-followup';return action;
    }
    const card=document.createElement('div');card.className='output-code-comment';
    const {title,body,file,start,end,priority}=item.attributes;
    const heading=document.createElement('strong');heading.textContent=(priority === undefined || title.startsWith('[P'+priority+']') ? '' : '[P'+priority+'] ')+title;
    const content=document.createElement('p');content.textContent=body;
    const destination=resolve(file);
    const location=document.createElement(destination ? 'a' : 'span');location.textContent=file+(start ? ':'+start+(end && end !== start ? '–'+end : '') : '');location.className='output-comment-location';
    if(destination){location.href=destination.url;if(start)location.dataset.sourceLine=String(start);if(end)location.dataset.sourceEnd=String(end);}
    card.append(heading,content,location,button('复制批注源码',event=>window.BridgeClipboard?.copy(()=>item.source,event.currentTarget)));return card;
  }
  window.BridgeOutputDirectives={read,create,review,reviewUrl,isReviewTarget,install(markdown){
    markdown.block.ruler.before('paragraph','output_directive',(state,startLine,endLine,silent)=>{
      const offset=state.bMarks[startLine]+state.tShift[startLine];
      const item=readState(state,offset);
      if(!item || item.kind !== 'comment' || state.src.slice(item.end).split('\n',1)[0].trim()) return false;
      if(silent)return true;
      let nextLine=startLine;
      while(nextLine < endLine && state.bMarks[nextLine] < item.end)nextLine++;
      const token=state.push('output_directive','',0);token.meta=item;token.map=[startLine,nextLine];state.line=nextLine;return true;
    });
    markdown.inline.ruler.before('escape','output_directive',(state,silent)=>{
      const item=readState(state,state.pos);if(!item)return false;
      if(!silent){const token=state.push('output_directive','',0);token.meta=item;}
      state.pos=item.end;return true;
    });
  }};
})();
