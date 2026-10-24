'use strict';
// Production image callback + Workbench DOM on synthetic image bytes only.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),out=path.join(root,'.tmp/v215-chat-feedback/image-workbench-check');fs.mkdirSync(out,{recursive:true});app.setPath('userData',path.join(out,'electron-data'));
const read=file=>fs.readFileSync(path.join(root,file),'utf8'),assets=require('../web/assets.json');
const style=['/style.css','/presentation.css','/workbench.css','/desktop-sessions.css'].flatMap(url=>assets[url]).map(file=>read('web/'+file)).join('\n');
const html='<!doctype html><html lang="zh"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+style+'</style><body></body></html>';
let writes=0;const server=http.createServer((req,res)=>{if(req.method!=='GET'){writes++;res.writeHead(405);return res.end();}if(req.url.startsWith('/api/')){res.writeHead(200,{'Content-Type':'image/png'});return res.end(fs.readFileSync(path.join(root,'web/icon.png')));}res.writeHead(200,{'Content-Type':'text/html'});res.end(html);});
app.whenReady().then(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const window=new BrowserWindow({width:390,height:844,show:false});const errors=[];window.webContents.on('console-message',event=>{if(event.level==='error')errors.push(event.message);});window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 await window.loadURL('http://127.0.0.1:'+server.address().port);const run=source=>window.webContents.executeJavaScript(source);
 for(const file of ['web/shared/i18n.js','web/layouts/viewport.js','web/features/chat/composer-quotes.js','web/features/chat/attachments.js','web/features/workspace/workbench.js','web/shared/image-viewer.js','tests/browser/image-composer.browser.js'])await run(read(file));
 const source=read('web/shell/app.js'),start=source.indexOf('function imageComposerTarget(){'),end=source.indexOf('function saveDraft(){',start);assert.ok(start>0&&end>start);const callback=source.slice(start,end),checks=[];
 for(const [width,height] of [[390,844],[1280,900]]){
  window.setSize(width,height);await run("document.querySelector('[data-image-composer-fixture]')?.remove()");
  const results=await run('runImageComposerWorkbenchTests('+JSON.stringify(callback)+',true)');checks.push({width,passed:results.length,results});
  fs.writeFileSync(path.join(out,'attachments-'+width+'.png'),(await window.webContents.capturePage()).toPNG());
 }
 assert.equal(writes,0);assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({checks,writes,errors},null,2));console.log(JSON.stringify({checks,writes,errors}));server.close();app.exit(0);
}).catch(error=>{console.error(error);server.close();app.exit(1);});
