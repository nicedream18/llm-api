type Bridge = {
  select_files(directory: boolean, multiple: boolean): Promise<string | string[] | null>;
  read_file(path: string): Promise<{ name: string; base64: string }>;
  save_file(content: string, name: string): Promise<boolean>;
  open_external(url: string): Promise<void>;
};
declare global { interface Window { pywebview?: { api: Bridge } } }
export async function nativeBridge(): Promise<Bridge> {
  if (window.pywebview?.api) return window.pywebview.api;
  return new Promise((resolve, reject) => {
    const ready = () => { clearTimeout(timer); window.removeEventListener('pywebviewready', ready);
      if (window.pywebview?.api) resolve(window.pywebview.api); else reject(new Error('原生桌面桥未就绪')); };
    const timer = setTimeout(() => { window.removeEventListener('pywebviewready', ready); reject(new Error('请使用 start-desktop.command 启动桌面软件')); }, 5000);
    window.addEventListener('pywebviewready', ready);
  });
}
export async function open(options: { directory?: boolean; multiple?: boolean; filters?: unknown[]; title?: string } = {}): Promise<string | string[] | null> {
  return (await nativeBridge()).select_files(Boolean(options.directory), Boolean(options.multiple));
}
export async function save(_options: { defaultPath?: string; filters?: unknown[] } = {}): Promise<string | null> {
  throw new Error('此导出格式尚未接入 Python 桌面版');
}
export async function openUrl(url: string): Promise<void> {
  if (!(url.startsWith('https://') || url.startsWith('http://'))) throw new Error('只支持 HTTP(S) 链接');
  if (window.pywebview?.api) await window.pywebview.api.open_external(url);
  else window.open(url, '_blank', 'noopener,noreferrer');
}
