'use strict';

// Drafts stay on this device. Every read requires a verified gateway and account scope.
class ComposerDrafts {
  constructor(storage=localStorage,coordinator=globalThis.indexedDB){this.storage=storage;this.coordinator=coordinator;this.temporaryPending=new Map();}
  key(scope,kind='draft'){
    if(!scope||!['gateway','provider','account','host','session'].every(name=>typeof scope[name]==='string'&&scope[name]))return null;
    return 'composer-v1:'+kind+':'+JSON.stringify([scope.gateway,scope.provider,scope.account,scope.host,scope.session]);
  }
  read(key){if(!key)return null;try{return JSON.parse(this.storage.getItem(key)||'null');}catch{return null;}}
  write(key,value){if(!key)return false;try{this.storage.setItem(key,JSON.stringify(value));return true;}catch{return false;}}
  remove(key){if(!key)return;try{this.storage.removeItem(key);}catch{}}
  load(scope){const saved=this.read(this.key(scope));return saved&&typeof saved.text==='string'?saved:null;}
  save(scope,fields){
    const key=this.key(scope);if(!key)return null;
    const previous=this.load(scope),text=String(fields.text||'').slice(0,100000);
    const draft={text,selectionStart:Math.max(0,Math.min(text.length,Number(fields.selectionStart)||0)),selectionEnd:Math.max(0,Math.min(text.length,Number(fields.selectionEnd)||0)),sendMode:fields.sendMode||'send',workMode:fields.workMode||'default',quotes:Array.isArray(fields.quotes)?fields.quotes.filter(value=>value&&typeof value.text==='string'&&value.text.trim()).slice(0,8).map(value=>({text:value.text.slice(0,100000),source:typeof value.source==='string'?value.source.slice(0,500):'',provider:typeof value.provider==='string'?value.provider.slice(0,40):''})):[],skills:Array.isArray(fields.skills)?fields.skills.filter(value=>typeof value==='string').slice(0,8):[],revision:previous?.revision||0};
    if(JSON.stringify({...draft,revision:0})!==JSON.stringify({...previous,revision:0}))draft.revision++;
    return this.write(key,draft)?draft:null;
  }
  clear(scope){this.remove(this.key(scope));}
  pending(scope){const saved=this.read(this.key(scope,'pending'));return saved&&typeof saved.id==='string'&&saved.id?saved:null;}
  discardPending(scope,id){if(this.pending(scope)?.id===id)this.remove(this.key(scope,'pending'));}
  begin(scope,body,id){
    const key=this.key(scope,'pending');if(!key)return null;
    const fingerprint=JSON.stringify(body),previous=this.pending(scope);
    if(previous?.fingerprint===fingerprint)return previous;
    if(previous?.body?.text===body.text)return {...previous,blocked:true};
    const pending={id,fingerprint,body};return this.write(key,pending)?pending:null;
  }
  confirm(scope,id,revision){
    const pending=this.pending(scope);if(pending?.id!==id)return false;
    this.remove(this.key(scope,'pending'));
    if(this.load(scope)?.revision===revision)this.clear(scope);
    return true;
  }
  // Only coordinated clients use this key: an older page cannot silently join an
  // attempt without registering it. Imported v1 requests remain untracked.
  coordinate(update){
    if(!this.coordinator)return Promise.resolve(null);
    return new Promise(resolve=>{
      let done=false,db,transaction,value;
      const finish=result=>{if(done)return;done=true;clearTimeout(timer);db?.close();resolve(result);};
      const timer=setTimeout(()=>{try{transaction?.abort();}catch{}finish(null);},2000);
      let request;try{request=this.coordinator.open('composer-pending-v2',1);}catch{finish(null);return;}
      request.onupgradeneeded=()=>request.result.createObjectStore('mutex');
      request.onblocked=request.onerror=()=>finish(null);
      request.onsuccess=()=>{
        db=request.result;if(done){db.close();return;}
        db.onversionchange=()=>db.close();
        try{
          transaction=db.transaction('mutex','readwrite');
          transaction.oncomplete=()=>finish(value);
          transaction.onabort=transaction.onerror=()=>finish(null);
          transaction.objectStore('mutex').get('pending').onsuccess=()=>{
            if(done)return;
            try{value=update(true);}catch{transaction.abort();}
          };
        }catch{finish(null);}
      };
    });
  }
  pendingSend(scope){const saved=this.read(this.key(scope,'pending-v2')),old=this.pending(scope);return saved?.id?saved:old&&saved?.legacyVersion!==JSON.stringify(old)?old:null;}
  async beginSend(scope,body,id,attempt,imported=false){
    if(!this.coordinator)return this.pendingSend(scope)?{blocked:true}:false;
    const result=await this.coordinate(coordinated=>{
      const key=this.key(scope,'pending-v2');if(!key)return null;
      const saved=this.read(key),old=this.pending(scope),legacyVersion=old?JSON.stringify(old):null;
      const unseenLegacy=old&&saved?.legacyVersion!==legacyVersion;
      const fingerprint=JSON.stringify(body);
      // A still-open v1 page may write another unknown after v2 was settled.
      // Never hide that new version behind a tombstone or an active v2 request.
      if(unseenLegacy&&(saved?.id||old.fingerprint!==fingerprint))return {blocked:true};
      const previous=unseenLegacy?old:saved;
      if(previous?.body?.text===body.text&&previous.fingerprint!==fingerprint)return {...previous,blocked:true};
      const same=previous?.fingerprint===fingerprint;
      const pending=same?{...previous}:{id,fingerprint,body};
      pending.attempts=[...(same&&Array.isArray(previous.attempts)?previous.attempts:[]),attempt];
      pending.untracked=!!(same&&(previous.untracked||unseenLegacy)||imported||!coordinated);
      pending.legacyVersion=unseenLegacy?legacyVersion:saved?.legacyVersion??null;
      return this.write(key,pending)?pending:false;
    });
    return result===null?(this.pendingSend(scope)?{blocked:true}:false):result;
  }
  settleSend(scope,id,attempt,action,revision){
    return this.coordinate(coordinated=>{
      if(!coordinated)return false;
      const key=this.key(scope,'pending-v2'),saved=this.read(key),old=this.pending(scope),legacyVersion=old?JSON.stringify(old):null;
      if(action==='ignore'&&old?.id===id&&saved?.id!==id){
        return this.write(key,{...(saved||{cleared:true}),legacyVersion});
      }
      const pending=saved??(action==='ignore'?old:null);
      if(pending?.id!==id)return false;
      if(action==='reject'){
        if(!pending.attempts?.includes(attempt))return false;
        pending.attempts=pending.attempts.filter(value=>value!==attempt);
        if(old&&pending.legacyVersion!==legacyVersion)pending.untracked=true;
        if(pending.untracked||pending.attempts.length){this.write(key,pending);return false;}
      }
      // A tombstone prevents reimporting v1 without racing an older page's writes.
      if(!this.write(key,{cleared:true,legacyVersion:action==='ignore'&&old?.id===id?legacyVersion:pending.legacyVersion??null}))return false;
      // Do not remove a legacy record written by a still-open older page.
      if(action==='confirm'&&this.load(scope)?.revision===revision)this.clear(scope);
      return true;
    });
  }
  migrate(scope,temporary,keys){
    if(!this.key(scope)||this.load(scope))return this.load(scope);
    let text;try{text=temporary.getItem(keys.text);}catch{return null;}
    if(text===null)return null;
    let skills=[];try{skills=JSON.parse(temporary.getItem(keys.skills)||'[]');}catch{}
    const saved=this.save(scope,{text,skills,sendMode:'send',workMode:'default'});
    if(saved)for(const key of Object.values(keys))try{temporary.removeItem(key);}catch{}
    return saved;
  }
}

if(typeof module!=='undefined')module.exports={ComposerDrafts};
