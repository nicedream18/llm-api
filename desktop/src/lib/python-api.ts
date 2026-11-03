/** Rust UI command contracts adapted to the authenticated Python REST API. */
import { getWebAdminToken, WEB_UNAUTHORIZED_EVENT } from './runtime';
import { nativeBridge } from './native';

type Row = Record<string, any>;
const enc = (value: unknown) => encodeURIComponent(String(value));
export async function request<T = any>(path: string, method = 'GET', body?: unknown, query?: Row): Promise<T> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query || {})) { if (value !== undefined && value !== null && value !== '') params.set(key, String(value)); }
  const token = getWebAdminToken();
  const response = await fetch('/api/v1' + path + (params.size ? '?' + params.toString() : ''), {
    method, credentials: 'include',
    headers: { ...(body !== undefined ? { 'content-type': 'application/json' } : {}), ...(token ? { authorization: 'Bearer ' + token } : {}) },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  if (response.status === 401) window.dispatchEvent(new Event(WEB_UNAUTHORIZED_EVENT));
  const payload = await response.json().catch(() => null);
  if (!response.ok || (payload?.code !== undefined && payload.code !== '0000')) {
    const detail = payload?.detail;
    throw new Error(payload?.info || (typeof detail === 'string' ? detail : undefined) || 'Python API 请求失败（HTTP ' + response.status + '）');
  }
  if (payload === null) throw new Error('Python API 返回了无效 JSON');
  return (payload.code !== undefined ? payload.data : payload) as T;
}

export function adaptChannel(row: Row): Row {
  const protocol = row.type === 'claude' || row.type === 'anthropic' ? 'anthropic' : row.type === 'ollama' ? 'ollama' : 'openai';
  return { ...row, config: row.config || {}, models: row.models || [], model_mapping: row.model_mapping || {},
    protocol, provider: row.type === 'claude' ? 'anthropic' : row.type, native_base_url: row.base_url || '',
    native_endpoints: protocol === 'anthropic' ? ['messages'] : protocol === 'ollama' ? ['api_chat'] : ['chat_completions'],
    identity_revision: 1, executor_kind: row.type, timeout_secs: row.config?.timeout_secs || 300,
    extra_keys: row.api_keys || [], request_headers: [], last_probe_at: null, last_probe_ok: null, probe_latency_ms: null };
}
function adaptKey(row: Row): Row { return { ...row, denied_models: [], denied_channels: [], allowed_models: row.allowed_models || [], allowed_channels: row.allowed_channels || [] }; }
function adaptStats(row: Row): Row { return { ...row, prompt_tokens: row.input_tokens || 0, completion_tokens: row.output_tokens || 0, cached_tokens: 0 }; }
function adaptAccount(row: Row): Row {
  return { ...row, label: row.name, account_id: row.id, disabled: row.status !== 'active' || row.enabled === false,
    models: (row.models || []).map((model: string | Row) => typeof model === 'string' ? { id: model, status: 'available', unavailable: false, next_retry_after: null, last_error: null } : model),
    quota: Array.isArray(row.quota?.limits) ? row.quota : null, model_mapping: row.model_mapping || {}, model_mapping_disabled: [], sort_order: 0, weight: 1,
    expires_at: row.expires_at || null, email: row.email || null, hasRefreshToken: false };
}
function adaptLog(row: Row): Row {
  const created = String(row.created_at || '').replace(' ', 'T');
  return { ...row, created_at: created && !/(Z|[+-][0-9]{2}:[0-9]{2})$/.test(created) ? created + 'Z' : created,
    risk_level: String(row.risk_level || 'clean').toLowerCase(), security_action: String(row.security_action || 'allow').toLowerCase(),
    latency_ms: row.duration_ms || 0, request_tokens: row.prompt_tokens || 0, response_tokens: row.completion_tokens || 0,
    is_stream: row.is_stream ?? row.stream, request_body: row.request_body || '', response_body: row.response_choices || '', cached_tokens: 0 };
}
function adaptKb(row: Row): Row { return { ...row, excluded_dirs: '', excluded_files: '', included_files: '', mcp_enabled: 1, embedding_batch_size: 16 }; }
function adaptDoc(row: Row): Row { return { ...row, error_message: row.error_message || row.task_error_message, doc_meta: typeof row.doc_meta === 'string' ? row.doc_meta : JSON.stringify(row.doc_meta || {}), ocr_failed_pages: '[]' }; }
function adaptWiki(row: Row): Row { return { ...row, wiki_dir: '', mcp_enabled: 1, page_count: row.page_count || 0, source_count: row.source_count || 0 }; }
function adaptPage(row: Row): Row { return { ...row, page_type: row.page_type || 'article', token_count: row.token_count || 0, tags: JSON.stringify(row.tags || []), wikilinks: '[]', frontmatter: '{}' }; }
function unsupported(command: string): never { throw new Error('Python 后端暂未支持此操作：' + command + '。界面已迁移，此能力尚未接入。'); }
function wikiInput(input: Row): Row {
  for (const [key, value] of Object.entries(input)) {
    if (!['name', 'description'].includes(key) && value !== undefined && value !== null && value !== '') unsupported('Wiki 高级配置 ' + key);
  }
  return { name: input.name, description: input.description || '' };
}

const securityKeys = ['enabled', 'mode', 'scan_unicode', 'scan_tools', 'scan_network', 'scan_response', 'redact_secrets', 'block_on_critical'];
const preferencesKey = 'waliapi.desktop.preferences';
async function getSettings(): Promise<Row> {
  const [security, runtime] = await Promise.all([request('/security/settings'), request('/desktop/runtime')]);
  let prefs: Row = {}; try { prefs = JSON.parse(localStorage.getItem(preferencesKey) || '{}'); } catch { /* corrupt local preferences */ }
  return { ...runtime, server_host: '127.0.0.1', ui_theme: prefs.ui_theme || 'light', ui_language: prefs.ui_language || 'zh-CN',
    auto_start: false, minimize_to_tray: false, close_to_tray: false,
    ...Object.fromEntries(securityKeys.map(key => ['security_' + key, security[key]])) };
}
function presets(): Row[] {
  return ['openai', 'anthropic', 'ollama'].map(protocol => {
    const endpoint = protocol === 'anthropic' ? 'messages' : protocol === 'ollama' ? 'api_chat' : 'chat_completions';
    const custom = { id: protocol + '-custom', protocol, provider: 'custom', display_name: '自定义', region: 'custom', description: '', icon_key: 'custom',
      native_base_url: '', legacy_base_url: '', legacy_type: protocol === 'anthropic' ? 'claude' : protocol, native_endpoints: [endpoint],
      default_checked_endpoints: [endpoint], auth_scheme: protocol === 'anthropic' ? 'x_api_key' : protocol === 'ollama' ? 'optional_bearer' : 'bearer',
      model_suggestions: [], model_enum_strategy: 'static_only', endpoint_test_strategy: 'probe_first_model', preset_revision: 'python-1' };
    return { protocol, presets: [custom] };
  });
}
async function channelInput(input: Row): Promise<Row> {
  if (input.request_headers?.length || input.model_mapping_disabled?.length) unsupported('渠道自定义请求头或禁用映射');
  const current = input.id ? await request('/channels/' + enc(input.id)) : {};
  const result = { ...current, ...input, config: { ...current.config, ...input.config, ...(input.timeout_secs !== undefined ? { timeout_secs: input.timeout_secs } : {}) } };
  if (input.extra_keys !== undefined) result.api_keys = input.extra_keys;
  if (input.clear_api_key) result.api_key = '';
  else if (input.id && !input.api_key) result.api_key = current.api_key;
  return result;
}

export async function invokePython(command: string, args: Row = {}): Promise<unknown> {
  const input = args.input || {}; const id = enc(args.id ?? input.id); const kb = enc(args.kbId ?? input.kb_id);
  const project = enc(args.projectId ?? args.id);
  switch (command) {
    case 'get_channels': return (await request<Row[]>('/channels')).map(adaptChannel);
    case 'get_channel': return adaptChannel(await request('/channels/' + id));
    case 'get_channel_api_key': return request('/desktop/secret/channel/' + id);
    case 'create_channel': return adaptChannel(await request('/channels', 'POST', await channelInput(input)));
    case 'update_channel': { await request('/channels', 'PUT', await channelInput(input)); return adaptChannel(await request('/channels/' + id)); }
    case 'toggle_channel': return request('/channels', 'PUT', { ...await request('/channels/' + id), status: args.status });
    case 'delete_channel': return request('/channels/' + id, 'DELETE');
    case 'get_channel_presets': return presets();
    case 'get_channel_stats': return (await request<Row[]>('/desktop/stats/channel')).map(adaptStats);
    case 'get_channel_extra_keys': return request('/channels/' + id + '/api-keys');
    case 'test_channel': { const result = await request('/channels/' + id + '/test', 'POST'); return { ...result, latency_ms: result.duration_ms }; }
    case 'test_channel_draft': {
      const result = await request('/channels/test-draft', 'POST', await channelInput(input));
      // Python currently performs one protocol probe, not the Rust multi-endpoint receipt.
      const endpoint = input.protocol === 'anthropic' ? 'messages' : input.protocol === 'ollama' ? 'api_chat' : 'chat_completions';
      return { draft_fingerprint: '', test_run_id: '', tested_at: new Date().toISOString(), results: (input.native_endpoints || [endpoint]).map((value: string) => ({
        endpoint: value, status: value === endpoint ? result.success ? 'passed' : 'failed' : 'skipped',
        message: value === endpoint ? result.message : 'Python 后端尚不支持逐端点探测', latency_ms: value === endpoint ? result.duration_ms : 0,
        tested_model: input.models?.[0] || null, cost_possible: value === endpoint,
      })) };
    }
    case 'get_api_keys': return (await request<Row[]>('/api-keys')).map(adaptKey);
    case 'get_api_key_full': return request('/desktop/secret/api-key/' + id);
    case 'get_api_key_stats': return (await request<Row[]>('/desktop/stats/api_key')).map(adaptStats);
    case 'create_api_key':
      if (input.denied_models?.length || input.denied_channels?.length) return unsupported(command + ': 排除规则');
      return adaptKey(await request('/api-keys', 'POST', input));
    case 'update_api_key':
      if (input.denied_models?.length || input.denied_channels?.length) return unsupported(command + ': 排除规则');
      return request('/api-keys', 'PUT', { ...await request('/api-keys/' + id), ...input });
    case 'delete_api_key': return request('/api-keys/' + id, 'DELETE');
    case 'get_api_key_answer_models': return [...new Set((await request<Row[]>('/channels')).flatMap(row => row.models || []))];
    case 'get_dashboard_stats': return { ...await request('/desktop/overview'), today_cached_tokens: 0, total_cached_tokens: 0, avg_ttft_ms: 0 };
    case 'get_model_stats': return (await request<Row[]>('/desktop/stats/model')).map(row => ({ ...row, request_count: row.total_calls, cached_tokens: 0, success_rate: row.total_calls ? row.success_calls / row.total_calls * 100 : 0 }));
    case 'get_token_trend': return request('/desktop/tokens', 'GET', undefined, { hours: args.hours || 24 });
    case 'get_prompt_part_stats': return []; // not measured by the Python backend
    case 'get_daily_token_stats': return request('/desktop/daily-tokens', 'GET', undefined, { days: args.days });
    case 'get_route_flow': return request('/desktop/route-flow', 'GET', undefined, { hours: args.hours || 24 });
    case 'get_logs': return (await request('/desktop/logs', 'GET', undefined, input)).items.map(adaptLog);
    case 'count_logs': return (await request('/desktop/logs', 'GET', undefined, { ...input, count_only: true })).total;
    case 'get_log': return adaptLog(await request('/logs/' + id));
    case 'get_log_filter_options': return request('/desktop/log-filters');
    case 'get_log_attempts': return request('/logs/' + enc(args.logId) + '/attempts');
    case 'get_log_security_findings': return request('/security/findings/by-log/' + enc(args.logId));
    case 'get_log_stream_segments': case 'get_log_prompt_parts': return [];
    case 'delete_log': return request('/logs/' + id, 'DELETE');
    case 'delete_all_logs': return request('/logs', 'DELETE');
    case 'delete_logs_before': return request('/logs/before', 'DELETE', undefined, { cutoff: args.beforeDate });
    case 'get_settings': return getSettings();
    case 'save_settings': {
      const settings = args.settings;
      await request('/security/settings', 'PUT', Object.fromEntries(securityKeys.map(key => [key, settings['security_' + key]])));
      localStorage.setItem(preferencesKey, JSON.stringify({ ui_theme: settings.ui_theme, ui_language: settings.ui_language })); return;
    }
    case 'apply_theme': document.documentElement.setAttribute('data-theme', args.theme); return;
    case 'get_server_status': { const runtime = await request('/desktop/runtime'); return { running: true, port: runtime.server_port, url: location.origin }; }
    case 'get_builtin_security_rules': return (await request<Row[]>('/security/rules/builtin')).map(row => ({ ...row, title: row.name, enabled: Boolean(row.enabled) }));
    case 'update_builtin_security_rule': return request('/security/rules/builtin/' + id, 'PUT', { ...input, ...(input.title !== undefined ? { name: input.title } : {}) });
    case 'get_custom_security_rules': return (await request<Row[]>('/security/rules/custom')).map(row => ({ ...row, title: row.name, enabled: Boolean(row.enabled) }));
    case 'create_custom_security_rule':
      if (input.rule_type && input.rule_type !== 'blacklist') unsupported('安全规则白名单');
      return request('/security/rules/custom', 'POST', { ...input, name: input.name || input.description || input.pattern });
    case 'toggle_custom_security_rule': { const rows = await request<Row[]>('/security/rules/custom'); const row = rows.find(item => String(item.id) === String(args.id)); if (!row) throw new Error('规则不存在'); return request('/security/rules/custom/' + id, 'PUT', { ...row, enabled: args.enabled }); }
    case 'delete_custom_security_rule': return request('/security/rules/custom/' + id, 'DELETE');
    case 'get_knowledge_bases': return (await request<Row[]>('/kb')).map(adaptKb);
    case 'create_knowledge_base': return adaptKb(await request('/kb', 'POST', input));
    case 'update_knowledge_base': return request('/kb/' + id, 'PUT', { ...await request('/kb/' + id), ...input });
    case 'delete_knowledge_base': return request('/kb/' + id, 'DELETE');
    case 'get_kb_documents': return (await request<Row[]>('/kb/' + kb + '/documents')).map(adaptDoc);
    case 'upload_kb_document': return adaptDoc(await request('/kb/' + enc(input.kb_id) + '/documents', 'POST', { ...input, file_type: input.filename.split('.').pop()?.toLowerCase() || 'txt' }));
    case 'upload_kb_document_from_path': { const file = await (await nativeBridge()).read_file(args.path); return adaptDoc(await request('/kb/' + kb + '/documents', 'POST', { filename: file.name, content: file.base64, file_type: file.name.split('.').pop()?.toLowerCase() || 'txt' })); }
    case 'delete_kb_document': return request('/kb/' + kb + '/documents/' + enc(args.docId), 'DELETE');
    case 'search_knowledge_base': return request('/kb/' + enc(input.kb_id) + '/search', 'POST', input);
    case 'ask_knowledge_base': return request('/kb/' + enc(input.kb_id) + (input.deep_research ? '/deep-research' : '/ask'), 'POST', input);
    case 'get_kb_stats': return request('/kb/' + kb + '/stats');
    case 'get_kb_conversations': return request('/kb/' + kb + '/conversations');
    case 'clear_kb_conversations': return request('/kb/' + kb + '/conversations', 'DELETE');
    case 'get_kb_sources': return request('/kb/' + kb + '/sources');
    case 'delete_kb_source': return request('/kb/' + kb + '/sources/' + enc(args.sourceId), 'DELETE');
    case 'get_kb_index_status': return request('/kb/' + kb + '/index');
    case 'build_kb_index': return request('/kb/' + kb + '/index', 'POST');
    case 'drop_kb_index': return request('/kb/' + kb + '/index', 'DELETE');
    case 'get_kb_tags': return request('/kb/' + kb + '/tags', 'GET', undefined, { limit: args.limit });
    case 'get_wiki_projects': return (await request<Row[]>('/wiki/projects')).map(adaptWiki);
    case 'get_wiki_project': return adaptWiki(await request('/wiki/projects/' + id));
    case 'create_wiki_project': return adaptWiki(await request('/wiki/projects', 'POST', wikiInput(input)));
    case 'update_wiki_project': { const fields = wikiInput(input); const current = await request('/wiki/projects/' + id); return request('/wiki/projects/' + id, 'PUT', { name: fields.name ?? current.name, description: input.description ?? current.description ?? '' }); }
    case 'delete_wiki_project': return request('/wiki/projects/' + id, 'DELETE');
    case 'get_wiki_pages': return (await request('/wiki/projects/' + project + '/pages', 'GET', undefined, { limit: 500 })).items.map(adaptPage);
    case 'get_wiki_page': { const pages = await request('/wiki/projects/' + project + '/pages', 'GET', undefined, { limit: 500 }); const row = pages.items.find((item: Row) => item.path === args.path); if (!row) throw new Error('页面不存在'); return adaptPage(await request('/wiki/projects/' + project + '/pages/' + enc(row.id))); }
    case 'save_wiki_page': { const pages = await request('/wiki/projects/' + project + '/pages', 'GET', undefined, { limit: 500 }); const row = pages.items.find((item: Row) => item.path === args.path);
      if (row) { const current = await request('/wiki/projects/' + project + '/pages/' + enc(row.id)); return request('/wiki/projects/' + project + '/pages/' + enc(row.id), 'PUT', { path: args.path, content: args.content, title: current.title, tags: current.tags || [], revision: current.revision }); }
      return request('/wiki/projects/' + project + '/pages', 'POST', { path: args.path, title: args.path.split('/').pop(), content: args.content }); }
    case 'get_wiki_sources': return request('/wiki/projects/' + project + '/sources');
    case 'add_wiki_source': return request('/wiki/projects/' + project + '/sources', 'POST', { filename: input.filename, content: input.content });
    case 'get_wiki_graph': return request('/wiki/projects/' + project + '/graph');
    case 'get_wiki_tags': return (await request<Row[]>('/wiki/projects/' + project + '/tags')).map(row => ({ word: row.tag || row.word, count: row.count }));
    case 'ingest_wiki_source': return request('/wiki/projects/' + project + '/sources/' + enc(args.sourceId) + '/ingest', 'POST');
    case 'get_service_statuses': {
      const [health, bases, projects, mcp] = await Promise.all([request('/health/details'), request<Row[]>('/kb'), request<Row[]>('/wiki/projects'), request('/mcp/tools')]);
      return [
        { id: 'knowledge', name: '知识库', description: 'Python 知识库与后台任务', enabled: true, running: health.checks.database === 'ok' && health.checks.worker === 'running', stats: { knowledge_bases: bases.length, documents: bases.reduce((sum, row) => sum + (row.doc_count || 0), 0), chunks: bases.reduce((sum, row) => sum + (row.chunk_count || 0), 0) } },
        { id: 'wiki', name: 'Wiki', description: 'Python Wiki 服务', enabled: true, running: health.checks.database === 'ok', stats: { projects: projects.length } },
        { id: 'mcp', name: 'MCP', description: 'Python MCP 工具接口', enabled: true, running: true, stats: { tools: (mcp.tools || mcp).map((tool: Row) => ({ ...tool, label: tool.name, desc: tool.description })) } },
      ];
    }
    case 'auth_accounts_list': return (await request<Row[]>('/providers')).map(adaptAccount);
    case 'auth_providers_list': return (await request<Row[]>('/providers/capabilities')).map(row => ({ id: row.provider, displayName: row.provider, iconKey: row.provider, loginMode: 'configured_oauth', loginMethods: [], supportsImport: false, supportsExport: false, supportsQuota: false }));
    case 'auth_refresh_token': { await request('/providers/' + id + '/refresh', 'POST'); return adaptAccount(await request('/providers/' + id)); }
    case 'auth_sync_models': { await request('/providers/' + id + '/models'); return adaptAccount(await request('/providers/' + id)); }
    case 'auth_toggle': { await request('/providers/' + id + '/operations', 'POST', { operation: 'enabled', enabled: !args.disabled }); return adaptAccount(await request('/providers/' + id)); }
    case 'auth_logout': return { deleted: await request('/providers/' + id, 'DELETE') };
    case 'export_channels': return JSON.stringify(await request('/channels/export'), null, 2);
    case 'import_waliapi_export': { const parsed = JSON.parse(args.content); const result = await request('/channels/import', 'POST', { channels: Array.isArray(parsed) ? parsed : parsed.channels }); return { imported: result.created.length + result.updated.length, skipped: result.skipped.length, errors: [] }; }
    case 'pick_import_file': { const bridge = await nativeBridge(); const path = await bridge.select_files(false, false); if (!path || Array.isArray(path)) return null; const file = await bridge.read_file(path); return new TextDecoder().decode(Uint8Array.from(atob(file.base64), ch => ch.charCodeAt(0))); }
    case 'save_export_file': return (await nativeBridge()).save_file(args.content, args.defaultName);
    case 'list_prompt_templates': return (await request<Row[]>('/platform/prompts')).map(row => ({ ...row, template_key: row.name, content: row.template, version: row.version || 1, active: row.enabled }));
    case 'create_prompt_template': return request('/platform/prompts', 'POST', { name: args.templateKey, template: args.content });
    case 'clear_semantic_cache': return request('/platform/cache', 'DELETE');
    case 'get_software_instances': return (await request<Row[]>('/software/instances')).map(row => ({ ...row, connector: row.connector_type, config: typeof row.config === 'string' ? row.config : JSON.stringify(row.config || {}) }));
    case 'delete_software_instance': return request('/software/instances/' + id, 'DELETE');
    case 'get_software_tool_logs': return request('/software/calls', 'GET', undefined, { limit: args.limit });
    case 'get_app_configs': return unsupported('自动修改本机应用配置');
    default: return unsupported(command);
  }
}
