import { lazy, Suspense } from 'react';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/layout/Layout';
import { WebAdminGate } from './components/WebAdminGate';
import { ErrorBoundary } from './components/ErrorBoundary';

const DashboardPage = lazy(() => import('./pages/DashboardPage').then(m => ({ default: m.DashboardPage })));
const ChannelsPage = lazy(() => import('./pages/ChannelsPage').then(m => ({ default: m.ChannelsPage })));
const AuthChannelsPage = lazy(() => import('./pages/AuthChannelsPage').then(m => ({ default: m.AuthChannelsPage })));
const ApiKeysPage = lazy(() => import('./pages/ApiKeysPage').then(m => ({ default: m.ApiKeysPage })));
const LogsPage = lazy(() => import('./pages/LogsPage').then(m => ({ default: m.LogsPage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then(m => ({ default: m.SettingsPage })));
const UsagePage = lazy(() => import('./pages/UsagePage').then(m => ({ default: m.UsagePage })));
const KnowledgeBasePage = lazy(() => import('./pages/KnowledgeBasePage').then(m => ({ default: m.KnowledgeBasePage })));

export default function App() {
  return <ErrorBoundary><WebAdminGate><HashRouter>
    <Layout hasUpdate={false} onCheckUpdate={() => window.alert('Python 桌面版使用本项目更新，不安装上游 Rust 更新包。')}>
      <Suspense fallback={<div className="page-shell text-sm text-muted-foreground">加载中...</div>}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/usage" element={<UsagePage />} />
          <Route path="/channels" element={<ChannelsPage />} />
          <Route path="/channels/auth" element={<AuthChannelsPage />} />
          <Route path="/api-keys" element={<ApiKeysPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          {['/services', '/services/knowledge-base', '/services/mcp', '/services/wiki', '/services/skills', '/services/prompts', '/services/software'].map(path => <Route key={path} path={path} element={<KnowledgeBasePage key={path} />} />)}
          <Route path="/prompt-templates" element={<Navigate to="/services/prompts" replace />} />
          <Route path="/software" element={<Navigate to="/services/software" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Layout>
  </HashRouter></WebAdminGate></ErrorBoundary>;
}
