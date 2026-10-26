'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function fixture(saved='18'){
  const properties={},storage={'bridge-file-font-size':saved,'bridge-terminal-font-size':'11'},listeners={};
  const context={document:{documentElement:{style:{setProperty:(key,value)=>properties[key]=value}}},localStorage:{getItem:key=>storage[key],setItem:(key,value)=>storage[key]=value},addEventListener:(key,fn)=>listeners[key]=fn,BridgeI18n:{t:x=>x}};
  vm.createContext(context);vm.runInContext(fs.readFileSync('web/features/workspace/workbench.js','utf8'),context);
  const font=vm.runInContext('FileFont',context);
  const wb={node:(tag,className)=>({tag,className,dataset:{},setAttribute(){},append(...nodes){this.children=nodes;}}),button:(text,onclick)=>({text,onclick})};
  return {font,wb,properties,storage,listeners};
}
test('file font synchronizes mounted and detached controls without terminal settings',()=>{
  const f=fixture(),a=f.font.control(f.wb),b=f.font.control(f.wb);
  assert.equal(a.value.textContent,'18px');a.increase.onclick();assert.equal(b.value.textContent,'19px');
  assert.equal(f.properties['--wb-file-font-size'],'19px');assert.equal(f.storage['bridge-file-font-size'],'19');assert.equal(f.storage['bridge-terminal-font-size'],'11');
  b.dispose();a.decrease.onclick();assert.equal(b.value.textContent,'19px');assert.equal(a.value.textContent,'18px');
  const c=f.font.control(f.wb);assert.equal(c.value.textContent,'18px');c.setZoom(true);assert.equal(c.value.textContent,'129%');assert.equal(f.properties['--wb-file-preview-zoom'],String(18/14));c.setZoom(false);
  f.listeners.storage({key:'bridge-file-font-size',newValue:'22'});assert.equal(c.value.textContent,'22px');
});
test('file font enforces bounds, reset and invalid persisted values',()=>{
  const f=fixture('999'),a=f.font.control(f.wb);assert.equal(f.font.size(),14);
  f.font.set(6);assert.equal(a.decrease.disabled,true);a.decrease.onclick();assert.equal(f.font.size(),6);
  f.font.set(24);assert.equal(a.increase.disabled,true);a.increase.onclick();assert.equal(f.font.size(),24);
  f.font.set('bad');assert.equal(f.font.size(),24);f.listeners.storage({key:'bridge-file-font-size',newValue:null});assert.equal(f.font.size(),14);
});
test('font CSS scopes text scaling to previews and leaves source rows on a shared grid',()=>{
  const css=fs.readFileSync('web/features/workspace/workbench.css','utf8');
  assert.match(css,/\.wb-preview-content \.wb-source,[^\n]*font-size:var\(--wb-file-font-size,14px\)/);
  assert.match(css,/\.wb-preview-content \.markdown-body\{font-size:var\(--wb-file-font-size,14px\)\}/);
  assert.match(css,/\.wb-source-body\{display:grid/);assert.match(css,/\.wb-source-number\{grid-column:1/);
});
