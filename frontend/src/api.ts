export type ApiEnvelope<T> = { code: string; info: string; data: T };

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  const payload = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok) throw new Error(payload.info || `HTTP ${response.status}`);
  return payload.data;
}

export const get = <T>(path: string) => api<T>(path);
export const post = <T>(path: string, body: unknown) => api<T>(path, { method: "POST", body: JSON.stringify(body) });
export const put = <T>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });
export async function upload<T>(path: string, file: File): Promise<T> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(path, { method: "POST", credentials: "include", body, headers: { Accept: "application/json" } });
  const payload = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok) throw new Error(payload.info || `HTTP ${response.status}`);
  return payload.data;
}

export async function uploadRaw<T>(path: string, file: File): Promise<T> {
  const response = await fetch(path, {
    method: "POST", credentials: "include", body: file,
    headers: { "Content-Type": file.type || "application/octet-stream", Accept: "application/json" },
  });
  const payload = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok) throw new Error(payload.info || `HTTP ${response.status}`);
  return payload.data;
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try { message = ((await response.json()) as ApiEnvelope<unknown>).info || message; } catch { /* Keep the HTTP status. */ }
    throw new Error(message);
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1_000);
}
