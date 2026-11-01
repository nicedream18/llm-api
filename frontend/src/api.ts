export type ApiEnvelope<T> = { code: string; info: string; data: T };

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  const payload = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok) throw new Error(payload.info || `HTTP ${response.status}`);
  return payload.data;
}

export const get = <T>(path: string) => api<T>(path);
