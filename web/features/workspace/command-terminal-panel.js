'use strict';

const TerminalFont=(()=>{
  const key='bridge-terminal-font-size',sizes=[12,14,16,18,20,24],panels=new Set();
  const valid=value=>sizes.includes(Number(value))?Number(value):14;
  let size=14;try{size=valid(localStorage.getItem(key));}catch{}
  function update(value){size=valid(value);for(const panel of panels)panel.applyFontSize(size);}
  globalThis.addEventListener?.('storage',event=>{if(event.key===key)update(event.newValue);});
  return {
    size:()=>size,
    register(panel){panels.add(panel);panel.applyFontSize(size);},
    unregister:panel=>panels.delete(panel),
    set(value){if(!sizes.includes(Number(value)))return;update(value);try{localStorage.setItem(key,String(size));}catch{}},
    control(workbench){
      const label=workbench.node('label','wb-terminal-font');
      const title=workbench.node('span','','字号');
      label.setAttribute('data-i18n-title','所有终端字号');label.title=BridgeI18n.t('所有终端字号');
      const select=workbench.node('select');select.setAttribute('data-i18n-aria-label','所有终端字号');select.setAttribute('aria-label',BridgeI18n.t('所有终端字号'));
      for(const value of sizes){const option=workbench.node('option','',value+'px');option.value=String(value);select.append(option);}
      select.value=String(size);select.onchange=()=>TerminalFont.set(select.value);label.append(title,select);
      return {label,select};
    },
  };
})();

