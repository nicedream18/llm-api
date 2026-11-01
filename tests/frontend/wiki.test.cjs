const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const context=vm.createContext({});
vm.runInContext(fs.readFileSync('app/static/js/helpers.js','utf8'),context);
vm.runInContext(fs.readFileSync('app/static/js/pages/wiki.js','utf8'),context);

test('Wiki renderer escapes executable HTML and Markdown titles',()=>{
  const result=context.renderWikiMarkdown('# <img src=x onerror=alert(1)>\n**<script>bad()</script>**');
  assert.ok(result.includes('<h1>&lt;img'));
  assert.ok(result.includes('<strong>&lt;script&gt;'));
  assert.ok(!result.includes('<img'));
  assert.ok(!result.includes('<script>'));
});

test('Wiki renderer preserves fenced code and does not render code as headings',()=>{
  const fence=String.fromCharCode(96).repeat(3);
  const result=context.renderWikiMarkdown(fence+'js\n# code\n<img>\n'+fence);
  assert.ok(result.includes('<pre><code># code\n&lt;img&gt;</code></pre>'));
  assert.ok(!result.includes('<h1>'));
});

test('Wiki renderer keeps unsafe link targets as inert text',()=>{
  const result=context.renderWikiMarkdown('[click](javascript:alert(1))');
  assert.ok(!result.includes('<a '));
  assert.ok(result.includes('javascript:alert(1)'));
});
