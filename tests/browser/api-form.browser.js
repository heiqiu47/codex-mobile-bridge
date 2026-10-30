// Exercise the actual production panel and styles; requests stay in memory.
async function runApiFormBrowserChecks(){
  const panel=codexCliAccessPanel,dialog=document.getElementById('accounts-dialog');
  const old={read:panel.read,request:panel.request,onChanged:panel.onChanged};
  const checks=[],requests=[],check=(value,label)=>{if(!value)throw Error(label);checks.push(label);};
  const fixture={codex:{accounts:[]}};
  const until=async predicate=>{const end=performance.now()+2000;while(!predicate()){
    if(performance.now()>end)throw Error('Synthetic API form action did not complete');
    await new Promise(resolve=>setTimeout(resolve,10));
  }};
  try{
    panel.read=async()=>fixture;panel.onChanged=()=>{};
    panel.request=async value=>{requests.push({...value});return value.action==='modelsDraft'?{models:['fixture-model','fixture-alternate']}:fixture;};
    await panel.refresh();dialog.showModal();codexCliDetails.open=false;
    const summary=codexCliDetails.querySelector('summary'),reference=accountsPanel.tools.querySelector('summary');
    check(getComputedStyle(summary).fontWeight===getComputedStyle(reference).fontWeight,'Collapsed API heading keeps the reminder heading style');
    summary.click();check(codexCliDetails.open,'API form expands from its actual summary');
    for(const field of [panel.name,panel.baseUrl,panel.key]){
      check(field.input.labels.length>0&&field.input.labels[0].textContent.trim(),'Connection input has a visible label');
      check(field.input.placeholder.length>0,'Empty connection input explains what to enter');
      const style=getComputedStyle(field.input);
      check(parseFloat(style.borderTopWidth)>0||style.backgroundColor!==getComputedStyle(field.label).backgroundColor,'Input remains visually identifiable');
    }
    panel.name.input.value='Synthetic API';panel.baseUrl.input.value='https://synthetic.invalid/v1';panel.key.input.value='synthetic-key';
    panel.fetchModels.click();await until(()=>!panel.draftLoading);
    check(panel.model.input.value==='fixture-model'&&!panel.modelSelect.hidden,'Upstream models populate the default selection');
    panel.modelSelect.value='fixture-alternate';panel.modelSelect.dispatchEvent(new Event('change'));
    panel.save.click();await until(()=>requests.some(value=>value.action==='saveApi')&&!panel.busy);
    check(requests.at(-1).action==='saveApi'&&requests.at(-1).model==='fixture-alternate','Saving uses the user-selected model');
    check(panel.key.input.value==='','Completed save clears the secret input');
    codexCliDetails.open=true;
    check(dialog.scrollWidth<=dialog.clientWidth+1,'The account dialog has no horizontal overflow');
    for(const input of panel.form.querySelectorAll('input:not([hidden]),select:not([hidden]),button')){
      if(!input.getClientRects().length)continue;
      const bounds=input.getBoundingClientRect(),container=dialog.getBoundingClientRect();
      check(bounds.left>=container.left-1&&bounds.right<=container.right+1,'Form controls stay inside the dialog');
    }
    return {passed:checks.length,checks,width:innerWidth};
  }finally{
    panel.clear();Object.assign(panel,old);dialog.close();
  }
}
