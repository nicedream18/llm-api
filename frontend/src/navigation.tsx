import { Component, type ReactNode, useEffect, useState } from "react";

export function usePage(allowed: string[]): string {
  const read = () => window.location.hash ? window.location.hash.slice(2).split("?")[0]! : "dashboard";
  const [page, setPage] = useState(read);
  useEffect(() => { const change = () => setPage(read()); window.addEventListener("hashchange", change); return () => window.removeEventListener("hashchange", change); }, []);
  return allowed.includes(page) ? page : "not-found";
}

export class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <section className="panel" role="alert"><h2>页面暂时无法显示</h2><p>请重试或从导航进入其他页面。</p><button onClick={() => this.setState({ failed: false })}>重新加载页面内容</button><a href="#/dashboard">返回仪表盘</a></section> : this.props.children;
  }
}
