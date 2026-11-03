import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { adaptChannel, invokePython, request } from './python-api';

function storage() {
  const values = new Map<string, string>();
  return { getItem: (key: string) => values.get(key) || null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) };
}
const reply = (data: unknown, status = 200) => new Response(JSON.stringify({ code: status === 200 ? '0000' : '0008', info: status === 200 ? '成功' : '未授权访问', data }), { status });
beforeEach(() => {
  vi.stubGlobal('sessionStorage', storage());
  vi.stubGlobal('localStorage', storage());
  vi.stubGlobal('window', new EventTarget());
});
afterEach(() => vi.unstubAllGlobals());

it('uses Python envelopes, cookies, query encoding and optional admin token', async () => {
  sessionStorage.setItem('waliapi.desktop.admin-token', 'test-token');
  const fetchMock = vi.fn().mockResolvedValue(reply({ ok: true }));
  vi.stubGlobal('fetch', fetchMock);
  expect(await request('/logs', 'GET', undefined, { keyword: 'a&b', limit: 5 })).toEqual({ ok: true });
  expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/logs?keyword=a%26b&limit=5');
  expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: 'include', headers: { authorization: 'Bearer test-token' } });
});
it('reports session expiration and rejects business errors', async () => {
  const expired = vi.fn();
  window.addEventListener('waliapi:unauthorized', expired);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(null, 401)));
  await expect(request('/auth/session')).rejects.toThrow('未授权');
  expect(expired).toHaveBeenCalledOnce();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: '0009', info: '拒绝写入' }))));
  await expect(request('/channels')).rejects.toThrow('拒绝写入');
});
it('hydrates channel partial updates and preserves backend configuration', async () => {
  const current = { id: 'c1', type: 'openai', name: 'old', models: ['model-a'], api_key: '****', priority: 7, config: { proxy: { mode: 'direct' }, other: true } };
  const fetchMock = vi.fn().mockResolvedValueOnce(reply(current)).mockResolvedValueOnce(reply(true)).mockResolvedValueOnce(reply({ ...current, name: 'new' }));
  vi.stubGlobal('fetch', fetchMock);
  await invokePython('update_channel', { input: { id: 'c1', name: 'new' } });
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ name: 'new', priority: 7, models: ['model-a'], api_key: '****', config: current.config });
});
it('preserves key quota and expiry on partial updates', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(reply({ id: 'k1', name: 'key', quota_limit: 200, expires_at: '2027-01-01' })).mockResolvedValueOnce(reply(true));
  vi.stubGlobal('fetch', fetchMock);
  await invokePython('update_api_key', { input: { id: 'k1', status: 0 } });
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ quota_limit: 200, expires_at: '2027-01-01', status: 0 });
});
it('maps source channel protocols without dropping their identity', () => {
  expect(adaptChannel({ type: 'claude', id: 'c1' })).toMatchObject({ id: 'c1', protocol: 'anthropic', native_endpoints: ['messages'], models: [], config: {} });
});
it('rejects unsupported writes rather than silently saving', async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  await expect(invokePython('create_api_key', { input: { denied_models: ['model-a'] } })).rejects.toThrow('尚未接入');
  await expect(invokePython('create_channel', { input: { request_headers: [{ name: 'x-test' }] } })).rejects.toThrow('尚未接入');
  await expect(invokePython('get_app_configs')).rejects.toThrow('尚未接入');
  expect(fetchMock).not.toHaveBeenCalled();
});
it('uses daily and flow contracts with real request and failure counts', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(reply([{ day: '2026-11-03', total_tokens: 90, request_count: 2 }])).mockResolvedValueOnce(reply([{ channel_id: 'c1', request_count: 2, fail_count: 1 }]));
  vi.stubGlobal('fetch', fetchMock);
  expect(await invokePython('get_daily_token_stats', { days: 385 })).toEqual([{ day: '2026-11-03', total_tokens: 90, request_count: 2 }]);
  expect(await invokePython('get_route_flow')).toEqual([{ channel_id: 'c1', request_count: 2, fail_count: 1 }]);
  expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/desktop/daily-tokens?days=385');
});
