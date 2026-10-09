import type { components } from "@shared/api";

export type Project = components["schemas"]["ProjectOut"];
export type Decision = components["schemas"]["DecisionOut"];
export type Word = components["schemas"]["WordOut"];
export type ExportFile = components["schemas"]["ExportOut"];
export type ProjectCreated = components["schemas"]["ProjectCreated"];
export type DecisionPatch = components["schemas"]["DecisionPatch"];

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // JSON이 아닌 오류 응답은 statusText 그대로
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listProjects: () => call<Project[]>("/projects"),
  getProject: (id: string) => call<Project>(`/projects/${id}`),
  createProject: (file: File) =>
    call<ProjectCreated>("/projects", {
      method: "POST",
      body: JSON.stringify({
        title: file.name.replace(/\.[^.]+$/, ""),
        filename: file.name,
        content_type: file.type || "video/quicktime",
        size_bytes: file.size,
      }),
    }),
  analyze: (id: string) => call<Project>(`/projects/${id}/analyze`, { method: "POST" }),
  transcript: (id: string) => call<Word[]>(`/projects/${id}/transcript`),
  decisions: (id: string) => call<Decision[]>(`/projects/${id}/decisions`),
  patchDecision: (id: string, did: string, body: DecisionPatch) =>
    call<Decision>(`/projects/${id}/decisions/${did}`, { method: "PATCH", body: JSON.stringify(body) }),
  addDecision: (id: string, start_ms: number, end_ms: number) =>
    call<Decision>(`/projects/${id}/decisions`, {
      method: "POST",
      body: JSON.stringify({ start_ms, end_ms }),
    }),
  render: (id: string) => call<Project>(`/projects/${id}/render`, { method: "POST" }),
  exports: (id: string) => call<ExportFile[]>(`/projects/${id}/exports`),
};

/** presigned URL로 S3에 직접 업로드. fetch는 업로드 진행률을 못 주므로 XHR. */
export function uploadToS3(
  url: string,
  headers: Record<string, string>,
  file: File,
  onProgress: (ratio: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(`업로드 실패 (${xhr.status})`)));
    xhr.onerror = () => reject(new Error("업로드 중 네트워크 오류"));
    xhr.send(file);
  });
}
