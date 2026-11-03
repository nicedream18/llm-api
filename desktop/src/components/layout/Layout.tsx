import { ReactNode } from "react";
import { Sidebar } from "./Sidebar";

export function Layout({
  children,
  hasUpdate,
  onCheckUpdate,
}: {
  children: ReactNode;
  hasUpdate: boolean;
  onCheckUpdate: () => void;
}) {
  return (
    <div className="flex h-screen overflow-hidden bg-transparent text-foreground">
      <Sidebar hasUpdate={hasUpdate} onCheckUpdate={onCheckUpdate} />
      <main className="flex-1 overflow-hidden">
        <div className="h-full overflow-auto bg-[linear-gradient(180deg,rgba(255,255,255,0.02),transparent)]">
          <div className="border-b border-blue-100 bg-blue-50/70 px-6 py-2 text-xs text-slate-500">Python 桌面版 · 界面源自 Rust 项目。缓存 Token、首字耗时与实时会话事件尚未计量；部分 Rust 专用操作尚未接入。</div>
          {children}
        </div>
      </main>
    </div>
  );
}
