import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { askWiki, del, downloadFile, get, post, put, uploadRaw } from "./api";
import type { WikiAnswer, WikiAttachment, WikiGraph, WikiPage, WikiProject, WikiSource } from "./types";
import { renderWikiMarkdown } from "./markdown";
import "./wiki.css";

type Props = { onError: (message: string) => void };
type PageForm = { path: string; title: string; content: string; tags: string; revision?: number };
const blankPage: PageForm = { path: "", title: "", content: "", tags: "" };
const assetMediaTypes = new Set(["image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain"]);

function encode(value: string): string { return encodeURIComponent(value); }
function pageDto(form: PageForm) {
  return {
    path: form.path.trim(), title: form.title.trim(), content: form.content,
    tags: form.tags.split(",").map(tag => tag.trim()).filter(Boolean),
    ...(form.revision ? { revision: form.revision } : {}),
  };
}

export function WikiManager({ onError }: Props) {
  const [projects, setProjects] = useState<WikiProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [projectName, setProjectName] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [newProjectName, setNewProjectName] = useState("");
  const [pages, setPages] = useState<WikiPage[]>([]);
  const [selectedPage, setSelectedPage] = useState<WikiPage | null>(null);
  const [form, setForm] = useState<PageForm>(blankPage);
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [tags, setTags] = useState<Array<{ tag: string; count: number }>>([]);
  const [sources, setSources] = useState<WikiSource[]>([]);
  const [sourceFilename, setSourceFilename] = useState("");
  const [sourceContent, setSourceContent] = useState("");
  const [attachments, setAttachments] = useState<WikiAttachment[]>([]);
  const [graph, setGraph] = useState<WikiGraph>({ nodes: [], edges: [] });
  const [askQuestion, setAskQuestion] = useState("");
  const [askModel, setAskModel] = useState("gpt-4o");
  const [askTopK, setAskTopK] = useState("5");
  const [askResult, setAskResult] = useState<WikiAnswer | null>(null);
  const [askBusy, setAskBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const pageLoadSequence = useRef(0);
  const base = `/api/v1/wiki/projects/${encode(projectId)}`;

  const loadProjects = async (preferId?: string) => {
    try {
      const rows = await get<WikiProject[]>("/api/v1/wiki/projects");
      setProjects(rows);
      setProjectId(current => preferId && rows.some(row => row.id === preferId)
        ? preferId
        : rows.some(row => row.id === current) ? current : rows[0]?.id || "");
    } catch (error) { onError(error instanceof Error ? error.message : "无法读取 Wiki 项目"); }
  };
  useEffect(() => { void loadProjects(); }, []);

  const loadPages = async () => {
    if (!projectId) return;
    const sequence = ++pageLoadSequence.current;
    const query = new URLSearchParams();
    if (search.trim()) query.set("query", search.trim());
    if (tagFilter) query.set("tag", tagFilter);
    try {
      const result = await get<{ items: WikiPage[]; total: number }>(`${base}/pages?${query.toString()}`);
      if (sequence === pageLoadSequence.current) setPages(result.items);
    } catch (error) { onError(error instanceof Error ? error.message : "无法读取 Wiki 页面"); }
  };
  useEffect(() => {
    if (!projectId) return;
    let current = true;
    Promise.all([
      get<WikiProject>(base), get<Array<{ tag: string; count: number }>>(`${base}/tags`),
      get<WikiSource[]>(`${base}/sources`), get<WikiGraph>(`${base}/graph`),
    ]).then(([project, tagRows, sourceRows, graphData]) => {
      if (!current) return;
      setProjectName(project.name); setProjectDescription(project.description || "");
      setTags(tagRows); setSources(sourceRows); setGraph(graphData);
    }).catch((error: Error) => { if (current) onError(error.message); });
    return () => { current = false; };
  }, [projectId]);
  useEffect(() => { void loadPages(); }, [projectId, search, tagFilter]);

  const reloadProjectData = async () => {
    if (!projectId) return;
    await loadPages();
    try {
      const [tagRows, sourceRows, graphData] = await Promise.all([
        get<Array<{ tag: string; count: number }>>(`${base}/tags`),
        get<WikiSource[]>(`${base}/sources`), get<WikiGraph>(`${base}/graph`),
      ]);
      setTags(tagRows); setSources(sourceRows); setGraph(graphData);
    } catch (error) { onError(error instanceof Error ? error.message : "刷新 Wiki 数据失败"); }
  };

  const createProject = async () => {
    if (!newProjectName.trim()) return;
    setBusy(true);
    try {
      const project = await post<WikiProject>("/api/v1/wiki/projects", { name: newProjectName.trim(), description: "" });
      setNewProjectName(""); await loadProjects(project.id);
    } catch (error) { onError(error instanceof Error ? error.message : "创建项目失败"); }
    finally { setBusy(false); }
  };
  const saveProject = async () => {
    setBusy(true);
    try {
      const updated = await put<WikiProject>(base, { name: projectName.trim(), description: projectDescription });
      setProjects(items => items.map(item => item.id === updated.id ? updated : item));
    } catch (error) { onError(error instanceof Error ? error.message : "保存项目失败"); }
    finally { setBusy(false); }
  };
  const deleteProject = async () => {
    if (!window.confirm("删除此 Wiki 项目及其页面、来源和附件？")) return;
    try { await del(base); setProjectId(""); setSelectedPage(null); setForm(blankPage); await loadProjects(); }
    catch (error) { onError(error instanceof Error ? error.message : "删除项目失败"); }
  };

  const openPage = async (page: WikiPage) => {
    try {
      const detail = await get<WikiPage>(`${base}/pages/${encode(page.id)}`);
      setSelectedPage(detail);
      setForm({ path: detail.path, title: detail.title, content: detail.content || "", tags: (detail.tags || []).join(", "), revision: detail.revision });
      const assets = await get<WikiAttachment[]>(`${base}/pages/${encode(page.id)}/attachments`);
      setAttachments(assets);
    } catch (error) { onError(error instanceof Error ? error.message : "无法读取页面"); }
  };
  const newPage = () => { setSelectedPage(null); setAttachments([]); setForm(blankPage); };
  const savePage = async () => {
    if (!form.path.trim() || !form.title.trim()) return;
    setBusy(true);
    try {
      const dto = pageDto(form);
      const saved = selectedPage
        ? await put<WikiPage>(`${base}/pages/${encode(selectedPage.id)}`, dto)
        : await post<WikiPage>(`${base}/pages`, dto);
      setSelectedPage(saved); setForm({ ...form, revision: saved.revision, tags: (saved.tags || []).join(", ") });
      await reloadProjectData();
    } catch (error) { onError(error instanceof Error ? error.message : "保存页面失败"); }
    finally { setBusy(false); }
  };
  const deletePage = async () => {
    if (!selectedPage || !window.confirm(`删除页面“${selectedPage.title}”？`)) return;
    try { await del(`${base}/pages/${encode(selectedPage.id)}`); setSelectedPage(null); setAttachments([]); setForm(blankPage); await reloadProjectData(); }
    catch (error) { onError(error instanceof Error ? error.message : "删除页面失败"); }
  };
  const uploadAttachment = async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file || !selectedPage) return;
    if (file.size > 10 * 1024 * 1024) { onError("附件不能超过 10 MiB"); input.value = ""; return; }
    if (!assetMediaTypes.has(file.type)) { onError("附件类型不受支持"); input.value = ""; return; }
    try {
      const asset = await uploadRaw<WikiAttachment>(`${base}/pages/${encode(selectedPage.id)}/attachments?filename=${encode(file.name)}`, file);
      setAttachments(current => [...current, asset]);
    } catch (error) { onError(error instanceof Error ? error.message : "上传附件失败"); }
    finally { input.value = ""; }
  };
  const removeAttachment = async (asset: WikiAttachment) => {
    if (!window.confirm(`删除附件“${asset.filename}”？`)) return;
    try { await del(`${base}/attachments/${encode(asset.id)}`); setAttachments(current => current.filter(item => item.id !== asset.id)); }
    catch (error) { onError(error instanceof Error ? error.message : "删除附件失败"); }
  };
  const insertAttachment = (asset: WikiAttachment) => {
    const reference = `[${asset.filename}](/api/v1/wiki/projects/${encode(projectId)}/attachments/${encode(asset.id)})`;
    setForm(current => ({ ...current, content: `${current.content}${current.content.endsWith("\n") || !current.content ? "" : "\n"}${reference}\n` }));
  };

  const importSourceFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) return;
    try { setSourceFilename(file.name); setSourceContent(await file.text()); }
    catch (error) { onError(error instanceof Error ? error.message : "无法读取来源文件"); }
    finally { input.value = ""; }
  };
  const createSource = async () => {
    if (!sourceFilename.trim() || !sourceContent.trim()) return;
    try {
      await post(`${base}/sources`, { filename: sourceFilename.trim(), content: sourceContent });
      setSourceFilename(""); setSourceContent(""); await reloadProjectData();
    } catch (error) { onError(error instanceof Error ? error.message : "添加来源失败"); }
  };
  const ingestSource = async (source: WikiSource) => {
    try { await post(`${base}/sources/${encode(source.id)}/ingest`, {}); await reloadProjectData(); }
    catch (error) { onError(error instanceof Error ? error.message : "摄入来源失败"); }
  };
  const removeSource = async (source: WikiSource) => {
    if (!window.confirm(`删除来源“${source.filename}”？`)) return;
    try { await del(`${base}/sources/${encode(source.id)}`); await reloadProjectData(); }
    catch (error) { onError(error instanceof Error ? error.message : "删除来源失败"); }
  };

  const askProject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const question = askQuestion.trim();
    const model = askModel.trim();
    if (!question || !model || !projectId) return;
    setAskBusy(true);
    setAskResult(null);
    try {
      const result = await askWiki<WikiAnswer>(projectId, {
        question,
        model,
        top_k: Math.min(20, Math.max(1, Number.parseInt(askTopK, 10) || 5)),
      });
      setAskResult(result);
    } catch (error) { onError(error instanceof Error ? error.message : "Wiki 问答失败"); }
    finally { setAskBusy(false); }
  };

  const exportProject = async () => {
    try { await downloadFile(`${base}/backup`, `wiki-${projectId}.json`); }
    catch (error) { onError(error instanceof Error ? error.message : "导出备份失败"); }
  };
  const restoreProject = async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) return;
    if (file.size > 55 * 1024 * 1024) { onError("备份文件超过最大上传限制"); input.value = ""; return; }
    setBusy(true);
    try {
      const backup: unknown = JSON.parse(await file.text());
      const restored = await post<WikiProject>("/api/v1/wiki/restore", backup);
      await loadProjects(restored.id);
    } catch (error) { onError(error instanceof Error ? error.message : "恢复 Wiki 备份失败"); }
    finally { setBusy(false); input.value = ""; }
  };

  if (!projectId) return <section><div className="panel"><h2>Wiki 项目</h2><p className="muted">创建一个项目来管理 Markdown 页面、附件与来源。</p><div className="inline-form"><input aria-label="新项目名称" placeholder="新项目名称" value={newProjectName} onChange={event => setNewProjectName(event.target.value)} /><button className="primary" onClick={createProject} disabled={busy}>创建项目</button><label className="secondary file-button">恢复备份<input type="file" accept="application/json,.json" onChange={restoreProject} /></label></div></div></section>;

  return <section className="wiki-manager">
    <div className="panel wiki-toolbar">
      <label className="field-label">当前项目<select value={projectId} onChange={event => { setProjectId(event.target.value); setSelectedPage(null); setForm(blankPage); }}>
        {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
      </select></label>
      <div className="wiki-toolbar-actions"><button className="primary" onClick={newPage}>新建页面</button><button className="secondary" onClick={exportProject}>导出备份</button><label className="secondary file-button">恢复备份<input type="file" accept="application/json,.json" onChange={restoreProject} /></label></div>
      <div className="inline-form"><input aria-label="新项目名称" placeholder="新项目名称" value={newProjectName} onChange={event => setNewProjectName(event.target.value)} /><button className="secondary" onClick={createProject} disabled={busy}>创建项目</button></div>
      <details className="project-settings"><summary>项目设置</summary><div className="inline-form"><input aria-label="项目名称" value={projectName} onChange={event => setProjectName(event.target.value)} /><input aria-label="项目描述" placeholder="项目描述" value={projectDescription} onChange={event => setProjectDescription(event.target.value)} /><button className="secondary" onClick={saveProject} disabled={busy}>保存设置</button><button className="danger" onClick={deleteProject}>删除项目</button></div></details>
    </div>

    <div className="wiki-layout">
      <aside className="panel wiki-sidebar">
        <div className="wiki-search"><input aria-label="搜索页面" placeholder="搜索页面…" value={search} onChange={event => setSearch(event.target.value)} /><select aria-label="按标签筛选" value={tagFilter} onChange={event => setTagFilter(event.target.value)}><option value="">所有标签</option>{tags.map(item => <option key={item.tag} value={item.tag}>{item.tag} ({item.count})</option>)}</select></div>
        <div className="wiki-page-list">{pages.map(page => <button className={`wiki-page-item ${selectedPage?.id === page.id ? "selected" : ""}`} key={page.id} onClick={() => void openPage(page)}><strong>{page.title}</strong><small>{page.path}</small><small>{page.tags?.join(" · ") || "无标签"}</small></button>)}{pages.length === 0 && <p className="muted">没有匹配页面。</p>}</div>
      </aside>

      <div className="wiki-editor-column">
        <div className="panel wiki-editor">
          <div className="panel-head"><div><h2>{selectedPage ? "编辑页面" : "新建页面"}</h2><p className="muted">{selectedPage ? `当前修订 ${selectedPage.revision ?? form.revision ?? "—"}` : "页面路径用于目录层级和 Wikilinks 解析。"}</p></div><div className="wiki-toolbar-actions"><button className="primary" onClick={savePage} disabled={busy || !form.title.trim() || !form.path.trim()}>{busy ? "保存中…" : "保存页面"}</button>{selectedPage && <button className="danger" onClick={deletePage}>删除</button>}</div></div>
          <label className="field-label">标题<input value={form.title} maxLength={256} onChange={event => setForm(current => ({ ...current, title: event.target.value }))} /></label>
          <label className="field-label">路径<input value={form.path} placeholder="guide/getting-started.md" onChange={event => setForm(current => ({ ...current, path: event.target.value }))} /></label>
          <label className="field-label">标签（逗号分隔）<input value={form.tags} placeholder="指南, 入门" onChange={event => setForm(current => ({ ...current, tags: event.target.value }))} /></label>
          <div className="wiki-content-grid"><label className="field-label">Markdown 内容<textarea className="wiki-content-input" value={form.content} maxLength={1_000_000} onChange={event => setForm(current => ({ ...current, content: event.target.value }))} /></label><div className="field-label"><span>安全预览</span>{renderWikiMarkdown(form.content, `/api/v1/wiki/projects/${encode(projectId)}/attachments/`)}</div></div>
          {selectedPage && <div className="wiki-attachments"><div className="panel-head"><h3>页面附件</h3><label className="secondary file-button">上传附件<input type="file" accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain" onChange={uploadAttachment} /></label></div><p className="muted">附件不会自动插入正文；用“插入引用”添加链接。</p><div className="wiki-asset-list">{attachments.map(asset => <article className="wiki-asset" key={asset.id}><span>{asset.filename}</span><small>{asset.media_type}</small><button className="secondary" onClick={() => insertAttachment(asset)}>插入引用</button><a href={`${base}/attachments/${encode(asset.id)}`}>下载</a><button className="danger" onClick={() => void removeAttachment(asset)}>删除</button></article>)}{attachments.length === 0 && <p className="muted">暂无附件。</p>}</div></div>}
        </div>

        <div className="panel wiki-sources"><div className="panel-head"><div><h2>来源摄入</h2><p className="muted">支持 Markdown 和 UTF-8 文本。</p></div></div><div className="wiki-source-form"><input aria-label="来源文件名" placeholder="文件名.md" value={sourceFilename} onChange={event => setSourceFilename(event.target.value)} /><label className="secondary file-button">读取文本文件<input type="file" accept=".md,.markdown,.txt,text/plain,text/markdown" onChange={importSourceFile} /></label><textarea aria-label="来源内容" placeholder="粘贴来源文本…" value={sourceContent} maxLength={1_000_000} onChange={event => setSourceContent(event.target.value)} /><button className="primary" onClick={createSource} disabled={!sourceFilename.trim() || !sourceContent.trim()}>添加来源</button></div><div className="wiki-source-list">{sources.map(source => <article className="wiki-source" key={source.id}><span><strong>{source.filename}</strong><small>状态：{source.status}{source.error_message ? ` · ${source.error_message}` : ""}</small></span><button className="secondary" onClick={() => void ingestSource(source)} disabled={source.status === "ingested"}>摄入</button><button className="danger" onClick={() => void removeSource(source)}>删除</button></article>)}{sources.length === 0 && <p className="muted">暂无来源。</p>}</div></div>

        <div className="panel wiki-graph"><div className="panel-head"><div><h2>页面关系图</h2><p className="muted">由正文中的 [[wikilinks]] 生成。</p></div><button className="secondary" onClick={() => void reloadProjectData()}>刷新关系</button></div><div className="wiki-graph-grid">{graph.nodes.map(node => <article className="wiki-graph-node" key={node.id}><strong>{node.title}</strong><small>{node.path}</small><ul>{graph.edges.filter(edge => edge.source === node.id).map((edge, index) => <li key={`${node.id}-${index}`}>{edge.resolved ? "→" : "↗"} {edge.path}{!edge.resolved && "（未解析）"}</li>)}</ul></article>)}{graph.nodes.length === 0 && <p className="muted">项目中还没有页面关系。</p>}</div></div>

        <div className="panel wiki-ask"><div className="panel-head"><div><h2>Wiki 问答</h2><p className="muted">只使用当前项目中检索到的页面内容回答，并返回引用来源。</p></div></div><form className="wiki-ask-form" onSubmit={askProject}><label className="field-label wiki-ask-question">问题<textarea aria-label="Wiki 问题" value={askQuestion} maxLength={32768} placeholder="例如：入门流程有哪些步骤？" onChange={event => setAskQuestion(event.target.value)} /></label><label className="field-label">模型<input aria-label="问答模型" value={askModel} maxLength={128} onChange={event => setAskModel(event.target.value)} /></label><label className="field-label">引用页面数<input aria-label="引用页面数" type="number" min="1" max="20" value={askTopK} onChange={event => setAskTopK(event.target.value)} /></label><button className="primary wiki-ask-submit" type="submit" disabled={askBusy || !askQuestion.trim() || !askModel.trim()}>{askBusy ? "检索并回答中…" : "开始问答"}</button></form>{askResult && <div className="wiki-answer" aria-live="polite"><h3>回答</h3>{renderWikiMarkdown(askResult.answer, `/api/v1/wiki/projects/${encode(projectId)}/attachments/`)}{askResult.sources.length > 0 && <div className="wiki-answer-sources"><h3>引用来源</h3>{askResult.sources.map(source => <details key={source.page_id}><summary>{source.title} · {source.path}</summary><pre>{source.content}</pre></details>)}</div>}</div>}</div>
      </div>
    </div>
  </section>;
}
