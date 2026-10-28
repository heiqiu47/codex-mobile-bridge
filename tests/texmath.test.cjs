'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const markdownit = require('../web/vendor/markdown-it.min.js');
const texmath = require('../web/vendor/texmath.js');
const katex = require('../web/vendor/katex/katex.min.js');

const markdown = markdownit({html:false, linkify:true, breaks:true})
  .use(texmath, {engine:katex, delimiters:['brackets','dollars']});
const expression = String.raw`S=\{x>0:x^2\le b\},\qquad a=\sup S.`;

for (const [open, close] of [['\\[', '\\]'], ['$$', '$$']]) {
  test(`${open} display math interrupts a paragraph without a blank line`, () => {
    const source = `要证明存在正数，先令\n${open}\n${expression}\n${close}\n后续正文`;
    const tokens = markdown.parse(source, {});
    const math = tokens.filter(token => token.type === 'math_block');
    assert.equal(math.length, 1);
    assert.equal(math[0].content.trim(), expression);
    assert.deepEqual(tokens.filter(token => token.type === 'inline').map(token => token.content),
      ['要证明存在正数，先令', '后续正文']);
    assert.match(markdown.render(source), /class="katex-display"/);
  });
}

test('code and incomplete brackets do not interrupt paragraphs as display math', () => {
  for (const source of ['正文\n\\[\nx^2', '正文\n`\\[x^2\\]`', '正文\n```tex\n\\[x^2\\]\n```']) {
    assert.equal(markdown.parse(source, {}).filter(token => token.type.startsWith('math_')).length, 0);
  }
});
