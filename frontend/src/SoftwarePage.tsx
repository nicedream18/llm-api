import { useEffect, useRef, useState } from "react";
import { del, get, post, put } from "./api";
import { DialogA11y } from "./DialogA11y";
import { useAction } from "./adminHooks";
import type { OpenApiPreview, SoftwareApproval, SoftwareCall, SoftwareDiscovery, SoftwareInstance, SoftwareTool } from "./types";

export function SoftwarePage({ onError }: { onError: (message: string) => void }) {
  const [view, setView] = useState(() => new URLSearchParams(window.location.hash.split("?")[1] || "").get("view") === "approvals" ? "approvals" : "tools");
  const [instanceOpen, setInstanceOpen] = useState(false);
  const [instances, setInstances] = useState<SoftwareInstance[]>([]);
  const [tools, setTools] = useState<SoftwareTool[]>([]);
  const [accessKeys, setAccessKeys] = useState<Array<{ id: string; name: string }>>([]);
  const [calls, setCalls] = useState<SoftwareCall[]>([]);
  const [approvals, setApprovals] = useState<SoftwareApproval[]>([]);
  const [specText, setSpecText] = useState("");
  const [instanceName, setInstanceName] = useState("");
  const [importName, setImportName] = useState("");
  const [instanceId, setInstanceId] = useState("");
  const [connectorType, setConnectorType] = useState("http");
  const [instanceConfig, setInstanceConfig] = useState("{}");
  const [editingInstance, setEditingInstance] = useState("");
  const [selectedTool, setSelectedTool] = useState("");
  const [invokeArguments, setInvokeArguments] = useState("{}");
  const [invokeResult, setInvokeResult] = useState("");
  const [approved, setApproved] = useState(false);
  const [discovery, setDiscovery] = useState<SoftwareDiscovery[]>([]);
  const [installPackage, setInstallPackage] = useState("");
  const [installManager, setInstallManager] = useState("pip");
  const [installMessage, setInstallMessage] = useState("");
  const [preview, setPreview] = useState<OpenApiPreview | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [acting, run] = useAction(onError);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const loadVersion = useRef(0);
  const load = async () => {
    const version = ++loadVersion.current;
    setLoading(true); setLoadError("");
    try { const [instanceRows, toolRows, callRows, approvalRows, keyRows] = await Promise.all([
    get<SoftwareInstance[]>("/api/v1/software/instances"),
    get<SoftwareTool[]>("/api/v1/software/tools"),
    get<SoftwareCall[]>("/api/v1/software/calls?limit=50"),
    get<SoftwareApproval[]>("/api/v1/software/approvals?status=pending&limit=50"),
    get<Array<{ id: string; name: string }>>("/api/v1/api-keys"),
  ]);
    if (version !== loadVersion.current) return;
    setInstances(instanceRows); setTools(toolRows); setCalls(callRows); setApprovals(approvalRows); setAccessKeys(keyRows);
    setInstanceId(current => instanceRows.some(row => row.id === current) ? current : instanceRows[0]?.id || "");
    setSelectedTool(current => toolRows.some(row => row.id === current) ? current : toolRows[0]?.id || "");
    } catch (error) { if (version === loadVersion.current) { const message = error instanceof Error ? error.message : "工具数据加载失败"; setLoadError(message); onError(message); } }
    finally { if (version === loadVersion.current) setLoading(false); }
  };
  useEffect(() => { void load(); return () => { loadVersion.current++; }; }, []);
  const toggle = (tool: SoftwareTool) => put<SoftwareTool>(`/api/v1/software/tools/${tool.id}/enabled?enabled=${tool.enabled ? "false" : "true"}`, {}).then(() => load()).catch((error: Error) => onError(error.message));
  const resetInstance = () => { setEditingInstance(""); setInstanceName(""); setConnectorType("http"); setInstanceConfig("{}"); setInstanceOpen(false); };
  const editInstance = (instance: SoftwareInstance) => { setEditingInstance(instance.id); setInstanceName(instance.name); setConnectorType(instance.connector_type); setInstanceConfig(JSON.stringify(instance.config || {}, null, 2)); setInstanceOpen(true); };
  const saveInstance = async () => {
    if (!instanceName.trim()) return;
    let parsed: unknown;
    try { parsed = JSON.parse(instanceConfig || "{}"); } catch { onError("实例配置必须是 JSON 对象"); return; }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) { onError("实例配置必须是 JSON 对象"); return; }
    const payload = { name: instanceName.trim(), connector_type: connectorType, config: parsed, enabled: instances.find(instance => instance.id === editingInstance)?.enabled ?? true };
    try {
      const saved = editingInstance
        ? await put<SoftwareInstance>(`/api/v1/software/instances/${encodeURIComponent(editingInstance)}`, payload)
        : await post<SoftwareInstance>("/api/v1/software/instances", payload);
      setInstanceId(saved.id); resetInstance(); await load();
    } catch (error) { onError(error instanceof Error ? error.message : "保存实例失败"); }
  };
  const removeInstance = async (instance: SoftwareInstance) => {
    if (!window.confirm(`删除实例“${instance.name}”及其工具？`)) return;
    try { await del(`/api/v1/software/instances/${encodeURIComponent(instance.id)}`); if (instanceId === instance.id) setInstanceId(""); await load(); }
    catch (error) { onError(error instanceof Error ? error.message : "删除实例失败"); }
  };
  const invoke = async () => {
    if (!selectedTool) return;
    let parsed: unknown;
    try { parsed = JSON.parse(invokeArguments || "{}"); } catch { onError("调用参数必须是 JSON 对象"); return; }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) { onError("调用参数必须是 JSON 对象"); return; }
    setInvokeResult("");
    try { const result = await post<unknown>(`/api/v1/software/tools/${encodeURIComponent(selectedTool)}/invoke`, { arguments: parsed, approved }); setInvokeResult(JSON.stringify(result, null, 2)); await load(); }
    catch (error) { onError(error instanceof Error ? error.message : "工具调用失败"); }
  };
  const decideApproval = async (approval: SoftwareApproval, approved: boolean) => {
    try { await post(`/api/v1/software/approvals/${encodeURIComponent(approval.id)}/decision`, { approved }); await load(); }
    catch (error) { onError(error instanceof Error ? error.message : "审批处理失败"); }
  };
  const scan = async () => { try { setDiscovery(await post<SoftwareDiscovery[]>("/api/v1/software/scan", {})); } catch (error) { onError(error instanceof Error ? error.message : "扫描本机工具失败"); } };
  const install = async () => { if (!installPackage.trim()) return; try { const result = await post<{ status: string; command: string[]; output?: string }>("/api/v1/software/install", { package: installPackage.trim(), manager: installManager, dry_run: true }); setInstallMessage(`${result.status === "planned" ? "已生成安装计划" : "已安装"}：${result.command.join(" ")}`); } catch (error) { onError(error instanceof Error ? error.message : "生成安装计划失败"); } };
  const parseSpec = () => {
    const value: unknown = JSON.parse(specText);
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("OpenAPI 规范必须是 JSON 对象");
    return value;
  };
  const inspect = async () => {
    setBusy(true); setMessage(""); setPreview(null);
    try {
      const result = await post<OpenApiPreview>("/api/v1/software/openapi/preview", { spec: parseSpec() });
      setPreview(result); setSelected(result.tools.map(tool => tool.name));
    } catch (error) { onError(error instanceof Error ? error.message : "无法预览 OpenAPI 规范"); }
    finally { setBusy(false); }
  };
  const importSelected = async () => {
    if (!preview || !importName.trim() || selected.length === 0) return;
    setBusy(true); setMessage("");
    try {
      const result = await post<{ instance: { name: string }; tools: SoftwareTool[] }>("/api/v1/software/openapi/import", { name: importName.trim(), spec: parseSpec(), tools: selected });
      setMessage(`已导入 ${result.tools.length} 个操作到“${result.instance.name}”。`);
      setPreview(null); setSelected([]); setImportName(""); void load();
    } catch (error) { onError(error instanceof Error ? error.message : "导入 OpenAPI 规范失败"); }
    finally { setBusy(false); }
  };
  return <section className="management-page software-page">
    <div className="management-toolbar"><div><h2>工具工作区</h2><p>集中管理连接器、工具调用与执行审批。</p></div><button className="primary" onClick={() => { resetInstance(); setView("instances"); setInstanceOpen(true); }}>＋ 添加连接器</button></div>
    <nav className="workspace-tabs" aria-label="工具集成功能">{[["tools", "已注册工具"], ["instances", "连接器"], ["discover", "本机发现"], ["openapi", "OpenAPI 导入"], ["approvals", "待审批"], ["calls", "调用记录"]].map(([id, label]) => <button className={view === id ? "active" : ""} key={id} aria-current={view === id ? "page" : undefined} onClick={() => setView(id)}>{label}{id === "approvals" && approvals.length > 0 && <span className="count-badge">{approvals.length}</span>}</button>)}</nav>
    {loading && <div className="empty-state" role="status"><span className="loading-mark" /><strong>正在加载工具工作区</strong></div>}
    {loadError && <div className="error inline-error" role="alert"><span>工具数据加载失败：{loadError}</span><button className="secondary" onClick={() => void load()}>重试</button></div>}
    {view === "discover" && <div className="panel"><div className="panel-head"><div><h2>本机工具发现</h2><p className="muted">仅检查固定的可执行文件白名单；安装默认只生成计划，不会修改本机。</p></div><button className="secondary" disabled={acting} onClick={() => void run(scan)}>扫描本机</button></div>{discovery.length > 0 && <div className="table-wrap"><table><thead><tr><th>工具</th><th>状态</th><th>路径</th><th>版本</th></tr></thead><tbody>{discovery.map(row => <tr key={row.name}><td>{row.name}</td><td className={row.installed ? "success" : "muted"}>{row.installed ? "已安装" : "未发现"}</td><td>{row.path || "—"}</td><td>{row.version || "—"}</td></tr>)}</tbody></table></div>}<div className="inline-form software-install-form"><input value={installPackage} maxLength={128} onChange={event => setInstallPackage(event.target.value)} aria-label="安装包名" placeholder="包名，例如：ruff" /><select aria-label="包管理器" value={installManager} onChange={event => setInstallManager(event.target.value)}><option value="pip">pip</option><option value="npm">npm</option><option value="winget">winget</option><option value="brew">brew</option><option value="apt">apt</option></select><button className="secondary" onClick={() => void run(install)} disabled={acting || !installPackage.trim()}>生成安装计划</button></div>{installMessage && <p className="success" role="status">{installMessage}</p>}</div>}
    {!loading && !loadError && view === "instances" && <div className="panel">
      <div className="panel-head"><div><h2>软件实例</h2><p className="muted">管理 CLI、HTTP、MCP 和 OpenAPI 连接器。凭据应通过部署配置注入。</p></div><button className="secondary" onClick={() => { resetInstance(); setInstanceOpen(true); }}>新建实例</button></div>
      <div className="card-list">{instances.map(instance => <article className={`subcard ${instance.id === instanceId ? "selected-card" : ""}`} key={instance.id}><div className="panel-head"><div><strong>{instance.name}</strong><span>{instance.connector_type} · {instance.enabled ? "已启用" : "已停用"}</span></div><div className="inline-form"><button className="secondary" onClick={() => { setInstanceId(instance.id); editInstance(instance); }}>编辑</button><button className="danger" disabled={acting} onClick={() => void run(() => removeInstance(instance))}>删除</button></div></div></article>)}</div>{instances.length === 0 && <p className="muted">暂无软件实例。</p>}
    </div>}
    {view === "openapi" && <div className="panel">
      <div className="panel-head"><div><h2>从 OpenAPI 创建工具</h2><p className="muted">粘贴 OpenAPI 3.0/3.1 JSON，先预览操作，再选择要导入的工具。</p></div></div>
      <label className="field-label">实例名称<input value={importName} maxLength={128} onChange={event => setImportName(event.target.value)} placeholder="例如：订单服务" /></label>
      <label className="field-label">OpenAPI JSON<textarea className="code-input" spellCheck={false} value={specText} onChange={event => setSpecText(event.target.value)} placeholder={'{\n  "openapi": "3.0.3",\n  "info": { "title": "Example", "version": "1.0.0" },\n  "servers": [{ "url": "https://api.example.com" }],\n  "paths": { ... }\n}'} /></label>
      <div className="inline-form"><button className="primary" onClick={inspect} disabled={busy || !specText.trim()}>{busy ? "处理中…" : "预览操作"}</button>{preview && <button className="secondary" onClick={() => { setPreview(null); setSelected([]); }}>清除预览</button>}</div>
      {message && <p className="success" role="status">{message}</p>}
      {preview && <div className="preview-block"><div className="panel-head"><div><h3>操作预览</h3><p className="muted">OpenAPI {preview.openapi} · {preview.tool_count} 个可导入操作</p></div><button className="primary" onClick={importSelected} disabled={busy || !importName.trim() || selected.length === 0}>导入所选（{selected.length}）</button></div>
        <div className="operation-list">{preview.tools.map(tool => <label className="operation-row" key={tool.name}><input type="checkbox" checked={selected.includes(tool.name)} onChange={event => setSelected(current => event.target.checked ? [...current, tool.name] : current.filter(name => name !== tool.name))} /><span className="operation-copy"><strong>{tool.name}</strong><small>{tool.description || "无描述"}</small><small>风险：{tool.risk_level} · 每次调用需审批</small><details><summary>参数定义</summary><pre>{JSON.stringify(tool.input_schema, null, 2)}</pre></details></span></label>)}</div>
      </div>}
    </div>}
    {!loading && !loadError && view === "tools" && <div className="panel software-tools-panel"><div className="panel-head"><h2>已注册工具</h2><button className="secondary" onClick={() => void load()}>刷新</button></div><div className="card-list">{tools.map(tool => <article className={`subcard ${tool.id === selectedTool ? "selected-card" : ""}`} key={tool.id}><button className="tool-select" aria-pressed={tool.id === selectedTool} onClick={() => setSelectedTool(tool.id)}><strong>{tool.name}</strong><span>{tool.description || "暂无描述"}</span><small>风险：{tool.risk_level} · {tool.enabled ? "已启用" : "已停用"}</small></button><button className="secondary" disabled={acting} onClick={() => void run(() => toggle(tool))}>{tool.enabled ? "停用" : "启用"}</button></article>)}</div>{tools.length === 0 && <p className="muted">暂无工具。</p>}<div className="software-debug"><h3>调用调试</h3><label className="field-label">工具<select value={selectedTool} onChange={event => setSelectedTool(event.target.value)}><option value="">选择工具</option>{tools.map(tool => <option key={tool.id} value={tool.id}>{tool.name}</option>)}</select></label><label className="field-label">参数 JSON<textarea className="code-input" value={invokeArguments} onChange={event => setInvokeArguments(event.target.value)} spellCheck={false} /></label><label className="checkbox-label"><input type="checkbox" checked={approved} onChange={event => setApproved(event.target.checked)} />我已确认本次调用风险并批准执行</label><button className="primary" onClick={() => void run(invoke)} disabled={acting || !selectedTool || !tools.find(tool => tool.id === selectedTool)?.enabled}>调用工具</button>{invokeResult && <pre className="software-result">{invokeResult}</pre>}</div></div>}
    {!loading && !loadError && view === "approvals" && <div className="panel"><div className="panel-head"><div><h2>待审批调用</h2><p className="muted">审批会在服务端持久化；批准后立即执行一次并写入调用记录。</p></div><button className="secondary" onClick={() => void load()}>刷新</button></div><div className="approval-list">{approvals.map(approval => <article className="subcard" key={approval.id}><strong>{tools.find(tool => tool.id === approval.tool_id)?.name || "已删除的工具"}</strong><small>主体：{accessKeys.find(key => key.id === approval.principal_id)?.name || (approval.principal_id ? "其他主体" : "—")} · {new Date(approval.created_at).toLocaleString()}</small><pre className="software-result">{JSON.stringify(approval.arguments || {}, null, 2)}</pre><div className="inline-form"><button className="primary" disabled={acting} onClick={() => void run(() => decideApproval(approval, true))}>批准并执行</button><button className="danger" disabled={acting} onClick={() => void run(() => decideApproval(approval, false))}>拒绝</button></div></article>)}{approvals.length === 0 && <p className="muted">暂无待审批调用。</p>}</div></div>}
    {!loading && !loadError && view === "calls" && <div className="panel"><div className="panel-head"><div><h2>调用记录</h2><p className="muted">请求与响应摘要已由服务端脱敏。</p></div><button className="secondary" onClick={() => void load()}>刷新</button></div><div className="table-wrap"><table><thead><tr><th>工具</th><th>主体</th><th>状态</th><th>耗时</th><th>错误</th><th>时间</th></tr></thead><tbody>{calls.map(call => <tr key={call.id}><td>{tools.find(tool => tool.id === call.tool_id)?.name || "已删除的工具"}</td><td>{accessKeys.find(key => key.id === call.principal_id)?.name || (call.principal_id ? "其他主体" : "—")}</td><td className={call.status === "succeeded" ? "success" : "error-cell"}>{call.status}</td><td>{call.duration_ms} ms</td><td>{call.error_type || "—"}</td><td>{new Date(call.created_at).toLocaleString()}</td></tr>)}</tbody></table>{calls.length === 0 && <p className="muted">暂无调用记录。</p>}</div></div>}
    {instanceOpen && <div className="drawer-backdrop" role="presentation"><section className="edit-drawer" role="dialog" aria-modal="true" aria-labelledby="instance-drawer-title"><DialogA11y onClose={() => setInstanceOpen(false)} /><div className="drawer-header"><div><span className="eyebrow">CLI / HTTP / MCP</span><h2 id="instance-drawer-title">{editingInstance ? "编辑连接器" : "添加连接器"}</h2></div><button className="icon-button" aria-label="关闭连接器编辑" onClick={() => setInstanceOpen(false)}>×</button></div><div className="drawer-content">      <div className="software-instance-form"><label className="field-label">实例名称<input value={instanceName} maxLength={128} onChange={event => setInstanceName(event.target.value)} placeholder="例如：本地工具" /></label><label className="field-label">连接器<select value={connectorType} onChange={event => setConnectorType(event.target.value)}><option value="http">HTTP</option><option value="cli">CLI</option><option value="mcp">MCP Server</option><option value="openapi">OpenAPI</option><option value="wechat">WeChat bridge</option><option value="clihub">CLIHub bridge</option></select></label><label className="field-label software-config">配置 JSON<textarea className="code-input" value={instanceConfig} onChange={event => setInstanceConfig(event.target.value)} spellCheck={false} /></label><div className="inline-form"><button className="primary" disabled={acting || !instanceName.trim()} onClick={() => void run(saveInstance)}>{editingInstance ? "保存实例" : "创建实例"}</button>{editingInstance && <button className="secondary" onClick={resetInstance}>取消编辑</button>}</div></div>
</div></section></div>}
  </section>;
}
