export type SecuritySettings = {
  enabled: boolean; mode: string; scan_unicode: boolean; scan_tools: boolean; scan_network: boolean;
  scan_response: boolean; redact_secrets: boolean; block_on_critical: boolean; fail_closed: boolean;
  capabilities?: { stream_response_scan: boolean; binary_attachment_scan: boolean };
};
export type BuiltinRule = { id: string; rule_id: string; name: string; description?: string; category?: string; severity?: string; action?: string; enabled: number; pattern?: string };
export type CustomRule = { id?: string; name: string; description?: string; category?: string; severity?: string; action?: string; enabled: number; pattern: string };
export type SecurityFinding = { id: string; log_id: string; title?: string; description?: string; severity?: string; phase?: string; category?: string; location?: string; evidence_masked?: string; action?: string; created_at?: string };
export type RequestDetail = { id?: string; model?: string; status_code?: number; duration_ms?: number; created_at?: string; request_id?: string; security_action?: string; request_body?: string; response_choices?: string; [key: string]: unknown };

export const securityBase = "/api/v1/security";
export const settingKeys = ["enabled", "mode", "redact_secrets", "scan_unicode", "scan_network", "scan_tools", "scan_response", "block_on_critical", "fail_closed"] as const;
export const modes = [
  { value: "audit", label: "审计", description: "记录风险，规则指定的阻断或脱敏仍会执行。", hint: "适合先观察" },
  { value: "warn", label: "告警", description: "保留风险记录，并按每条规则的动作处置。", hint: "兼容告警模式" },
  { value: "redact", label: "脱敏", description: "高风险请求会清理可识别的凭证内容。", hint: "保护敏感信息" },
  { value: "block", label: "阻断", description: "严重风险在启用拦截后会被拒绝转发。", hint: "严格安全边界" },
];
export const categories: Record<string, string> = { credentials: "凭证密钥", path: "文件与路径", personal: "个人信息", unicode: "Unicode 字符", network: "网络风险", tools: "工具与命令", tracking: "追踪与指纹", prompt: "提示词", domain: "域名", tool: "工具名称", keyword: "关键词", custom: "自定义", secret: "敏感信息" };
export const severityLabels: Record<string, string> = { info: "提示", low: "低风险", medium: "中风险", high: "高风险", critical: "严重风险" };
export const actionLabels: Record<string, string> = { warn: "记录告警", allow: "允许", redact: "脱敏", sanitize: "脱敏", block: "阻断" };
export const severityOptions = Object.entries(severityLabels);
export const actionOptions = Object.entries(actionLabels).filter(([value], index, rows) => rows.findIndex(([, label]) => label === rows[index]![1]) === index || value === "sanitize");

export function settingsPatch(current: SecuritySettings, draft: SecuritySettings): Partial<SecuritySettings> {
  return Object.fromEntries(settingKeys.filter(key => current[key] !== draft[key]).map(key => [key, draft[key]]));
}
export function effectiveState(rule: BuiltinRule, settings: SecuritySettings | null): "enabled" | "disabled" | "category-off" | "scanner-off" | "unknown" {
  if (!rule.enabled) return "disabled";
  if (!settings) return "unknown";
  if (!settings.enabled) return "scanner-off";
  const toggle = rule.category === "unicode" ? "scan_unicode" : rule.category === "network" ? "scan_network" : rule.category === "tools" ? "scan_tools" : null;
  return toggle && !settings[toggle] ? "category-off" : "enabled";
}
export function emptyCustomRule(): CustomRule { return { name: "", description: "", category: "custom", severity: "medium", action: "warn", enabled: 1, pattern: "" }; }
export function friendlyDate(value?: string): string {
  if (!value) return "—"; const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
}
export function errorText(error: unknown): string { return error instanceof Error ? error.message : "操作失败，请重试"; }
