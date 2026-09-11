// 后端 API 类型与请求封装
export interface CaseItem {
  id: number;
  case_no: string | null;
  title: string;
  cause: string | null;
  parties: string;
  lawyer: string;
  remark: string | null;
  created_at: string;
}

export interface DocumentItem {
  id: number;
  case_id: number;
  filename: string;
  page_count: number;
  size_bytes: number;
  status: "processing" | "indexed" | "failed";
  error: string | null;
  uploaded_at: string;
  indexed_at: string | null;
}

export interface CaseDetail extends CaseItem {
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
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
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
  search: (params: { q: string; caseId?: number; page?: number }) => {
    const sp = new URLSearchParams({
      q: params.q,
      page: String(params.page ?? 1),
    });
    if (params.caseId) sp.set("case_id", String(params.caseId));
    return request<SearchResponse>(`/api/search?${sp.toString()}`);
  },
  uploadPdf: (caseId: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`/api/cases/${caseId}/documents`, {
      method: "POST",
      body: fd,
    }).then(async (r) => {
      if (!r.ok) {
        const b = await r.json().catch(() => ({}));
        throw new Error(b.detail || "上传失败");
      }
      return r.json() as Promise<DocumentItem>;
    });
  },
  deleteDocument: (caseId: number, docId: number) =>
    request<void>(`/api/cases/${caseId}/documents/${docId}`, {
      method: "DELETE",
    }),
  documentStatus: (caseId: number, docId: number) =>
    request<DocumentItem>(
      `/api/cases/${caseId}/documents/${docId}/status`
    ),
};

export function previewUrl(caseId: number, docId: number, page?: number) {
  const hash = page ? `#page=${page}` : "";
  return `/api/cases/${caseId}/documents/${docId}/preview${hash}`;
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
