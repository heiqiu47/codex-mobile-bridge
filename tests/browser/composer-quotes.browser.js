// Run with production ComposerQuotes and composer CSS in a synthetic page.
// Uses only local DOM and in-memory drafts; never submits a chat.
window.runComposerQuoteLayoutChecks=async function(){
 const results=[],check=(ok,label)=>{if(!ok)throw Error(label);results.push(label);};
 for(const provider of ['codex','claude']){
  const root=document.createElement('section');root.style.cssText='position:fixed;inset:0;background:var(--page);z-index:100;overflow:auto';
  const messages=document.createElement('div');messages.innerHTML='<div class="message assistant"><div class="message-body">Selected reply text for the quote</div></div>';
  const form=document.createElement('form');form.className='composer'+(provider==='claude'?' ds-composer':'');
  const tools=document.createElement('div');tools.className='composer-tools';
  tools.innerHTML='<button class="tool-button">模型</button><button class="tool-button">Skill</button><button class="tool-button">权限</button><button class="tool-button context-usage">◯</button><button class="composer-toggle">⌃</button>';
  const container=document.createElement('div'),input=document.createElement('textarea');input.value='Existing draft';container.append(input);form.append(tools,container);root.append(messages,form);document.body.append(root);
  let changes=0;const scope={provider,session:'synthetic'};
  const quotes=new ComposerQuotes({messages,input,container,scope:()=>scope,onChange:()=>changes++,onPrompt(){}});
  try{
   check(quotes.action.previousElementSibling===tools.querySelector('.context-usage'),provider+' selection action follows context usage');
   const text=messages.querySelector('.message-body').firstChild,range=document.createRange(),selection=getSelection();range.setStart(text,0);range.setEnd(text,13);selection.removeAllRanges();selection.addRange(range);quotes.capture();
   check(!quotes.action.hidden&&quotes.root.hidden,provider+' selection action does not create an empty preview row');
   const actionBox=quotes.action.getBoundingClientRect(),contextBox=tools.querySelector('.context-usage').getBoundingClientRect();
   if(innerWidth>720)check(Math.abs(actionBox.top-contextBox.top)<2&&actionBox.left>=contextBox.right,provider+' wide action stays beside context usage');
   else check(actionBox.top>=contextBox.bottom,provider+' narrow action has its own row');
   check(actionBox.right<=innerWidth,provider+' action fits viewport');
   quotes.action.dispatchEvent(new Event('pointerdown'));selection.removeAllRanges();quotes.capture();quotes.action.click();
   check(quotes.quotes[0]?.text==='Selected repl'&&changes===1,provider+' pointer selection survives focus collapse');
   check(input.value==='Existing draft',provider+' quoting preserves draft');
   const multiline='First line\nSecond line\n'+('Long quote content '.repeat(30));quotes.restore([{text:multiline,provider}]);
   const details=quotes.root.querySelector('details'),summary=details.querySelector('summary'),full=details.querySelector('.composer-quote-full');
   const style=getComputedStyle(summary),lineHeight=parseFloat(style.lineHeight)||parseFloat(style.fontSize)*1.5;
   check(!details.open&&style.whiteSpace==='nowrap'&&summary.getBoundingClientRect().height<=lineHeight+2,provider+' collapsed multiline quote occupies one line');
   check(summary.getBoundingClientRect().right<=innerWidth,provider+' collapsed preview fits viewport');
   summary.click();check(details.open&&full.textContent===multiline&&full.getBoundingClientRect().height>0,provider+' full quote remains expandable');
   input.focus();check(quotes.action.hidden&&quotes.quotes[0].text===multiline,provider+' input focus hides action while retaining quote');
  }finally{quotes.reset();root.remove();getSelection().removeAllRanges();}
 }
 return results;
};
