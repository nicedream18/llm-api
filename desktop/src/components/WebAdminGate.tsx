import { type FormEvent, type ReactNode, useEffect, useState } from 'react';
import { Loader2, Server } from 'lucide-react';
import { request } from '../lib/python-api';
import { WEB_UNAUTHORIZED_EVENT, setWebAdminToken } from '../lib/runtime';

export function WebAdminGate({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [checking, setChecking] = useState(true);
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    const unauthorized = () => { setWebAdminToken(''); setAuthenticated(false); setError('登录已失效，请重新登录'); };
    window.addEventListener(WEB_UNAUTHORIZED_EVENT, unauthorized);
    request<{authenticated: boolean}>('/auth/session').then(value => { if (active) setAuthenticated(value.authenticated); })
      .catch(() => {}).finally(() => { if (active) setChecking(false); });
    return () => { active = false; window.removeEventListener(WEB_UNAUTHORIZED_EVENT, unauthorized); };
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); setChecking(true); setError('');
    try { await request('/auth/login', 'POST', { username, password }); setPassword(''); setAuthenticated(true); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '登录失败'); }
    finally { setChecking(false); }
  }
  if (authenticated) return children;
  return <main className="flex min-h-screen items-center justify-center bg-[#eef3f8] p-6">
    <section className="surface w-full max-w-md rounded-[28px] p-8">
      <div className="mb-7 flex items-center gap-4"><span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-600 text-white"><Server size={23} /></span>
        <div><h1 className="text-2xl font-bold text-slate-900">WaLiAPI Desktop</h1><p className="mt-1 text-sm text-slate-500">Python 桌面版 · 登录本地管理服务</p></div></div>
      <form onSubmit={submit} className="space-y-4">
        <label className="block text-sm text-slate-700">用户名<input autoFocus autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} className="mt-2 h-12 w-full rounded-2xl border border-slate-200 bg-white px-4" required /></label>
        <label className="block text-sm text-slate-700">密码<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} className="mt-2 h-12 w-full rounded-2xl border border-slate-200 bg-white px-4" required /></label>
        {error && <p role="alert" className="rounded-xl bg-rose-50 p-3 text-sm text-rose-600">{error}</p>}
        <button disabled={checking} className="action-primary flex h-12 w-full items-center justify-center gap-2 rounded-2xl">{checking && <Loader2 size={17} className="animate-spin" />}{checking ? '正在连接' : '进入桌面控制台'}</button>
      </form><p className="mt-5 text-xs leading-5 text-slate-400">使用 Python 项目原有管理员账号；窗口关闭后清除本次登录状态。</p>
    </section></main>;
}
