import { afterEach, expect, it, vi } from 'vitest';
import { authApi, kbApi, logApi, wikiApi, securityApi } from './api';

afterEach(() => vi.unstubAllGlobals());
function mockApi(data: unknown) {
  vi.stubGlobal('sessionStorage', { getItem: () => '' });
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: '0000', data })));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
it('connects copied authApi command names and safe model and quota shapes', async () => {
  mockApi([{ id: 'a', name: 'Account', provider: 'codex', status: 'active', models: ['model-a'], quota: { used: 1 } }]);
  const accounts = await authApi.accountsList();
  expect(accounts[0]).toMatchObject({ label: 'Account', disabled: false, models: [{ id: 'model-a', status: 'available' }], quota: null });
});
it('connects provider names from the copied providersList contract', async () => {
  mockApi([{ provider: 'codex' }]);
  expect((await authApi.providersList())[0]).toMatchObject({ id: 'codex', displayName: 'codex', loginMethods: [] });
});
it('preserves the document extension so PDFs enter the PDF parser', async () => {
  const fetchMock = mockApi({ id: 'doc1' });
  await kbApi.uploadDocument({ kb_id: 'kb1', filename: 'example.PDF', content: 'JVBERg==' });
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ filename: 'example.PDF', file_type: 'pdf' });
});
it('normalizes Python risk levels and UTC timestamps before rendering source log badges', async () => {
  mockApi({ items: [{ id: 'l1', created_at: '2026-11-03 07:08:39', risk_level: 'Critical', security_action: 'Block', duration_ms: 5 }] });
  expect((await logApi.getAll())[0]).toMatchObject({ risk_level: 'critical', security_action: 'block', created_at: '2026-11-03T07:08:39Z', latency_ms: 5 });
});
it('rejects unsupported Wiki settings and whitelist semantics without saving', async () => {
  const fetchMock = mockApi({});
  await expect(wikiApi.createProject({ name: 'Wiki', ingest_model: 'model-a' })).rejects.toThrow('Wiki 高级配置');
  await expect(securityApi.createCustomRule({ rule_type: 'whitelist', category: 'domain', pattern: 'example', severity: 'low', action: 'allow' })).rejects.toThrow('安全规则白名单');
  expect(fetchMock).not.toHaveBeenCalled();
});
