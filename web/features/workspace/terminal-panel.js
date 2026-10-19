'use strict';

class TerminalPanel {
  constructor(workbench, session, tab) {
    Object.assign(this, {workbench, session, tab});this.disposed=false;this.cursor=0;this.running=false;this.operations=[];this.composing=false;this.completionVersion=0;
    this.visibility=()=>{clearTimeout(this.timer);if(document.hidden)this.readController?.abort();else if(this.running){if(this.polling)this.resumeRead=true;else this.poll();}};
    document.addEventListener('visibilitychange',this.visibility);
    this.key='pty:'+session.key;
    try{this.id=sessionStorage.getItem(this.key);}catch{}
    this.hadId=!!this.id;this.id ||= uuid();this.save();
    this.tab.name=BridgeI18n.t('终端 · 连接中');this.workbench.paint();
    this.load();
  }
  save(){try{sessionStorage.setItem(this.key,this.id);}catch{}}
  url(extra=''){return this.workbench.endpoint(this.session,'terminal')+'&mode=pty'+extra;}
  async load(){
    try{
      const info=await this.workbench.request(this.url());if(this.disposed)return;
      if(info.mode==='command'){
        this.fallback=new CommandTerminalPanel(this.workbench,this.session,this.tab);return;
      }
      this.render(info);
      if(this.hadId){this.running=true;await this.poll();this.focusOnSelect();return;}
      const result=await this.workbench.request(this.url(),{action:'open',id:this.id,cols:this.term.cols,rows:this.term.rows});
      if(this.disposed){if(!this.hadId)this.workbench.request(this.url(),{action:'close',id:this.id}).catch(()=>{});return;}
      this.apply(result);this.schedule();this.focusOnSelect();
    }catch(e){if(!this.disposed){if(!this.status)this.render({});this.status.textContent=BridgeI18n.t(e.message);this.reopen.hidden=false;this.tab.name=BridgeI18n.t('终端 · 未连接');this.workbench.paint();}}
  }
  render(info){
    const n=(...a)=>this.workbench.node(...a),b=(...a)=>this.workbench.button(...a);
    this.tab.body.replaceChildren();this.tab.body.classList.add('wb-pty');
    const head=n('div','wb-terminal-head');this.location=n('strong','',info.shell||BridgeI18n.t('连接终端…'));
    this.reopen=b(BridgeI18n.t('重新打开'),()=>this.restart());this.reopen.hidden=true;
    head.append(this.location,b(BridgeI18n.t('清屏'),()=>this.term.clear()),this.reopen);
    this.shellHint=n('small','wb-terminal-shell-hint',BridgeI18n.t('跨盘切换示例：cd /d D:\\（进入 D 盘根目录）。'));this.shellHint.hidden=!/(^|[\\/])cmd(?:\.exe)?$/i.test(info.shell||'');
    this.screen=n('div','wb-terminal-screen');this.screen.setAttribute("data-i18n-aria-label",'交互终端');this.screen.setAttribute('aria-label',BridgeI18n.t('交互终端'));
    this.status=n('p','wb-status');this.status.setAttribute('role','status');
    const keys=n('div','wb-terminal-keys');
    for(const [label,value] of [['Ctrl+C','\x03'],['Tab','\t'],['Esc','\x1b'],['↑','\x1b[A'],['↓','\x1b[B'],['←','\x1b[D'],['→','\x1b[C']])keys.append(b(label,()=>label==='Tab'&&this.mobile()?this.complete():this.enqueue(value)));
    this.form=n('form','wb-terminal-input');this.input=n('textarea');this.input.rows=2;this.input.setAttribute("data-i18n-placeholder",'输入命令或回复，换行键可换行');this.input.placeholder=BridgeI18n.t('输入命令或回复，换行键可换行');this.input.setAttribute("data-i18n-aria-label",'终端输入');this.input.setAttribute('aria-label',BridgeI18n.t('终端输入'));this.input.setAttribute('autocapitalize','off');this.input.setAttribute('autocorrect','off');this.input.spellcheck=false;
    this.send=n('button','',BridgeI18n.t('发送到终端'));this.send.type='submit';this.send.disabled=true;
    this.form.append(this.input,this.send);this.form.onsubmit=e=>{e.preventDefault();this.submit();};
    this.input.addEventListener('compositionstart',()=>{this.composing=true;this.clearCompletion();});
    this.input.addEventListener('compositionend',()=>{this.composing=false;this.clearCompletion();});
    this.input.addEventListener('input',()=>this.clearCompletion());
    this.input.addEventListener('click',()=>this.clearCompletion());
    this.input.addEventListener('select',()=>this.clearCompletion());
    this.input.addEventListener('keydown',e=>{if(e.key==='Tab'&&this.mobile()&&!e.isComposing&&!this.composing){e.preventDefault();this.complete();}else if(e.key!=='Tab')this.clearCompletion();});
    this.completions=n('div','wb-terminal-completions');this.completions.hidden=true;
    // Enter in the mobile composer ALWAYS inserts a newline. Submit is explicit.
    this.retry=b(BridgeI18n.t('重试未确认输入'),()=>{this.inputError=false;this.retry.hidden=true;this.flush();});this.retry.hidden=true;
    this.tab.body.append(head,this.shellHint,this.screen,keys,this.form,this.completions,this.status,this.retry);
    this.term=new Terminal({fontSize:14,fontFamily:'Menlo, Consolas, monospace',cursorBlink:true,scrollback:2000,
      theme:{background:'#11151b',foreground:'#e2e8f0',cursor:'#7ee0b6'},allowProposedApi:false,
      linkHandler:{activate:()=>{}},disableStdin:true});
    // Terminal output must never write to or read the system clipboard (OSC 52).
    this.term.parser.registerOscHandler(52,()=>true);
    this.fit=new FitAddon.FitAddon();this.term.loadAddon(this.fit);this.term.open(this.screen);
    this.term.onData(data=>this.enqueue(data));
    this.term.onResize(({cols,rows})=>{clearTimeout(this.resizeTimer);this.resizeTimer=setTimeout(()=>{if(this.running&&!this.disposed)this.workbench.request(this.url(),{action:'resize',id:this.id,cols,rows}).catch(e=>this.status.textContent=BridgeI18n.t(e.message));},120);});
    this.observer=new ResizeObserver(()=>this.layout());this.observer.observe(this.screen);this.layout();
  }
  mobile(){return BridgeHost.hasNativeLayout()||((navigator.userAgentData?.mobile||/\b(?:iPhone|Android|Mobile)\b/i.test(navigator.userAgent||''))&&BridgeLayout.prefersTouchInput()&&BridgeLayout.isCompactViewport());}
  layout(){
    if(this.disposed||!this.screen?.clientHeight||!this.screen.clientWidth)return;
    this.tab.body.classList.toggle('wb-terminal-touch',this.mobile());this.term.options.disableStdin=!this.running||this.mobile()||this.inputError;
    const size=this.fit.proposeDimensions?.();if(size&&(size.cols!==this.term.cols||size.rows!==this.term.rows))this.fit.fit();
  }
  focusOnSelect(){
    if(this.disposed||!this.running||this.mobile()||!this.workbench.isVisible(this.session,this.tab)||document.hidden||this.composing)return;
    if(document.querySelector('dialog[open]')||window.getSelection?.()?.toString())return;
    const active=document.activeElement;
    if(active&&active!==document.body&&!this.tab.body.contains(active)&&active.matches?.('input,textarea,[contenteditable="true"]'))return;
    this.layout();
    this.term.focus();
  }
  clearCompletion(){this.completionVersion++;if(this.completions){this.completions.hidden=true;this.completions.replaceChildren();}}
  async complete(){
    if(!this.running||this.disposed||!this.mobile()||this.composing||this.inputError)return;
    this.clearCompletion();const version=this.completionVersion,id=this.id,text=this.input.value,selectionStart=this.input.selectionStart,selectionEnd=this.input.selectionEnd;
    if(selectionStart!==selectionEnd)return;
    try{
      const result=await this.workbench.request(this.url(),{action:'complete',id,text,selectionStart});
      if(this.disposed||id!==this.id||version!==this.completionVersion||text!==this.input.value||selectionStart!==this.input.selectionStart||selectionEnd!==this.input.selectionEnd||!this.mobile()||!this.workbench.isVisible(this.session,this.tab))return;
      const candidates=result.candidates||[];
      const apply=candidate=>{
        if(version!==this.completionVersion||text!==this.input.value||selectionStart!==this.input.selectionStart||selectionEnd!==this.input.selectionEnd||id!==this.id||!this.workbench.isVisible(this.session,this.tab))return;
        this.input.setRangeText(candidate.insertText,result.replaceStart,result.replaceEnd,'end');this.clearCompletion();this.input.focus();
      };
      if(candidates.length===1){apply(candidates[0]);return;}
      if(!candidates.length){this.completions.append(this.workbench.node('span','',BridgeI18n.t('没有匹配的路径')));this.completions.hidden=false;return;}
      this.completions.append(this.workbench.node('span','',BridgeI18n.t('选择路径补全')));
      for(const candidate of candidates){const button=this.workbench.button(candidate.label,()=>apply(candidate));button.type='button';this.completions.append(button);}
      if(result.truncated)this.completions.append(this.workbench.node('small','',BridgeI18n.t('仅显示部分匹配项')));
      this.completions.hidden=false;
    }catch(e){if(!this.disposed&&version===this.completionVersion)this.status.textContent=BridgeI18n.t(e.message);}
  }
  async submit(){
    if(!this.running||this.send.disabled)return;
    const text=this.input.value;
    // xterm honours bracketed-paste mode set by the active shell/application.
    if(text){this.term.options.disableStdin=false;this.term.paste(text);this.layout();}
    this.enqueue('\r');this.input.value='';this.clearCompletion();this.input.focus();
  }
  enqueue(data){
    if(!this.running||this.disposed)return;
    // Keep each Unicode character intact while staying below the server input cap.
    let chunk='';for(const char of data){if(chunk.length+char.length>3000){this.queueChunk(chunk);chunk='';}chunk+=char;}
    if(chunk)this.queueChunk(chunk);
    clearTimeout(this.flushTimer);this.flushTimer=setTimeout(()=>this.flush(),12);
  }
  queueChunk(data){
    const tail=this.operations[this.operations.length-1];
    if(tail&&!tail.sent&&tail.data.length+data.length<=3000)tail.data+=data;
    else this.operations.push({id:uuid(),data,sent:false});
  }
  async flush(){
    if(this.flushing||this.inputError||this.disposed)return;
    clearTimeout(this.flushTimer);
    this.flushing=true;
    try{
      while(this.operations.length&&!this.disposed){
        const entry=this.operations[0];entry.sent=true;
        await this.workbench.request(this.url(),{action:'input',id:this.id,inputId:entry.id,data:entry.data});
        this.operations.shift();
      }
    }catch(e){if(!this.disposed){this.inputError=true;this.status.textContent=BridgeI18n.t(e.message)+BridgeI18n.t(' · 输入结果未确认；重试不会重复输入。');this.retry.hidden=false;this.send.disabled=true;this.term.options.disableStdin=true;}}
    finally{this.flushing=false;if(!this.disposed&&!this.inputError){this.send.disabled=!this.running;this.layout();}}
  }
  apply(result){
    if(result.reset)this.term.reset();
    if(result.output)this.term.write(result.output);
    this.cursor=result.cursor;this.running=result.running;
    const label=BridgeI18n.t(result.running?'终端 · 已连接':'终端 · 已退出');if(this.tab.name!==label){this.tab.name=label;this.workbench.paint();}
    this.location.textContent=result.shell||BridgeI18n.t('终端');this.location.title=result.cwd||'';
    if(!this.inputError)this.status.textContent=result.running?BridgeI18n.t('连续会话 · 关闭标签将结束终端'):result.message||BridgeI18n.t('终端已退出');
    this.send.disabled=!this.running||this.inputError;this.reopen.hidden=this.running;this.layout();
  }
  schedule(error=false,idle=false){clearTimeout(this.timer);if(!this.disposed&&this.running&&!document.hidden&&!this.restarting)this.timer=setTimeout(()=>this.poll(),error?750:(!this.workbench.isVisible(this.session,this.tab)?500:idle?35:0));}
  async poll(){
    if(this.disposed||document.hidden||this.polling||!this.running||this.restarting)return;
    this.polling=true;clearTimeout(this.timer);const id=this.id,controller=this.readController=new AbortController();
    let error=false,idle=false;
    try{const result=await this.workbench.request(this.url('&id='+this.id+'&after='+this.cursor+'&waitMs=1000'),undefined,controller.signal);if(!this.disposed&&!controller.signal.aborted&&this.id===id){idle=!result.output&&result.cursor===this.cursor;this.apply(result);}}
    catch(e){if(!this.disposed&&!controller.signal.aborted&&this.id===id){error=true;this.status.textContent=BridgeI18n.t(e.message);if([401,403,404].includes(e.status)){this.running=false;this.send.disabled=true;this.reopen.hidden=false;}}}
    finally{
      this.polling=false;this.readController=null;
      const resume=this.resumeRead;this.resumeRead=false;
      if(resume&&!this.disposed&&!document.hidden)this.poll();else this.schedule(error,idle);
    }
  }
  async restart(){
    if(this.restarting)return;this.restarting=true;this.readController?.abort();clearTimeout(this.timer);
    try{
      // Close the previous id even after a lost open response; never orphan a shell.
      try{await this.workbench.request(this.url(),{action:'close',id:this.id});}catch(e){if(e.status!==404)throw e;}
      this.id=uuid();this.save();this.cursor=0;this.operations=[];this.inputError=false;this.retry.hidden=true;this.clearCompletion();this.term.reset();
      const result=await this.workbench.request(this.url(),{action:'open',id:this.id,cols:this.term.cols,rows:this.term.rows});if(!this.disposed){this.apply(result);this.schedule();}
    }catch(e){if(!this.disposed)this.status.textContent=BridgeI18n.t(e.message);}
    finally{this.restarting=false;this.schedule();}
  }
  dispose(){
    this.disposed=true;document.removeEventListener('visibilitychange',this.visibility);this.readController?.abort();clearTimeout(this.timer);clearTimeout(this.flushTimer);clearTimeout(this.resizeTimer);this.observer?.disconnect();this.term?.dispose();this.fallback?.dispose();
    if(!this.fallback)this.workbench.request(this.url(),{action:'close',id:this.id}).catch(()=>{});
    try{sessionStorage.removeItem(this.key);}catch{}
  }
}
