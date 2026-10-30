'use strict';
// Shared by chat fences and file previews; token text never passes through HTML.
window.BridgeCodeSyntax = (() => {
  const labels = {markup:'HTML',css:'CSS',clike:'C-like',javascript:'JavaScript',python:'Python',typescript:'TypeScript',jsx:'JSX',tsx:'TSX',json:'JSON',yaml:'YAML',toml:'TOML',bash:'Bash',powershell:'PowerShell',batch:'Batch'};
  const aliases = {html:'markup',xml:'markup',svg:'markup',js:'javascript',mjs:'javascript',cjs:'javascript',py:'python',py3:'python',python3:'python',ts:'typescript',yml:'yaml',sh:'bash',shell:'bash',zsh:'bash',ps1:'powershell',bat:'batch',cmd:'batch'};
  const languageFor = info => {
    const name = String(info || '').trim().split(/\s/,1)[0].toLowerCase();
    return Object.hasOwn(aliases,name) ? aliases[name] : Object.hasOwn(labels,name) ? name : null;
  };
  const plainLabel = () => typeof BridgeI18n === 'undefined' ? '纯文本' : BridgeI18n.t('纯文本');
  const label = language => labels[language] || plainLabel();
  const eligible = text => text.length <= 65536 && (text.match(/\r\n|\r|\n/g) || []).length < 4000;
  const tokenize = (text, language) => {
    const grammar = language && eligible(text) && window.Prism?.languages[language];
    if (grammar) try { return window.Prism.tokenize(text,grammar); } catch (_) { /* Preserve the source on grammar failure. */ }
    return text;
  };
  const append = (node, items) => {
    for (const token of Array.isArray(items) ? items : [items]) {
      if (typeof token === 'string') node.append(document.createTextNode(token));
      else {
        const span = document.createElement('span');
        span.className = ['token',token.type,...[].concat(token.alias || [])].join(' ');
        append(span,token.content);node.append(span);
      }
    }
  };
  document.addEventListener('bridge-language',()=>document.querySelectorAll('.code-language').forEach(node=>{node.textContent=label(node.dataset.language);}));
  return {languageFor,label,eligible,tokenize,append};
})();
