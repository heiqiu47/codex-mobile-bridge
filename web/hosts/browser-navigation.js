'use strict';
// Browser history owns only list/detail navigation, never session or composer data.
class BrowserNavigation {
  constructor({read,restore,onError=()=>{}}){
    this.read=read;this.restore=restore;this.onError=onError;this.restoring=false;this.paused=false;this.revision=0;
    try{this.scope=sessionStorage.getItem('bridge-browser-navigation')||'';}catch{}
    if(!this.scope)this.rotateScope();
    window.addEventListener('popstate',event=>{
      if(!this.enabled())return;
      if(this.pendingBack){this.pendingBack=false;const route=this.pendingRoute;this.pendingRoute=null;if(route&&event.state?.bridgeNavigation===1&&!event.state.route){this.sync(route);return;}}
      if(event.state?.bridgeNavigation!==1){++this.revision;this.restoring=false;return;}
      if(event.state.scope!==this.scope){++this.revision;this.restoring=false;history.replaceState(this.entry(null),'',this.url(null));return;}
      const revision=++this.revision;this.restoring=true;
      const current=()=>revision===this.revision;
      Promise.resolve().then(()=>this.restore(event.state.route||null,current)).catch(error=>{if(current()){this.onError(error);history.replaceState(this.entry(this.read()),'',this.url(this.read()));}}).finally(()=>{if(current())this.restoring=false;});
    });
  }
  rotateScope(){this.scope=String(Date.now())+'-'+Math.random().toString(36).slice(2);try{sessionStorage.setItem('bridge-browser-navigation',this.scope);}catch{}}
  entry(route){return {bridgeNavigation:1,scope:this.scope,route};}
  invalidate(){++this.revision;this.restoring=false;this.pendingRoute=null;this.pendingBack=false;this.rotateScope();if(this.enabled())history.replaceState(this.entry(null),'',this.url(null));}
  enabled(){return !BridgeHost.isNativeApp()&&!BridgeHost.hasNativeLayout();}
  url(route){return location.pathname+location.search+(route&&route.provider==='codex'?'#'+route.id+'~'+encodeURIComponent(route.host):'');}
  sync(route=this.read()){
    if(!this.enabled())return false;
    if(this.restoring||this.paused)return true;
    if(this.pendingBack){this.pendingRoute=route;return true;}
    const current=history.state;
    if(route){
      route={provider:route.provider,id:route.id,host:route.host||'local'};
      if(current?.bridgeNavigation!==1||current.scope!==this.scope)history.replaceState(this.entry(null),'',this.url(null));
      const state=this.entry(route);
      if(history.state?.route)history.replaceState(state,'',this.url(route));
      else history.pushState(state,'',this.url(route));
    }else if(current?.bridgeNavigation===1&&current.route){
      this.pendingBack=true;history.back();
    }else history.replaceState(this.entry(null),'',this.url(null));
    return true;
  }
}
