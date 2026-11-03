export type ApiEnvelope<T> = { code: string; info: string; data: T };

async function read<T>(response: Response, path: string): Promise<T> {
  if (response.status === 401 && path.startsWith("/api/v1/") && !path.startsWith("/api/v1/auth/")) window.dispatchEvent(new Event("admin-session-expired"));
  const payload = await response.json().catch(() => null) as (ApiEnvelope<T> & { detail?: unknown }) | null;
  if (!response.ok) {
    const detail = typeof payload?.detail === "string" ? payload.detail : Array.isArray(payload?.detail) ? payload.detail.map(item => `${item.loc?.join(".") || "输入"}: ${item.msg || "无效"}`).join("；") : "";
    throw new Error(payload?.info || detail || `HTTP ${response.status}`);
  }
  if (!payload) throw new Error("服务返回了无效的 JSON 响应");
  return payload.data;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  return read<T>(response, path);
}

export const get = <T>(path: string, init?: RequestInit) => api<T>(path, init);
export const post = <T>(path: string, body: unknown) => api<T>(path, { method: "POST", body: JSON.stringify(body) });
export const put = <T>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });
export async function askWiki<T>(projectId: string, request: { question: string; model: string; top_k: number }): Promise<T> {
  return post<T>(`/api/v1/wiki/projects/${encodeURIComponent(projectId)}/ask`, request);
}
export async function upload<T>(path: string, file: File): Promise<T> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(path, { method: "POST", credentials: "include", body, headers: { Accept: "application/json" } });
  return read<T>(response, path);
}

export function uploadWithProgress<T>(path: string, file: File, onProgress: (percent: number | null) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const body = new FormData();
    body.append("file", file);
    xhr.open("POST", path);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = event => onProgress(event.lengthComputable && event.total > 0 ? Math.round(event.loaded * 100 / event.total) : null);
    xhr.onerror = () => reject(new Error("网络连接失败，请检查连接后重试。"));
    xhr.onabort = () => reject(new Error("上传已取消。"));
    xhr.onload = async () => {
      try {
        const response = new Response(xhr.responseText, { status: xhr.status });
        resolve(await read<T>(response, path));
      } catch (error) { reject(error); }
    };
    xhr.send(body);
  });
}

export async function uploadRaw<T>(path: string, file: File): Promise<T> {
  const response = await fetch(path, {
    method: "POST", credentials: "include", body: file,
    headers: { "Content-Type": file.type || "application/octet-stream", Accept: "application/json" },
  });
  return read<T>(response, path);
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) {
    await read<never>(response, path);
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1_000);
}
