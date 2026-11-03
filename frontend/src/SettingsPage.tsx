import { useEffect, useMemo, useState } from "react";
import { AdministrationPanel } from "./AdministrationPanel";
import { del, get, post } from "./api";
import { EntityPicker, type EntityOption } from "./EntityPicker";
import type { AccessGrant, ClientConfig, KnowledgeBase, PromptTemplate, SoftwareTool, WikiProject } from "./types";

type AccessKey = { id: string; name: string; status: number; key?: string | null };
type McpTool = { name: string; description?: string };
type GrantResources = {
  keys: AccessKey[];
  tools: McpTool[];
  knowledgeBases: KnowledgeBase[];
  projects: WikiProject[];
  softwareTools: SoftwareTool[];
};

const emptyResources: GrantResources = { keys: [], tools: [], knowledgeBases: [], projects: [], softwareTools: [] };
const resourceNames: Record<string, string> = { mcp_tool: "MCP 工具", kb: "知识库", wiki: "Wiki 项目", software: "Software 工具" };

export function SettingsPage({ onError }: { onError: (message: string) => void }) {
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [configs, setConfigs] = useState<ClientConfig[]>([]);
  const [grants, setGrants] = useState<AccessGrant[]>([]);
  const [resources, setResources] = useState<GrantResources>(emptyResources);
  const [principalType, setPrincipalType] = useState("api_key");
  const [principalId, setPrincipalId] = useState("");
  const [resourceType, setResourceType] = useState("mcp_tool");
  const [resourceId, setResourceId] = useState("*");
  const [grantAction, setGrantAction] = useState("execute");
  const [target, setTarget] = useState("codex");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const [promptRows, configRows, grantRows, keys, mcp, knowledgeBases, projects, softwareTools] = await Promise.all([
        get<PromptTemplate[]>("/api/v1/platform/prompts"),
        get<ClientConfig[]>("/api/v1/platform/config"),
        get<AccessGrant[]>("/api/v1/access/grants"),
        get<AccessKey[]>("/api/v1/api-keys"),
        get<{ tools: McpTool[] }>("/api/v1/mcp/tools"),
        get<KnowledgeBase[]>("/api/v1/kb"),
        get<WikiProject[]>("/api/v1/wiki/projects"),
        get<SoftwareTool[]>("/api/v1/software/tools"),
      ]);
      setPrompts(promptRows); setConfigs(configRows); setGrants(grantRows);
      setResources({ keys, tools: mcp.tools || [], knowledgeBases, projects, softwareTools });
    } catch (error) {
      onError(error instanceof Error ? error.message : "无法加载系统设置");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);

  const apiKeyOptions: EntityOption[] = resources.keys.map(key => ({ id: key.id, label: key.name, detail: key.status ? "已启用" : "已停用" }));
  const resourceOptions: EntityOption[] = useMemo(() => {
    const all: EntityOption[] = [{ id: "*", label: "所有资源", detail: "对该资源类型授予通配权限" }];
    if (resourceType === "mcp_tool") return [...all, ...resources.tools.map(tool => ({ id: tool.name, label: tool.name, detail: tool.description }))];
    if (resourceType === "kb") return [...all, ...resources.knowledgeBases.map(item => ({ id: item.id, label: item.name, detail: `${item.doc_count} 个文档` }))];
    if (resourceType === "wiki") return [...all, ...resources.projects.map(item => ({ id: item.id, label: item.name, detail: item.description }))];
    return [...all, ...resources.softwareTools.map(tool => ({ id: tool.id, label: tool.name, detail: tool.description }))];
  }, [resourceType, resources]);
  const resourceLabels = useMemo(() => {
    const labels = new Map<string, string>();
    resources.tools.forEach(item => labels.set(`mcp_tool:${item.name}`, item.name));
    resources.knowledgeBases.forEach(item => labels.set(`kb:${item.id}`, item.name));
    resources.projects.forEach(item => labels.set(`wiki:${item.id}`, item.name));
    resources.softwareTools.forEach(item => labels.set(`software:${item.id}`, item.name));
    return labels;
  }, [resources]);
  const keyNames = useMemo(() => new Map(resources.keys.map(key => [key.id, key.name])), [resources.keys]);
  const duplicateGrant = grants.some(grant => grant.principal_type === principalType && grant.principal_id === principalId
    && grant.resource_type === resourceType && grant.resource_id === resourceId && grant.action === grantAction);

  const run = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setMessage("");
    try { await action(); }
    catch (error) { onError(error instanceof Error ? error.message : "操作失败"); }
    finally { setBusy(false); }
  };
  const preview = () => run(async () => {
    const result = await post<{ path: string }>("/api/v1/platform/config/preview", { target, values: {} });
    setMessage(`配置预览：${result.path}`);
  });
  const clearCache = () => run(async () => {
    await del("/api/v1/platform/cache");
    setMessage("语义缓存已清理");
  });
  const removeConfig = (config: ClientConfig) => run(async () => {
    await del(`/api/v1/platform/config/${encodeURIComponent(config.target)}`);
    await load(); setMessage("客户端配置已删除");
  });
  const createGrant = () => run(async () => {
    await post<AccessGrant>("/api/v1/access/grants", {
      principal_type: principalType, principal_id: principalId.trim(), resource_type: resourceType,
      resource_id: resourceId, action: grantAction,
    });
    setPrincipalId(""); setResourceId("*");
    await load(); setMessage("授权已添加");
  });
  const removeGrant = (grant: AccessGrant) => {
    if (!window.confirm("删除这条授权？")) return;
    void run(async () => { await del(`/api/v1/access/grants/${encodeURIComponent(grant.id)}`); await load(); setMessage("授权已删除"); });
  };

  return <section className="settings-page">
    <AdministrationPanel onError={onError} />
    <div className="panel">
      <div className="table-heading"><div><h2>平台设置</h2><p>生成客户端配置、管理提示模板和资源授权。</p></div></div>
      <div className="settings-config-toolbar">
        <label>目标客户端<select value={target} onChange={event => setTarget(event.target.value)}><option value="codex">Codex CLI</option><option value="claude">Claude Code</option><option value="gemini">Gemini CLI</option></select></label>
        <button className="primary" disabled={busy} onClick={() => void preview()}>预览配置</button>
        <button className="secondary" disabled={busy} onClick={() => void clearCache()}>清理语义缓存</button>
      </div>
      {message && <p className="success" role="status">{message}</p>}
      {loading && <p className="muted" role="status">正在加载系统设置…</p>}
      <h3>已生成客户端配置</h3>
      <div className="card-list">{configs.map(config => <article className="subcard" key={config.target}><strong>{config.target}</strong><span>{config.path}</span><small>{config.size} bytes</small><button className="secondary" disabled={busy} onClick={() => void removeConfig(config)}>删除</button></article>)}</div>
      {!loading && configs.length === 0 && <p className="muted">暂无客户端配置。</p>}
      <h3>Prompt 模板</h3>
      <div className="card-list">{prompts.map(prompt => <article className="subcard" key={prompt.id}><strong>{prompt.name}</strong><span>{prompt.description || prompt.template}</span><small>{prompt.enabled ? "已启用" : "已停用"}</small></article>)}</div>
      {!loading && prompts.length === 0 && <p className="muted">暂无 Prompt 模板。</p>}
      <div className="settings-grants-heading"><div><h3>访问授权</h3><p className="muted">为 API Key 或 MCP 主体设置对知识库、Wiki、Software 和 MCP 工具的权限。未配置的访问默认拒绝。</p></div></div>
      <form className="grant-form settings-grant-form" aria-busy={loading} onSubmit={event => { event.preventDefault(); void createGrant(); }}>
        <label className="field-label">主体类型<select disabled={loading} value={principalType} onChange={event => { setPrincipalType(event.target.value); setPrincipalId(""); }}><option value="api_key">访问密钥</option><option value="mcp">MCP 主体</option></select></label>
        {principalType === "api_key" ? <EntityPicker label="访问密钥" value={principalId ? [principalId] : []} options={apiKeyOptions} onChange={value => setPrincipalId(value[0] || "")} multiple={false} disabled={loading} placeholder="搜索密钥名称" helperText="选择名称即可，系统会使用对应的内部标识。" />
          : <label className="field-label">MCP 主体标识<input disabled={loading} value={principalId} maxLength={64} onChange={event => setPrincipalId(event.target.value)} placeholder="调用方主体标识" /><small className="field-help">填写 MCP 调用上下文中的主体标识。</small></label>}
        <label className="field-label">资源类型<select disabled={loading} value={resourceType} onChange={event => { setResourceType(event.target.value); setResourceId("*"); }}><option value="mcp_tool">MCP 工具</option><option value="kb">知识库</option><option value="wiki">Wiki 项目</option><option value="software">Software 工具</option></select></label>
        <EntityPicker label={resourceNames[resourceType]} value={[resourceId]} options={resourceOptions} onChange={value => setResourceId(value[0] || "*")} multiple={false} disabled={loading} placeholder={`搜索${resourceNames[resourceType]}`} helperText="选择名称或“所有资源”。" />
        <label className="field-label">允许操作<select value={grantAction} onChange={event => setGrantAction(event.target.value)}><option value="execute">执行</option><option value="read">读取</option><option value="write">写入</option></select></label>
        <button className="primary grant-submit" disabled={loading || busy || !principalId.trim() || duplicateGrant}>{busy ? "处理中…" : duplicateGrant ? "授权已存在" : "添加授权"}</button>
      </form>
      <div className="table-wrap"><table><thead><tr><th>主体</th><th>资源</th><th>操作</th><th>创建时间</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{grants.map(grant => <tr key={grant.id}>
        <td>{grant.principal_type === "api_key" ? `访问密钥：${keyNames.get(grant.principal_id) || "不可用密钥"}` : `MCP：${grant.principal_id}`}</td>
        <td>{resourceNames[grant.resource_type] || grant.resource_type}：{grant.resource_id === "*" ? "所有资源" : resourceLabels.get(`${grant.resource_type}:${grant.resource_id}`) || "不可用资源"}</td>
        <td>{grant.action}</td><td>{new Date(grant.created_at).toLocaleString()}</td>
        <td><button className="danger" disabled={busy} onClick={() => removeGrant(grant)}>删除</button></td>
      </tr>)}</tbody></table>{!loading && grants.length === 0 && <p className="muted">暂无授权。</p>}</div>
    </div>
  </section>;
}
