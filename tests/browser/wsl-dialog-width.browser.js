// Isolated production-page fixture only. Synthetic WSL reads; never switches an account or sends a chat.
window.runWslDialogWidthChecks=async function({kind='accounts',provider='codex',language='zh',assert=true}={}){
  window.__wslLayoutCleanup?.();
  BridgeI18n.setLanguage(language);BridgeI18n.apply();
  const distribution='Nvidia_SDKM_Ubuntu_22.04_JetPack_6.2.1',longName='SavedAccountWithoutSpaces'.repeat(5);
  let dialog,panel;
  if(kind==='accounts'){
    dialog=document.createElement('dialog');dialog.className='picker ds-picker';
    const head=document.createElement('div');head.className='picker-head';
    const heading=document.createElement('div');heading.className='accounts-dialog-heading';
    const title=document.createElement('h2');title.textContent=BridgeI18n.t('账号与接入');heading.append(title);
    const close=document.createElement('button');close.className='icon-button';close.textContent='×';close.onclick=()=>dialog.close();head.append(heading,close);
    const controls=document.createElement('div');controls.className='accounts-runtime-controls';
    const label=document.createElement('label');label.append(BridgeI18n.t('运行环境'));
    const select=document.createElement('select');select.append(new Option('WSL '+provider+' · '+distribution,'wsl'));label.append(select);controls.append(label);
    const root=document.createElement('div');dialog.append(head,controls,root);document.body.append(dialog);
    panel=new WslAccountsPanel({root,provider,read:async entry=>({entry,provider,available:true,activeVerified:false,identity:'synthetic',target:{distribution,user:'fixture',configDir:'/home/fixture/.codex'},accounts:[{id:'fake',name:longName,kind:'api',baseUrl:'https://example.invalid/'+longName,model:'synthetic-model'}],capabilities:{save:true,import:true,models:true,switch:true}}),request:async()=>{throw Error('Writes prohibited in layout fixture');}});
    await panel.select('wsl');
    panel.sources=[{id:'fake-import',name:longName,source:'synthetic'}];panel.render();
    root.querySelectorAll('details').forEach(node=>node.open=true);
  }else{
    dialog=document.getElementById('new-chat-dialog').cloneNode(true);dialog.removeAttribute('id');
    dialog.querySelector('#new-chat-entry-label').hidden=false;
    dialog.querySelector('#new-chat-type').value='wsl';
    dialog.querySelector('#new-chat-entry').append(new Option(provider+' · '+distribution,'wsl'));
    dialog.querySelector('#new-chat-project').append(new Option(longName,'synthetic'));
    dialog.querySelector('form').onsubmit=event=>{event.preventDefault();throw Error('Submission prohibited');};
    document.body.append(dialog);
  }
  window.__wslLayoutCleanup=()=>{panel?.dispose();dialog.close();dialog.remove();delete window.__wslLayoutCleanup;};
  dialog.showModal();
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  const rect=dialog.getBoundingClientRect(),contentLeft=rect.left+parseFloat(getComputedStyle(dialog).paddingLeft),contentRight=rect.right-parseFloat(getComputedStyle(dialog).paddingRight);
  const overflowing=[...dialog.querySelectorAll('h2,h3,strong,small,select,input,button,label,section,.wsl-account-actions')].filter(node=>{
    const bounds=node.getBoundingClientRect();return bounds.width>0&&(bounds.left<contentLeft-2||bounds.right>contentRight+2);
  }).map(node=>({tag:node.tagName,class:node.className,width:Math.round(node.getBoundingClientRect().width)}));
  dialog.scrollLeft=1000;
  const selectFontSizes=[...dialog.querySelectorAll('select')].filter(node=>node.getBoundingClientRect().width>0).map(node=>parseFloat(getComputedStyle(node).fontSize));
  const result={kind,provider,language,viewport:innerWidth,dialogWidth:Math.round(rect.width),clientWidth:dialog.clientWidth,scrollWidth:dialog.scrollWidth,scrollLeft:dialog.scrollLeft,overflowing,selectFontSizes};
  if(assert&&innerWidth<=600&&selectFontSizes.some(size=>size<16))throw Error('Narrow native selects must use at least 16px: '+JSON.stringify(result));
  if(assert&&(rect.left<0||rect.right>innerWidth||dialog.scrollWidth>dialog.clientWidth+1||dialog.scrollLeft!==0||overflowing.length))throw Error(JSON.stringify(result));
  return result;
};
