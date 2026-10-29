// Synthetic models only; no native client or upstream request is allowed.
window.runAgentModelSettingsChecks=async function(options={}){
 await BridgeFeatures.load('chat');
 const checks=[],check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 for(const provider of options.provider?[options.provider]:['claude','deepseek']){
  const view=desktopSessions,originalRequest=view.request;let keep=false;
  const writes=[];let release;
  view.request=async(url,body)=>{
   if(body){writes.push(body);return {status:'accepted'};}
   if(url.includes('/catalog'))return new Promise(resolve=>release=resolve);
   if(url.includes('/detail'))return {session:{id:'synthetic',title:(options.surface||provider)+' · 模型设置测试',backend:options.surface||'code',model:provider==='deepseek'?'provider/old':'old-model',status:'idle'},capabilities:{models:true,effort:true,manualModels:true,manualEffort:true},modelCatalogIdentity:'same-account',messages:[{id:'user',role:'user',text:'请检查这个测试会话的模型设置。'},{id:'reply',role:'assistant',text:'可以在下方切换模型与思考强度。'}]};
   return {sessions:[]};
  };
  try{
   await view.choose(provider);await view.open('synthetic');
   const opening=view.models();await Promise.resolve();
   const dialog=document.querySelector('dialog.ds-model-dialog[open]'),model=dialog.querySelector('.ds-manual-model');
   check(!!dialog&&!model.hidden,provider+' manual model is available during slow catalog discovery');
   model.value=provider==='deepseek'?'provider/manual':'manual-model';model.dispatchEvent(new Event('input'));
   const custom=dialog.querySelector('.effort-options input[value="__custom__"]');custom.click();
   const effort=dialog.querySelector('.ds-manual-effort');effort.value='high';effort.dispatchEvent(new Event('input'));
   check(!dialog.querySelector('.primary').disabled,provider+' manual model and reasoning are usable before discovery completes');
   release({models:[],capabilities:{models:true,manualModels:true,manualEffort:true},cache:{identity:'same-account'}});await opening;
   check(model.value.endsWith('manual')||model.value==='manual-model',provider+' catalog completion preserves manual draft');
   check(!dialog.textContent.includes('muted')&&!dialog.textContent.includes('账号已切换'),provider+' empty catalog does not invent account-switch failure or style text');
   const box=dialog.getBoundingClientRect(),input=model.getBoundingClientRect();check(box.width<=innerWidth&&input.right<=box.right,provider+' controls fit viewport');
   if(options.leaveOpen){keep=true;return checks;}
   await dialog.querySelector('form').onsubmit({preventDefault(){}});
   check(writes.length===1&&writes[0].effort==='high'&&writes[0].manualEffort===true,provider+' manual choice reaches settings request once');
  }finally{release?.({models:[],cache:{identity:'same-account'}});if(!keep){view.modelDialog?.close();view.request=originalRequest;}}
 }
 return checks;
};
