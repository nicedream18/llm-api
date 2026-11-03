import { invokePython } from './python-api';

export const WEB_UNAUTHORIZED_EVENT = 'waliapi:unauthorized';
export interface RuntimeEvent<T> { payload: T }
// The native host is Python/WKWebView, not Tauri. Keep capability checks honest.
export function isTauriRuntime(): boolean { return false; }
export function getWebAdminToken(): string { return sessionStorage.getItem('waliapi.desktop.admin-token') || ''; }
export function setWebAdminToken(token: string): void {
  if (token.trim()) sessionStorage.setItem('waliapi.desktop.admin-token', token.trim());
  else sessionStorage.removeItem('waliapi.desktop.admin-token');
}
export async function invoke<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
  return invokePython(command, args) as Promise<T>;
}
// Python services expose polling APIs; never connect to the Rust event server.
export async function listen<T>(name: string, handler: (event: RuntimeEvent<T>) => void): Promise<() => void> {
  const listener = (event: Event) => handler({ payload: (event as CustomEvent<T>).detail });
  window.addEventListener(name, listener);
  return () => window.removeEventListener(name, listener);
}
export async function onFileDrop(_cb: (paths: string[]) => void): Promise<() => void> { return () => {}; }
export async function openExternalUrl(url: string): Promise<void> {
  const { openUrl } = await import('./native');
  await openUrl(url);
}
export async function writeClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return; }
  const input = document.createElement('textarea');
  input.value = text; document.body.appendChild(input); input.select();
  const copied = document.execCommand('copy'); input.remove();
  if (!copied) throw new Error('复制失败，请手动复制');
}
