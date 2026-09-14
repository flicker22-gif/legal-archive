// 后端 API 类型与请求封装
import { getRole, type Role, type SecurityLevel } from "./rbac";

export type { Role, SecurityLevel };

export interface FolderItem {
  id: number;
  case_id: number;
  name: string;
  position: number;
  doc_count: number;
}

export interface CaseItem {
  id: number;
  case_no: string | null;
  title: string;
  cause: string | null;
  parties: string;
  lawyer: string;
  remark: string | null;
  security_level: SecurityLevel;
  created_at: string;
}

export interface DocumentItem {
  id: number;
  case_id: number;
  folder_id: number | null;
  folder_name: string | null;
  filename: string;
  page_count: number;
  size_bytes: number;
  status: "queued" | "processing" | "indexed" | "failed";
  error: string | null;
  retry_count: number;
  uploaded_at: string;
  indexed_at: string | null;
}

// 上传响应：deduplicated=true 表示同案件下已存在相同内容的卷宗，未重复落盘
export interface UploadResult extends DocumentItem {
  deduplicated: boolean;
}

export interface CaseDetail extends CaseItem {
  folders: FolderItem[];
  documents: DocumentItem[];
}

export interface CaseListResponse {
  total: number;
  page: number;
  page_size: number;
  items: CaseItem[];
}

export interface SearchHit {
  document_id: number;
  case_id: number;
  case_no: string | null;
  case_title: string;
  security_level: SecurityLevel;
  folder_id: number | null;
  folder_name: string | null;
  filename: string;
  page_no: number;
  snippet: string;
  rank: number;
}

export interface SearchResponse {
  q: string;
  page: number;
  page_size: number;
  total: number;
  hits: SearchHit[];
}

export interface CaseInput {
  case_no?: string | null;
  title: string;
  cause?: string | null;
  parties: string;
  lawyer: string;
  remark?: string | null;
  security_level?: SecurityLevel;
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  return { "X-User-Role": getRole(), ...extra };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = authHeaders();
  if (init?.body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    const err = new Error(detail);
    (err as Error & { status?: number }).status = res.status;
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  listCases: (q = "", page = 1) =>
    request<CaseListResponse>(
      `/api/cases?page=${page}&q=${encodeURIComponent(q)}`
    ),
  getCase: (id: number) => request<CaseDetail>(`/api/cases/${id}`),
  createCase: (data: CaseInput) =>
    request<CaseItem>(`/api/cases`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  deleteCase: (id: number) =>
    request<void>(`/api/cases/${id}`, { method: "DELETE" }),
  setSecurityLevel: (caseId: number, level: SecurityLevel) =>
    request<CaseItem>(`/api/cases/${caseId}/security-level`, {
      method: "PATCH",
      body: JSON.stringify({ security_level: level }),
    }),

  // ---- 目录 ----
  createFolder: (caseId: number, name: string) =>
    request<FolderItem>(`/api/cases/${caseId}/folders`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  renameFolder: (caseId: number, folderId: number, name: string) =>
    request<FolderItem>(`/api/cases/${caseId}/folders/${folderId}`, {
      method: "PUT",
      body: JSON.stringify({ name }),
    }),
  deleteFolder: (caseId: number, folderId: number) =>
    request<void>(`/api/cases/${caseId}/folders/${folderId}`, {
      method: "DELETE",
    }),
  reorderFolders: (caseId: number, folderIds: number[]) =>
    request<FolderItem[]>(`/api/cases/${caseId}/folders/reorder`, {
      method: "POST",
      body: JSON.stringify(folderIds),
    }),

  search: (params: {
    q: string;
    caseId?: number;
    folderId?: number | null;
    page?: number;
  }) => {
    const sp = new URLSearchParams({
      q: params.q,
      page: String(params.page ?? 1),
    });
    if (params.caseId) sp.set("case_id", String(params.caseId));
    if (params.folderId !== undefined && params.folderId !== null)
      sp.set("folder_id", String(params.folderId));
    return request<SearchResponse>(`/api/search?${sp.toString()}`);
  },

  uploadPdf: (caseId: number, file: File, folderId?: number | null) => {
    const fd = new FormData();
    fd.append("file", file);
    if (folderId !== undefined && folderId !== null)
      fd.append("folder_id", String(folderId));
    return fetch(`/api/cases/${caseId}/documents`, {
      method: "POST",
      body: fd,
      headers: authHeaders(),
    }).then(async (r) => {
      if (!r.ok) {
        const b = await r.json().catch(() => ({}));
        throw new Error(b.detail || "上传失败");
      }
      return r.json() as Promise<UploadResult>;
    });
  },
  retryDocument: (caseId: number, docId: number) =>
    request<DocumentItem>(`/api/cases/${caseId}/documents/${docId}/retry`, {
      method: "POST",
    }),
  moveDocument: (
    caseId: number,
    docId: number,
    folderId: number | null
  ) =>
    request<DocumentItem>(
      `/api/cases/${caseId}/documents/${docId}/move`,
      {
        method: "PATCH",
        body: JSON.stringify({ folder_id: folderId }),
      }
    ),
  deleteDocument: (caseId: number, docId: number) =>
    request<void>(`/api/cases/${caseId}/documents/${docId}`, {
      method: "DELETE",
    }),
  documentStatus: (caseId: number, docId: number) =>
    request<DocumentItem>(
      `/api/cases/${caseId}/documents/${docId}/status`
    ),
};

// PDF 由浏览器 iframe / 新标签直接加载，无法带自定义头，用 ?role= 兜底
export function previewUrl(
  caseId: number,
  docId: number,
  page?: number
) {
  const role = typeof window !== "undefined" ? getRole() : "secretary";
  const hash = page ? `#page=${page}` : "";
  return `/api/cases/${caseId}/documents/${docId}/preview?role=${role}${hash}`;
}

export function downloadUrl(caseId: number, docId: number) {
  const role = typeof window !== "undefined" ? getRole() : "secretary";
  return `/api/cases/${caseId}/documents/${docId}/download?role=${role}`;
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(
    d.getHours()
  )}:${p(d.getMinutes())}`;
}
