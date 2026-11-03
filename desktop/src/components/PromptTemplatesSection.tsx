import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeftRight, FileText, Loader2, Plus, Save } from "lucide-react";
import { promptTemplateApi } from "../lib/api";
import type { PromptTemplate } from "../types";

/** Prompt 模板管理（C-07）：按 key 分组列版本、编辑新建版本、一键激活/回滚。
 *  种子 = 源码字面量 v1；激活新版本立即生效，回滚 v1 同理；占位符非法拒绝激活。
 *  作为「服务」页下的一个区块嵌入，与 RAG / Wiki / MCP 并列。 */
export function PromptTemplatesSection() {
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTemplates(await promptTemplateApi.list());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const grouped = useMemo(() => {
    const map = new Map<string, PromptTemplate[]>();
    for (const t of templates) {
      const list = map.get(t.template_key) ?? [];
      list.push(t);
      map.set(t.template_key, list);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [templates]);

  const activeOf = (key: string) => grouped.find(([k]) => k === key)?.[1].find(t => t.active);

  const startEdit = (key: string) => {
    setEditingKey(key);
    setDraft(activeOf(key)?.content ?? "");
    setNotice(null);
  };

  const saveNewVersion = async (key: string) => {
    setNotice(null);
    setError(null);
    try {
      const version = await promptTemplateApi.create(key, draft);
      setNotice(`已保存 ${key} v${version}（未激活，预览确认后一键激活）`);
      setEditingKey(null);
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const activate = async (key: string, version: number) => {
    setNotice(null);
    setError(null);
    try {
      await promptTemplateApi.activate(key, version);
      setNotice(`已激活 ${key} v${version}，立即生效`);
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  if (loading && templates.length === 0) {
    return (
      <div className="surface empty-state">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 说明卡片 */}
      <div className="surface data-card rounded-2xl">
        <div className="flex items-start gap-4">
          <div className="flex-shrink-0 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 p-3 text-white shadow-lg shadow-blue-500/20">
            <FileText size={22} />
          </div>
          <div className="flex-1">
            <h3 className="text-base font-semibold text-slate-900">Prompt 模板版本化</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">
              RAG 问答与深度研究的系统提示词版本化管理：编辑保存生成新版本，一键激活/回滚立即生效；
              升级时自动以源码字面量种子 v1（行为逐字节不变）；含非法占位符的模板会被拒绝。
            </p>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
          {error}
          <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-red-600">✕</button>
        </div>
      )}
      {notice && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-600">
          {notice}
          <button onClick={() => setNotice(null)} className="ml-2 text-emerald-400 hover:text-emerald-600">✕</button>
        </div>
      )}

      {grouped.length === 0 ? (
        <div className="surface empty-state rounded-2xl">
          <FileText className="h-12 w-12 text-slate-300" />
          <p className="text-sm text-slate-500">暂无 Prompt 模板</p>
        </div>
      ) : (
        <div className="space-y-3">
          {grouped.map(([key, versions]) => {
            const active = versions.find(v => v.active);
            return (
              <div key={key} className="surface data-card rounded-2xl">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-50">
                      <FileText className="h-4 w-4 text-blue-600" />
                    </div>
                    <div>
                      <div className="font-mono text-sm font-semibold text-slate-900">{key}</div>
                      <div className="text-xs text-slate-500">
                        当前激活 v{active?.version ?? "-"} · 共 {versions.length} 个版本
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => (editingKey === key ? setEditingKey(null) : startEdit(key))}
                    className="flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-900"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    {editingKey === key ? "取消编辑" : "编辑新版本"}
                  </button>
                </div>

                {editingKey === key && (
                  <div className="mb-4">
                    <textarea
                      value={draft}
                      onChange={e => setDraft(e.target.value)}
                      rows={10}
                      className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 font-mono text-xs text-slate-800 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                    />
                    <div className="mt-2 flex items-center gap-2">
                      <button
                        onClick={() => void saveNewVersion(key)}
                        className="action-primary"
                      >
                        <Save className="h-3.5 w-3.5" /> 保存为新版本
                      </button>
                      <span className="text-xs text-slate-400">
                        保存仅校验占位符；激活后才切换生效
                      </span>
                    </div>
                  </div>
                )}

                <div className="space-y-2">
                  {versions.map(v => (
                    <div
                      key={v.id}
                      className={`flex items-center justify-between gap-3 rounded-xl border px-3 py-2 ${
                        v.active
                          ? "border-emerald-200 bg-emerald-50/50"
                          : "border-slate-100 bg-slate-50/60"
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 text-xs">
                          <span className="font-mono font-semibold text-slate-800">v{v.version}</span>
                          {v.active && (
                            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                              激活中
                            </span>
                          )}
                          <span className="text-slate-400">{v.created_at}</span>
                        </div>
                        <pre className="mt-1 max-h-24 overflow-y-auto whitespace-pre-wrap break-all text-xs text-slate-500">
                          {v.content}
                        </pre>
                      </div>
                      {!v.active && (
                        <button
                          onClick={() => void activate(key, v.version)}
                          className="flex shrink-0 items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:border-blue-200 hover:bg-blue-50 hover:text-blue-600"
                        >
                          <ArrowLeftRight className="h-3.5 w-3.5" />
                          {v.version === 1 ? "回滚到此版本" : "激活此版本"}
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
