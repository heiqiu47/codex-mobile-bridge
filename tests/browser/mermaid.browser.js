/* Run in a browser with markdown-it, texmath, KaTeX, i18n, mermaid-cards.js,
 * and markdown.js loaded. The returned promise reports completed checks. */
(async () => {
  const checks=[];
  const check=(name,ok)=>{if(!ok)throw Error(name);checks.push(name);};
  const originalRenderer=window.BridgeMermaidRenderer,originalClipboard=window.BridgeClipboard;
  const fixture=document.createElement('div');document.body.append(fixture);
  const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
  const scope=BridgeMermaidCards.createScope();
  let calls=0, copied='', copyDone;
  window.BridgeMermaidRenderer={version:'test',render:async()=>{calls++;return {url:'data:image/svg+xml,%3Csvg%3E%3C/svg%3E',width:120,height:80};}};
  window.BridgeClipboard={copy:getSource=>copyDone=Promise.resolve(getSource()).then(value=>{copied=value;})};
  const render=(value,options={})=>{
    const owner=document.createElement('div');owner.__mermaidScope=scope;owner.__mermaidIdentity='row-1';
    renderMarkdown(owner,value,[],()=>'',options);fixture.append(owner);return owner;
  };
  try{
    const unfinished=render('```mermaid\ngraph TD\n A-->B');
    await tick();
    check('unclosed fence stays readable code',!unfinished.querySelector('.mermaid-card')&&unfinished.querySelector('pre code')?.textContent.includes('A-->B')&&calls===0);
    const ordinary=render('```js\nconst x=1\n```');
    check('ordinary fence is unchanged',!ordinary.querySelector('.mermaid-card')&&ordinary.querySelector('.code-copy'));
    const source='graph TD\n A-->B\n';
    const complete=render('```js\nfirst\n```\n\n```mermaid\n'+source+'```',{fullText:async()=> '```js\nfirst\n```\n\n```mermaid\n'+source+'```'});
    await tick();await tick();
    const card=complete.querySelector('.mermaid-card');
    check('complete Mermaid fence renders image once',card?.querySelector('img')&&calls===1);
    card.querySelectorAll('button')[1].click();
    check('source switch reveals exact parsed code',!card.querySelector('pre').hidden&&card.querySelector('pre code').textContent===source);
    card.querySelectorAll('button')[2].click();await copyDone;
    check('copy follows original code-block index',copied===source);
    complete.remove();
    const replacement=render('```js\nfirst\n```\n\n```mermaid\n'+source+'```');
    await tick();
    check('view survives row replacement',!replacement.querySelector('.mermaid-card pre').hidden);
    replacement.querySelectorAll('.mermaid-card button')[0].click();await tick();
    check('unchanged output reuses bounded cache',calls===1&&replacement.querySelector('.mermaid-card img'));
    BridgeMermaidCards.clearScope(scope);
    check('dispose clears session cache and view state',scope.cache.size===0&&scope.views.size===0);
    const pending=BridgeMermaidCards.createScope();
    let finish;
    window.BridgeMermaidRenderer={version:'pending',render:()=>new Promise(resolve=>{finish=resolve;})};
    const old=document.createElement('div');old.__mermaidScope=pending;old.__mermaidIdentity='old';
    renderMarkdown(old,'```mermaid\ngraph LR\n A-->B\n```');fixture.append(old);
    await tick();BridgeMermaidCards.clearScope(pending);old.remove();
    finish({url:'data:image/svg+xml,%3Csvg%3E%3C/svg%3E',width:120,height:80});await tick();
    check('disposed async result cannot populate cache or detached row',pending.cache.size===0&&!old.querySelector('.mermaid-card img'));
    const nested=BridgeMermaidCards.createScope();
    window.BridgeMermaidRenderer={version:'nested',render:async()=>({url:'data:image/svg+xml,%3Csvg%3E%3C/svg%3E',width:120,height:80})};
    const detached=document.createElement('div');detached.__mermaidScope=nested;
    renderMarkdown(detached,'> - item\n>   ```mermaid\n>   graph TD\n>   A-->B\n>   ```');
    await tick();fixture.append(detached);
    check('nested quoted list fence renders after detached construction',!!detached.querySelector('.mermaid-card img'));
    BridgeMermaidCards.clearScope(nested);
    const budget=BridgeMermaidCards.createScope();
    for(let index=0;index<25;index++){
      const owner=document.createElement('div');owner.__mermaidScope=budget;owner.__mermaidIdentity='file:'+index;
      renderMarkdown(owner,'```mermaid\ngraph TD\n A'+index+'-->B\n```');fixture.append(owner);
    }
    await tick();await tick();
    check('shared scope bounds diagrams across files',budget.cache.size<=24&&budget.bytes<=6*1024*1024);
    BridgeMermaidCards.clearScope(budget);
    return {passed:checks.length,checks};
  } finally {fixture.remove();window.BridgeMermaidRenderer=originalRenderer;window.BridgeClipboard=originalClipboard;}
})();
