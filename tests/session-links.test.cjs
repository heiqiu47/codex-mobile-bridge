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
