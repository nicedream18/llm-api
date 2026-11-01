const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const context = vm.createContext({});
vm.runInContext(fs.readFileSync('app/static/js/helpers.js', 'utf8'), context);
vm.runInContext(fs.readFileSync('app/static/js/pages/wiki.js', 'utf8'), context);

test('Wiki renderer handles a long Markdown document within the regression budget', () => {
  const document = Array.from({ length: 5000 }, (_, index) =>
    index % 100 === 0 ? `## Section ${index}` : `A searchable paragraph ${index} with **formatting**.`
  ).join('\n');
  const started = process.hrtime.bigint();
  const rendered = context.renderWikiMarkdown(document);
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
  assert.ok(rendered.includes('<h2>Section 4900</h2>'));
  assert.ok(rendered.includes('<strong>formatting</strong>'));
  assert.ok(elapsedMs < 2000, `long document render took ${elapsedMs.toFixed(1)}ms`);
});