class CommandTerminalPanel {
  constructor(workbench, session, tab) {
    Object.assign(this, {workbench, session, tab}); this.disposed=false; this.cursor=0; this.output='';
    this.visibility=()=>{clearTimeout(this.timer);if(document.hidden)this.readController?.abort();else if(this.running){if(this.polling)this.resumeRead=true;else this.poll();}};
    document.addEventListener('visibilitychange',this.visibility);
    this.key='terminal:'+session.key;
    try { this.id=sessionStorage.getItem(this.key); } catch {}
    const n=(...args)=>workbench.node(...args), b=(...args)=>workbench.button(...args);
    const head=n('div','wb-terminal-head wb-terminal-font-head'); head.append(n('strong','',BridgeI18n.t('终端')));
    this.stop=b(BridgeI18n.t('停止'),()=>this.cancel());this.stop.disabled=true;
    const font=TerminalFont.control(workbench);this.fontSelect=font.select;
    head.append(b(BridgeI18n.t('清屏'),()=>{this.output='';this.screen.textContent='';}),font.label,this.stop);
    this.location=n('p','wb-terminal-location',BridgeI18n.t('正在读取项目…'));
    this.status=n('p','wb-status');this.status.setAttribute('role','status');
    this.screen=n('pre','wb-terminal-output');this.screen.tabIndex=0;this.screen.setAttribute('aria-label',BridgeI18n.t('命令输出'));
    this.form=n('form','wb-terminal-form');this.command=n('textarea');this.command.rows=1;this.command.placeholder=BridgeI18n.t('输入命令…');this.command.setAttribute('aria-label',BridgeI18n.t('终端命令'));this.command.spellcheck=false;
    this.command.setAttribute('autocapitalize','off');this.command.setAttribute('autocorrect','off');
    this.prompt=n('span','wb-terminal-prompt','$');this.prompt.setAttribute('aria-hidden','true');
    this.run=n('button','',BridgeI18n.t('运行 ↵'));this.run.type='submit';this.run.disabled=true;
    this.form.append(this.prompt,this.command,this.run);this.form.onsubmit=e=>{e.preventDefault();this.start();};
    this.command.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&!BridgeHost.hasNativeLayout()&&!BridgeLayout.isCompactViewport(innerWidth)){e.preventDefault();this.form.requestSubmit();}};
    const help=n('details','wb-terminal-help');help.append(n('summary','',BridgeI18n.t('命令终端 · 使用说明')),n('p','',BridgeI18n.t('每条命令从项目目录运行，沿用当前系统用户权限。Enter 运行，Shift+Enter 换行。支持脚本与构建输出，暂不支持 vim、密码输入等交互式程序。单次最多运行 30 分钟。')));
    tab.body.append(head,this.location,this.screen,this.form,this.status,help);
    TerminalFont.register(this);
    this.load();
  }
  applyFontSize(size){this.fontSelect.value=String(size);this.screen.style.fontSize=size+'px';this.command.style.fontSize=Math.max(16,size)+'px';this.prompt.style.fontSize=size+'px';}
  url(extra='') {return this.workbench.endpoint(this.session,'terminal')+extra;}
  async load() {
    try {
      const info=await this.workbench.request(this.url());if(this.disposed)return;
      this.location.textContent=(info.host==='local'?BridgeI18n.t('此电脑'):info.host)+' · '+info.cwd+' · '+info.shell;
      this.cwd=info.cwd;this.run.disabled=false;
      this.prompt.textContent=/cmd(?:\.exe)?$/i.test(info.shell)?'>':'$';
      if(this.id){this.running=true;this.run.disabled=true;await this.poll();}
    } catch(e){if(!this.disposed)this.status.textContent=e.message;}
  }
  remember(){try{if(this.id)sessionStorage.setItem(this.key,this.id);else sessionStorage.removeItem(this.key);}catch{}}
  async start() {
    const command=this.command.value.trim();if(!command||this.running||this.run.disabled)return;
    this.running=true;this.run.disabled=true;this.stop.disabled=true;this.id=uuid();this.remember();this.cursor=0;
    this.output='';this.commandText=this.prompt.textContent+' '+command+'\n';this.screen.textContent=this.commandText;this.status.textContent=BridgeI18n.t('正在启动…');
    try {
      const result=await this.workbench.request(this.url(),{action:'start',id:this.id,command});
      if(this.disposed)return;this.command.value='';this.apply(result);if(this.running)this.schedule();
    } catch(e){if(!this.disposed){this.status.textContent=e.message+BridgeI18n.t(' · 正在查询执行状态，不会重复执行。');this.schedule();}}
  }
  apply(result) {
    const follow=this.screen.scrollHeight-this.screen.clientHeight-this.screen.scrollTop<48;
    // Render output as text; strip terminal escape sequences, including OSC links.
    const text=result.output.replace(/\x1b\][^\x07]*(?:\x07|\x1b\\)/g,'').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'');
    this.output=((result.reset?'':this.output)+text).slice(-262144);this.cursor=result.cursor;
    this.screen.textContent=(this.commandText||'')+this.output;if(follow)this.screen.scrollTop=this.screen.scrollHeight;
    this.running=result.running;this.run.disabled=this.running;this.stop.disabled=!this.running;
    this.status.textContent=(result.running?BridgeI18n.t('运行中'):result.message||BridgeI18n.t('已结束 · 退出码 ')+result.exitCode)+(result.truncated?BridgeI18n.t(' · 仅保留最近输出'):'');
  }
  schedule(){clearTimeout(this.timer);if(!this.disposed&&!document.hidden&&!this.canceling)this.timer=setTimeout(()=>this.poll(),900);}
  async poll() {
    if(this.disposed||document.hidden||this.polling||!this.running||this.canceling)return;
    this.polling=true;clearTimeout(this.timer);const id=this.id,controller=this.readController=new AbortController();
    try {
      const result=await this.workbench.request(this.url('&id='+this.id+'&after='+this.cursor),undefined,controller.signal);
      if(this.disposed||controller.signal.aborted||this.id!==id)return;this.apply(result);
    } catch(e){
      if(this.disposed||controller.signal.aborted||this.id!==id)return;
      this.status.textContent=e.message;
      if(e.status===404){this.running=false;this.run.disabled=false;this.stop.disabled=true;this.id=null;this.remember();}
    } finally {
      this.polling=false;this.readController=null;
      const resume=this.resumeRead;this.resumeRead=false;
      if(resume&&!this.disposed&&!document.hidden&&!this.canceling)this.poll();else if(this.running)this.schedule();
    }
  }
  async cancel() {
    if(!this.id||this.canceling)return;this.canceling=true;this.stop.disabled=true;this.readController?.abort();clearTimeout(this.timer);
    try {const result=await this.workbench.request(this.url(),{action:'stop',id:this.id,after:this.cursor});if(!this.disposed)this.apply(result);}
    catch(e){if(!this.disposed){this.status.textContent=e.message;this.stop.disabled=false;}}
    finally{this.canceling=false;if(this.running)this.schedule();}
  }
  dispose(){this.disposed=true;TerminalFont.unregister(this);document.removeEventListener('visibilitychange',this.visibility);this.readController?.abort();clearTimeout(this.timer);}
}
