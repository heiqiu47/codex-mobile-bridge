'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context=vm.createContext({window:{}});
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../web/features/chat/message-actions.js'),'utf8'),context);
const text=context.window.BridgeSessionLinks.text,id='019d0000-1234-7123-8123-123456789abc';
test('copies native Codex thread identity locally and on SSH without launching',()=>{
 assert.equal(text({provider:'codex',id}),'codex://threads/'+id);
 assert.equal(text({provider:'codex',id,host:'remote ssh / 主机'}),'codex://threads/'+id+'?hostId=remote%20ssh%20%2F%20%E4%B8%BB%E6%9C%BA');
});
test('endpoint digests, WSL runtime, invalid threads and unknown providers do not claim deep links',()=>{
 for(const identity of [{provider:'codex',id,host:'wsl:abc'},{provider:'codex',id,runtime:'wsl'},{provider:'codex',id:'bridge-only'},{provider:'claude',id},{provider:'codex',id,host:null}])assert.equal(text(identity),null);
});
test('Harness copies the actual native Session ID verbatim',()=>assert.equal(text({provider:'deepseek',id:'session-native-123'}),'session-native-123'));

const read=file=>fs.readFileSync(require('node:path').join(__dirname,'../web',file),'utf8');
test('Codex title details and copy handlers use current identity and disable unsupported WSL links',()=>{
 const nodes=new Map(),copies=[],notices=[];
 const get=key=>{if(!nodes.has(key))nodes.set(key,{textContent:key,showModal(){this.open=true;}});return nodes.get(key);};
 const ui=vm.createContext({window:{BridgeSessionLinks:context.window.BridgeSessionLinks,BridgeClipboard:{copyWithFeedback:(getter,button)=>copies.push(getter())}},get,$:get,t:value=>value,toast:value=>notices.push(value)});
 vm.runInContext(`let currentId=${JSON.stringify(id)},currentHost='local';`,ui);
 vm.runInContext(read('features/settings/presentation.js').split('\n').find(line=>line.includes("get('chat-details-button').onclick=")),ui);
 const app=read('shell/app.js');vm.runInContext(app.slice(app.indexOf("$('copy-session-link').onclick=")),ui);
 get('chat-details-button').onclick();assert.equal(get('chat-details-dialog').open,true);assert.equal(get('copy-session-link').disabled,false);
 get('copy-session-link').onclick();assert.equal(copies[0],'codex://threads/'+id);
 vm.runInContext("currentHost='ssh:other';",ui);get('chat-details-button').onclick();get('copy-session-link').onclick();assert.match(copies[1],/hostId=ssh%3Aother$/);
 vm.runInContext("currentHost='wsl:internal';",ui);get('chat-details-button').onclick();assert.equal(get('copy-session-link').disabled,true);get('copy-session-link').onclick();assert.equal(copies.length,2);assert.equal(notices.length,1);
});
test('Harness title details copy the original native Session ID; unsupported providers omit action',()=>{
 const copies=[],dialogs=[];
 const ui=vm.createContext({window:{BridgeSessionLinks:context.window.BridgeSessionLinks,BridgeClipboard:{copyWithFeedback:getter=>copies.push(getter())}}});
 const source=read('features/clients/desktop-sessions.js'),method=source.slice(source.indexOf('  chatDetails(){'),source.indexOf('  async notifications(){'));
 const invoke=vm.runInContext('({'+method+'}).chatDetails',ui);
 const view={provider:'deepseek',sid:'session-original',state:{title:'Example'},dialog(){const dialog={children:[],append(...nodes){this.children.push(...nodes);},showModal(){this.open=true;}};dialogs.push(dialog);return dialog;},button(textContent,onclick){return {textContent,onclick,classList:{add(){}}};},node(){return {};}};
 invoke.call(view);assert.equal(dialogs[0].open,true);const copy=dialogs[0].children.find(node=>node.textContent==='复制 Session ID');assert.ok(copy);copy.onclick();assert.deepEqual(copies,['session-original']);
 view.sid='session-next';invoke.call(view);dialogs[1].children.find(node=>node.textContent==='复制 Session ID').onclick();assert.deepEqual(copies,['session-original','session-next']);
 view.provider='claude';invoke.call(view);assert.equal(dialogs[2].children.some(node=>node.textContent==='复制 Session ID'||node.textContent==='复制深度链接'),false);
});

test('Codex title copy sits next to execution host outside the message/rename group',()=>{
 const html=read('index.html'),dialog=html.slice(html.indexOf('<dialog id="chat-details-dialog"'),html.indexOf('</dialog>',html.indexOf('<dialog id="chat-details-dialog"')));
 assert.match(dialog,/<div class="chat-detail-execution"><span id="execution-host"><\/span><button id="copy-session-link" class="plain message-copy"/);
 assert.equal((dialog.match(/id="copy-session-link"/g)||[]).length,1);
 assert.ok(dialog.indexOf('id="rename-chat"')<dialog.indexOf('class="chat-detail-meta"'));
});
