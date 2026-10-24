'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.join(__dirname,'..');
const markdownit=require('../web/vendor/markdown-it.min.js');
function load(){
  const window={};
  vm.runInNewContext(fs.readFileSync(path.join(root,'web/shared/output-directives.js'),'utf8'),{window,URL});
  return window.BridgeOutputDirectives;
}
const directives=load();
test('complete directives consume escaped quotes and multiline source exactly',()=>{
  const source='::code-comment{title="Fix \\"quote\\"" body="first\nsecond" file="/src/a.js" start=12 end=14 priority=2}';
  const result=directives.read(source);
  assert.equal(result.attributes.title,'Fix "quote"');
  assert.equal(result.attributes.body,'first\nsecond');
  assert.equal(result.source,source);
  assert.equal(directives.read('::code-comment{title="T" body="'+'x'.repeat(65536)+'" file="/a"}'),null);
  assert.equal(directives.read(String.raw`::code-comment{title="T" body="B" file="C:\foo\bar.py"}`).attributes.file,String.raw`C:\foo\bar.py`);
  assert.equal(result.end,source.length);
  assert.equal(directives.read(':codex-followup[继续]{prompt="保留草稿"}').attributes.prompt,'保留草稿');
});
test('partial streams and malformed attributes stay inert',()=>{
  const complete='::code-comment{title="T" body="B" file="/a" start=1}';
  for(let index=0;index<complete.length;index++) assert.equal(directives.read(complete.slice(0,index)),null);
  for(const attrs of ['title="T" body="B" file="/a" end=2','title="T" body="B" file="/a" priority=4','title="T" body="B" file="/a" start=1000001','title="T" body="B" file="/a" start=3 end=2','title="T" body="B" file="/a" extra="x"','title="T" title="U" body="B" file="/a"']) assert.equal(directives.read('::code-comment{'+attrs+'}'),null);
});
test('markdown recognizes directives outside code only',()=>{
  const md=markdownit();directives.install(md);
  const source=':codex-followup[Continue]{prompt="Go"}';
  const children=text=>md.parse(text,{}).flatMap(token=>token.children||[]);
  const multiline=md.parse('::code-comment{title="T" body="first\n\nsecond" file="/a"}\n\nnext',{});
  assert.equal(multiline[0].type,'output_directive');
  assert.equal(multiline[0].meta.attributes.body,'first\n\nsecond');
  assert.equal(children(source).filter(token=>token.type==='output_directive').length,1);
  assert.equal(children('`'+source+'`').filter(token=>token.type==='output_directive').length,0);
  assert.equal(children('```\n'+source+'\n```').filter(token=>token.type==='output_directive').length,0);
  assert.equal(children('\\'+source).filter(token=>token.type==='output_directive').length,0);
});
test('PR mapping accepts only an exact HTTPS github pull request',()=>{
  assert.equal(directives.isReviewTarget('codex://review/path'),false);
  assert.equal(directives.isReviewTarget('codex://review.evil/?pr=x'),false);
  const url='codex://review?pr='+encodeURIComponent('https://github.com/org/repo/pull/46')+'&path=a.js&line=12';
  assert.equal(directives.reviewUrl(url),'https://github.com/org/repo/pull/46');
  for(const target of ['javascript:alert(1)','https://github.com.evil.test/org/repo/pull/46','https://user@github.com/org/repo/pull/46','https://github.com/org/repo/pull/46?x=1','file:///tmp/a']) assert.equal(directives.reviewUrl('codex://review?pr='+encodeURIComponent(target)),null);
});
test('cards use authorized file URLs and followups dispatch prompt without sending',()=>{
  class Node {
    constructor(tag){this.tag=tag;this.children=[];this.dataset={};}
    append(...items){this.children.push(...items);}
    dispatchEvent(event){this.event=event;return true;}
  }
  const window={BridgeClipboard:{copy:(getText)=>getText()}};
  vm.runInNewContext(fs.readFileSync(path.join(root,'web/shared/output-directives.js'),'utf8'),{window,URL,BridgeI18n:{t:value=>'EN '+value},document:{createElement:tag=>new Node(tag)},CustomEvent:class{constructor(type,options){this.type=type;Object.assign(this,options);}}});
  const api=window.BridgeOutputDirectives;
  const source='::code-comment{title="T" body="<script>literal</script>" file="/private/a" start=12 end=14 priority=2}';
  const item=api.read(source);
  const unknown=api.create(item,()=>null);
  assert.equal(api.create({...item,attributes:{...item.attributes,title:'[P2] Keep draft'}},()=>null).children[0].textContent,'[P2] Keep draft');
  assert.equal(api.create({...item,attributes:{...item.attributes,title:'[P1] Keep draft'}},()=>null).children[0].textContent,'[P2] [P1] Keep draft');
  assert.equal(unknown.children[2].tag,'span');
  assert.equal(unknown.children[3].textContent,'EN 复制批注源码');
  assert.equal(unknown.children[1].textContent,'<script>literal</script>');
  const known=api.create(item,()=>({url:'/api/authorized/file'}));
  assert.equal(known.children[2].href,'/api/authorized/file');
  assert.equal(known.children[2].dataset.sourceLine,'12');
  assert.equal(known.children[2].dataset.sourceEnd,'14');
  assert.equal(known.children[3].onclick({currentTarget:known.children[3]}),source);
  const follow=api.create(api.read(':codex-followup[Continue]{prompt="Keep draft"}'));
  assert.equal(follow.textContent,'Continue');
  follow.onclick({currentTarget:follow});
  assert.equal(follow.event.type,'bridge-compose-prompt');
  assert.equal(follow.event.detail.text,'Keep draft');
  assert.equal(follow.event.bubbles,true);
});
