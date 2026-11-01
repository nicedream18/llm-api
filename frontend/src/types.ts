export type Dashboard = { total_requests: number; total_tokens: number; total_errors: number; avg_duration_ms: number; active_channels: number; active_api_keys: number; health_score: number; health_badge: string };
export type Channel = { id: string; name: string; type: string; status: number; models: string[]; api_keys?: unknown[] };
export type Provider = { id: string; provider: string; name: string; status: string; priority: number; models: string[] };
export type SoftwareTool = { id: string; name: string; description: string; risk_level: string; enabled: number };
