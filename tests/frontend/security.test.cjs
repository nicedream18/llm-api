const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/static/js/pages/security.js', 'utf8');

test('legacy security switches persist actual state and preserve it after failure', async () => {
  const calls = []; const messages = [];
  const state = { data: { security: { settings: { enabled: true, redact_secrets: false } } } };
  let succeed = true;
  const context = vm.createContext({ state, toast: (...args) => messages.push(args), updatePage: () => {}, api: async (path, init) => {
    calls.push([path, init]); return succeed ? { code: '0000', data: { enabled: true, redact_secrets: true } } : { code: 'ERR', info: 'failed' };
  } });
  vm.runInContext(source, context);
  await context.toggleSecPolicy('mask');
  assert.equal(calls[0][0], '/security/settings');
  assert.deepEqual(JSON.parse(calls[0][1].body), { redact_secrets: true });
  assert.equal(state.data.security.settings.redact_secrets, true);
  succeed = false; await context.toggleSecPolicy('audit');
  assert.equal(state.data.security.settings.enabled, true);
  assert.equal(messages.at(-1)[0], 'failed');
});

test('legacy security loading requires settings and reports incomplete loads', async () => {
  const state = { data: { security: {} } }; let updated = 0; const messages = [];
  const context = vm.createContext({ state, toast: (...args) => messages.push(args), updatePage: () => updated++, api: async path => path.endsWith('/settings') ? { code: 'ERR' } : { code: '0000', data: [] } });
  vm.runInContext(source, context); await context.loadSecurity();
  assert.equal(updated, 0); assert.equal(messages.length, 1);
});
