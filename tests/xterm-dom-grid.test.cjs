'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

// Execute the bundled row factory itself while replacing only its browser/services.
const source=fs.readFileSync(path.join(__dirname,'../web/vendor/xterm/xterm.js'),'utf8');
const marker='let f=t.DomRendererRowFactory=';
const start=source.indexOf(marker);
assert.ok(start>=0,'DOM row factory is bundled');
const end=source.indexOf(';function v(',start);
assert.ok(end>start,'DOM row factory boundary is present');
const factorySource=source.slice(start+marker.length,end);

function cell(chars,width=1,extra={}){
  return {chars,width,bg:0,fg:0,extended:{ext:0,underlineStyle:1},...extra,
    getWidth(){return this.width;},getChars(){return this.chars;},getCode(){return this.chars.codePointAt(0)||32;},
    isBold(){return !!this.bold;},isItalic(){return !!this.italic;},isDim(){return false;},
    isInvisible(){return !!this.invisible;},isUnderline(){return !!this.underline;},
    isUnderlineColorDefault(){return true;},isOverline(){return false;},isStrikethrough(){return false;},
    getFgColor(){return 0;},getBgColor(){return 0;},getFgColorMode(){return 0;},getBgColorMode(){return 0;},isInverse(){return false;}};
}
function fixture(cells,{customGlyphs=true,focused=false}={}){
  const spans=[];
  const document={createElement(tag){assert.equal(tag,'span');const span={style:{},attributes:{},textContent:'',className:'',
    setAttribute(name,value){this.attributes[name]=value;},getAttribute(name){return this.attributes[name]||null;}};spans.push(span);return span;}};
  const context=vm.createContext({
    a:{CellData:class {}},d:{JoinedCellData:class {}},o:{WHITESPACE_CELL_CHAR:' '},
    n:{INVERTED_DEFAULT_COLOR:256},_:{treatGlyphAsBackgroundColor:()=>false},
    c:{color:{multiplyOpacity:color=>color},channels:{toColor:()=>({rgba:0,css:'#000'})}},
    u:{AttributeData:{toColorRGB:()=>[0,0,0]}},v:(value,pad,length)=>value.padStart(length,pad)});
  vm.runInContext(`globalThis.Factory=${factorySource}`,context);
  const colors={foreground:{rgba:0,css:'#fff'},background:{rgba:0,css:'#000'},
    selectionBackgroundOpaque:{rgba:0x336699ff},selectionInactiveBackgroundOpaque:{rgba:0x336699ff},
    selectionForeground:null,ansi:[]};
  const factory=new context.Factory(document,{getJoinedCharacters:()=>[]},
    {rawOptions:{customGlyphs,minimumContrastRatio:1,drawBoldTextInBrightColors:false}},
    {isFocused:focused},{isCursorHidden:false,isCursorInitialized:true},
    {forEachDecorationAtCell(){}},{colors});
  const line={getNoBgTrimmedLength:()=>cells.length,loadCell(index,target){Object.assign(target,cells[index]);}};
  const render=(options={})=>factory.createRow(line,0,!!options.cursor,'block','outline',options.cursorColumn??0,false,
    9.375,{get:(chars,bold)=>chars==='中'?19.1:bold?10.2:9.6},options.underlineStart??-1,options.underlineEnd??-1);
  return {factory,render,spans};
}

test('merged runs and double-width glyphs use absolute fractional grid positions',()=>{
  const f=fixture([cell('a'),cell('b'),cell('中',2),cell('',0),cell('c'),cell('d')]);
  const row=f.render();
  assert.deepEqual(Array.from(row,span=>span.textContent),['ab','中','cd']);
  assert.deepEqual(Array.from(row,span=>[span.style.position,span.style.left,span.style.width]),[
    ['absolute','0px','18.75px'],['absolute','18.75px','18.75px'],['absolute','37.5px','18.75px']]);
  assert.ok(Math.abs(parseFloat(row[1].style.letterSpacing)+0.35)<1e-9);
});

test('cursor, style, underline and selection changes keep separate anchored spans',()=>{
  const f=fixture([cell('a'),cell('b'),cell('c',1,{bold:true}),cell('d',1,{extended:{ext:1,underlineStyle:1}}),cell('e')]);
  f.factory.handleSelectionChanged([4,0],[5,0],false);
  const row=f.render({cursor:true,cursorColumn:1,underlineStart:3,underlineEnd:3});
  assert.deepEqual(Array.from(row,span=>span.textContent),['a','b','c','d','e']);
  assert.deepEqual(Array.from(row,span=>span.style.left),['0px','9.375px','18.75px','28.125px','37.5px']);
  assert.ok(row[1].className.includes('xterm-cursor'));
  assert.ok(row[2].className.includes('xterm-bold'));
  assert.equal(row[3].style.textDecoration,'underline');
  assert.ok(row[4].className.includes('xterm-decoration-top'));
});

test('block glyphs retain text but paint per cell, without absorbing ordinary runs',()=>{
  const f=fixture([cell('a'),cell('▀'),cell('▐'),cell('▔'),cell('▕'),cell('b')]);
  const row=f.render();
  assert.deepEqual(Array.from(row,span=>span.textContent),['a','▀','▐','▔','▕','b']);
  assert.deepEqual(Array.from(row,span=>span.style.left),['0px','9.375px','18.75px','28.125px','37.5px','46.875px']);
  for(const span of row.slice(1,5)){
    assert.match(span.style.backgroundImage,/linear-gradient/);
    assert.equal(span.style.textIndent,'-9999px');
    assert.equal(span.style.width,'9.375px');
  }
  assert.equal(row[0].style.backgroundImage,undefined);
  const disabled=fixture([cell('▀')],{customGlyphs:false}).render()[0];
  assert.equal(disabled.style.backgroundImage,undefined);
  assert.equal(disabled.textContent,'▀');
  const invisible=fixture([cell('▀',1,{invisible:true})]).render()[0];
  assert.equal(invisible.style.backgroundImage,undefined);
});
