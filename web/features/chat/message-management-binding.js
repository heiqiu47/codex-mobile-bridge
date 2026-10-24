'use strict';

// The manager edits its own draft. The chat composer is never an edit buffer.
class MessageManagementBinding {
  constructor({target,request,notify,translate,beforeOpen=()=>{},onChanged,Panel=MessageManagement}){
    Object.assign(this,{target,request,notify,translate,beforeOpen,onChanged});
    this.reads=new Map();
    this.panel=new Panel({scope:()=>this.current().scope,t:translate,uuid:()=>this.current().uuid(),
      beforeOpen,load:scope=>this.load(scope),localRecords:scope=>this.records(this.current(scope)),
      reorder:(scope,value)=>this.change(scope,'reorder',value),withdraw:(scope,value)=>this.change(scope,'withdraw',value),
      ignore:(scope,value)=>this.change(scope,'ignore',value),ignoreLocal:(scope,record)=>this.ignoreLocal(scope,record),
      edit:(scope,value)=>this.change(scope,'edit',value),loadEditor:scope=>this.loadEditor(scope),
      saveEditor:(scope,value,previous)=>this.saveEditor(scope,value,previous),onError:notify,onChanged:()=>onChanged?.()});
  }
  current(scope){
    const target=this.target();
    if(!target?.scope||!target.drafts?.key(target.scope)||scope&&target.drafts.key(scope)!==target.drafts.key(target.scope))throw Error('聊天或账号已切换，请重新打开消息管理');
    return target;
  }
  options(target,records){return {temporary:target.temporary,temporaryKey:target.temporaryKey,...(records?{records}:{})};}
  records(target){return target.drafts.pendingRecords(target.scope,this.options(target));}
  async load(scope){
    const target=this.current(scope),records=this.records(target);
    if(!target.url)return {version:'',queue:[],unknown:[],receipts:[],capabilities:{reorder:false,withdraw:false,edit:false},reason:'此接入的排队消息由原生客户端管理，请在电脑端处理。'};
    const editor=this.loadEditor(scope),ids=[...new Set([...records.map(row=>row.id),editor?.id,editor?.sourceId].filter(Boolean))];
    let result,identityRetries=0;
    // Legacy and editor receipts stay bounded; repeated reads do not dispatch work.
    for(let index=0;index<Math.max(1,ids.length);index+=16){
      const query=ids.slice(index,index+16).map(id=>'id='+encodeURIComponent(id)).join('&');
      let response;
      for(;;){
        response=await this.request(target.url+(query?(target.url.includes('?')?'&':'?')+query:''));
        this.current(scope);
        if(response.draftAccountIdentity===scope.account)break;
        if(response.identityPending!==true||response.draftAccountIdentity||identityRetries===3)throw Error('账号状态尚未确认，请稍后重试');
        await new Promise(resolve=>setTimeout(resolve,[250,500,1000][identityRetries++]));
        this.current(scope);
      }
      result=result?{...response,receipts:[...result.receipts,...response.receipts]}:response;
    }
    await target.drafts.reconcilePending(scope,{scope,receipts:result.receipts},this.options(target,records));
    this.current(scope);this.onChanged?.();return result;
  }
  reconcile(){
    let target;try{target=this.current();}catch{return Promise.resolve(null);}
    if(!target.url||!this.records(target).length)return Promise.resolve(null);
    const key=target.drafts.key(target.scope);
    if(this.reads.has(key))return this.reads.get(key);
    const task=this.load(target.scope).catch(()=>null).finally(()=>this.reads.delete(key));
    this.reads.set(key,task);return task;
  }
  async change(scope,action,value){
    const target=this.current(scope);
    if(!target.url)throw Error('此接入的排队消息由原生客户端管理，请在电脑端处理。');
    const result=await this.request(target.url,{...value,action,expectedAccount:scope.account});
    this.current(scope);this.onChanged?.();return result;
  }
  async ignoreLocal(scope,record){
    const target=this.current(scope);
    const result=await target.drafts.ignoreLocalPending(scope,record,this.options(target));
    this.current(scope);this.onChanged?.();return result;
  }
  loadEditor(scope){const target=this.current(scope);return target.drafts.read(target.drafts.key(scope,'queue-editor'));}
  async saveEditor(scope,value,previous){
    const target=this.current(scope),key=target.drafts.key(scope,'queue-editor');
    const expected=JSON.stringify(previous===undefined?this.loadEditor(scope):previous);
    const result=await target.drafts.coordinate(()=>{
      this.current(scope);
      if(JSON.stringify(target.drafts.read(key))!==expected)return {conflict:true};
      if(value===null){target.drafts.remove(key);return {ok:target.drafts.read(key)===null};}
      return {ok:target.drafts.write(key,value)};
    });
    if(result?.conflict)throw Error('编辑记录已在另一页面更新，请重新打开消息管理');
    if(!result?.ok)throw Error('无法保存编辑内容，请检查设备存储后重试');
    return true;
  }
  async open(){try{return await this.panel.open();}catch(error){this.notify(this.translate(error.message));}}
}
if(typeof module!=='undefined')module.exports={MessageManagementBinding};
