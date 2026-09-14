"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  downloadUrl,
  formatDate,
  formatSize,
  previewUrl,
  type CaseDetail,
  type DocumentItem,
  type FolderItem,
  type SearchHit,
} from "@/lib/api";
import SecurityBadge from "@/components/SecurityBadge";
import {
  canDeleteCase,
  canDownload,
  canManage,
  canSetSecurity,
  canView,
  getRole,
  LEVEL_LABELS,
  type Role,
  type SecurityLevel,
} from "@/lib/rbac";

type Selection = "all" | "unfiled" | number;

export default function CaseDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const caseId = Number(params.id);

  const [role, setRole] = useState<Role>("secretary");
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [forbidden, setForbidden] = useState("");
  const [notFound, setNotFound] = useState(false);
  const [selection, setSelection] = useState<Selection>("all");

  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState("");
  const [noticeKind, setNoticeKind] = useState<"ok" | "err">("ok");
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const [newFolderName, setNewFolderName] = useState("");
  const [showFolderInput, setShowFolderInput] = useState(false);
  const [editingFolder, setEditingFolder] = useState<number | null>(null);
  const [editName, setEditName] = useState("");

  const [kw, setKw] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [hitTotal, setHitTotal] = useState(0);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);

  const flash = (msg: string, kind: "ok" | "err" = "ok") => {
    setNotice(msg);
    setNoticeKind(kind);
  };

  const load = useCallback(() => {
    api
      .getCase(caseId)
      .then((d) => {
        setDetail(d);
        setForbidden("");
        setNotFound(false);
      })
      .catch((e: Error & { status?: number }) => {
        if (e.status === 403) setForbidden(e.message);
        else if (e.status === 404) setNotFound(true);
      });
  }, [caseId]);

  useEffect(() => {
    setRole(getRole());
    load();
  }, [load]);

  const processing =
    detail?.documents.some(
      (d) => d.status === "processing" || d.status === "queued"
    ) ?? false;
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [processing, load]);

  if (notFound)
    return <div className="error-banner">案件不存在。</div>;
  if (forbidden)
    return (
      <div className="forbidden-panel">
        <div className="big">🔒 无权访问该案件</div>
        <div>{forbidden}</div>
        <div style={{ marginTop: 16 }}>
          <Link href="/" className="btn sm ghost">返回案件列表</Link>
        </div>
      </div>
    );
  if (!detail) return <div className="empty">加载中…</div>;

  const level: SecurityLevel = detail.security_level;
  const mayManage = canManage(role);
  const mayView = canView(role, level);
  const mayDownload = canDownload(role, level);

  const folders = detail.folders ?? [];
  const documents = detail.documents ?? [];
  const unfiledCount = documents.filter((d) => d.folder_id == null).length;

  const visibleDocs = documents.filter((d) => {
    if (selection === "all") return true;
    if (selection === "unfiled") return d.folder_id == null;
    return d.folder_id === selection;
  });

  const uploadTargetId = typeof selection === "number" ? selection : null;
  const uploadTargetName =
    typeof selection === "number"
      ? folders.find((f) => f.id === selection)?.name ?? "目录"
      : "未分类";

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    for (const file of Array.from(files)) {
      if (!file.name.toLowerCase().endsWith(".pdf")) continue;
      setUploading(true);
      try {
        const res = await api.uploadPdf(caseId, file, uploadTargetId);
        load();
        flash(
          res.deduplicated
            ? `《${file.name}》与已上传的《${res.filename}》内容完全相同（指纹一致），未重复落盘`
            : `已上传到「${uploadTargetName}」，正在建立索引…`
        );
      } catch (e) {
        flash((e as Error).message, "err");
      } finally {
        setUploading(false);
      }
    }
  }

  async function retryDoc(doc: DocumentItem) {
    try {
      await api.retryDocument(caseId, doc.id);
      load();
      flash(`《${doc.filename}》已重新排队，正在重建索引…`);
    } catch (e) {
      flash((e as Error).message, "err");
    }
  }

  async function createFolder() {
    const name = newFolderName.trim();
    if (!name) return;
    try {
      const f = await api.createFolder(caseId, name);
      setNewFolderName("");
      setShowFolderInput(false);
      setSelection(f.id);
      load();
    } catch (e) {
      flash((e as Error).message, "err");
    }
  }

  async function saveRename(folder: FolderItem) {
    const name = editName.trim();
    setEditingFolder(null);
    if (!name || name === folder.name) return;
    try {
      await api.renameFolder(caseId, folder.id, name);
      load();
    } catch (e) {
      flash((e as Error).message, "err");
    }
  }

  async function removeFolder(folder: FolderItem) {
    const msg =
      folder.doc_count > 0
        ? `删除目录「${folder.name}」？其中 ${folder.doc_count} 份卷宗将移到「未分类」，不会删除文件。`
        : `删除空目录「${folder.name}」？`;
    if (!confirm(msg)) return;
    try {
      await api.deleteFolder(caseId, folder.id);
      if (selection === folder.id) setSelection("all");
      load();
    } catch (e) {
      flash((e as Error).message, "err");
    }
  }

  async function moveFolder(folder: FolderItem, delta: -1 | 1) {
    const ordered = [...folders].sort((a, b) => a.position - b.position);
    const i = ordered.findIndex((f) => f.id === folder.id);
    const j = i + delta;
    if (j < 0 || j >= ordered.length) return;
    [ordered[i], ordered[j]] = [ordered[j], ordered[i]];
    try {
      await api.reorderFolders(caseId, ordered.map((f) => f.id));
      load();
    } catch (e) {
      flash((e as Error).message, "err");
    }
  }

  async function moveDoc(doc: DocumentItem, folderId: number | null) {
    if (folderId === doc.folder_id) return;
    try {
      await api.moveDocument(caseId, doc.id, folderId);
      load();
    } catch (e) {
      flash((e as Error).message, "err");
    }
  }

  async function removeDoc(doc: DocumentItem) {
    if (!confirm(`确定删除卷宗《${doc.filename}》？此操作不可恢复。`)) return;
    try {
      await api.deleteDocument(caseId, doc.id);
      load();
    } catch (e) {
      flash((e as Error).message, "err");
    }
  }

  async function changeLevel(lv: SecurityLevel) {
    try {
      await api.setSecurityLevel(caseId, lv);
      load();
      flash(`保密级别已调整为「${LEVEL_LABELS[lv]}」`);
    } catch (e) {
      flash((e as Error).message, "err");
    }
  }

  async function removeCase() {
    if (!confirm(`确定删除整个案件「${detail?.title ?? ""}」及其全部卷宗？不可恢复。`)) return;
    try {
      await api.deleteCase(caseId);
      window.location.href = "/";
    } catch (e) {
      flash((e as Error).message, "err");
    }
  }

  async function doSearch(e?: React.FormEvent) {
    e?.preventDefault();
    if (!kw.trim()) return;
    setSearching(true);
    setSearched(true);
    try {
      const folderParam =
        typeof selection === "number"
          ? selection
          : selection === "unfiled"
          ? 0
          : undefined;
      const r = await api.search({
        q: kw.trim(), caseId, folderId: folderParam,
      });
      setHits(r.hits);
      setHitTotal(r.total);
      setNotice("");
    } catch (e) {
      flash((e as Error).message, "err");
    } finally {
      setSearching(false);
    }
  }

  const navItem = (key: Selection, label: string, count: number, icon = "📁") => (
    <button
      key={String(key)}
      className={`folder-nav-item ${selection === key ? "active" : ""}`}
      onClick={() => setSelection(key)}
    >
      <span className="ficon">{icon}</span>
      <span className="fname">{label}</span>
      <span className="fcount">{count}</span>
    </button>
  );

  return (
    <>
      <div className="row" style={{ marginBottom: 6 }}>
        <Link href="/" className="btn ghost sm">← 案件列表</Link>
      </div>
      <div className="row" style={{ gap: 12, marginBottom: 4, flexWrap: "wrap" }}>
        <h1 className="page-title" style={{ margin: 0 }}>{detail.title}</h1>
        <SecurityBadge level={level} size="md" />
      </div>
      <p className="page-sub">
        {detail.case_no || "未登记案号"}
        {detail.cause ? ` · ${detail.cause}` : ""}
      </p>

      <div className="card">
        <h2>案件信息</h2>
        <div className="meta-grid">
          <div className="k">当事人</div>
          <div className="v">{detail.parties}</div>
          <div className="k">承办律师</div>
          <div className="v">{detail.lawyer}</div>
          <div className="k">保密级别</div>
          <div className="v">
            {canSetSecurity(role) ? (
              <select
                className="move-select"
                style={{ width: 220 }}
                value={level}
                onChange={(e) => changeLevel(e.target.value as SecurityLevel)}
              >
                <option value="normal">普通</option>
                <option value="secret">秘密（律师可看不可下载）</option>
                <option value="confidential">机密（仅合伙人可看）</option>
              </select>
            ) : (
              <SecurityBadge level={level} size="md" />
            )}
          </div>
          <div className="k">立案时间</div>
          <div className="v">{formatDate(detail.created_at)}</div>
          {detail.remark && (
            <>
              <div className="k">备注</div>
              <div className="v">{detail.remark}</div>
            </>
          )}
        </div>
        {canDeleteCase(role) && (
          <div className="row" style={{ marginTop: 14 }}>
            <button className="btn danger sm" onClick={removeCase}>
              删除整个案件
            </button>
          </div>
        )}
      </div>

      {notice && (
        <div className={`${noticeKind === "err" ? "error" : "ok"}-banner`}>
          {notice}
        </div>
      )}

      <div className="folder-layout">
        <aside className="card folder-sidebar">
          <h2>卷宗目录</h2>
          {navItem("all", "全部材料", documents.length, "🗂")}
          {navItem("unfiled", "未分类", unfiledCount, "📎")}
          <div className="folder-sep" />
          {[...folders]
            .sort((a, b) => a.position - b.position)
            .map((f) =>
              editingFolder === f.id ? (
                <input
                  key={f.id}
                  className="folder-edit-input"
                  autoFocus
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  onBlur={() => saveRename(f)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") saveRename(f);
                    if (e.key === "Escape") setEditingFolder(null);
                  }}
                />
              ) : (
                <div
                  key={f.id}
                  className={`folder-nav-item ${selection === f.id ? "active" : ""}`}
                  onClick={() => setSelection(f.id)}
                >
                  <span className="ficon">📁</span>
                  <span className="fname" title={f.name}>{f.name}</span>
                  <span className="fcount">{f.doc_count}</span>
                  {mayManage && (
                    <span className="factions">
                      <span title="上移" onClick={(e) => { e.stopPropagation(); moveFolder(f, -1); }}>↑</span>
                      <span title="下移" onClick={(e) => { e.stopPropagation(); moveFolder(f, 1); }}>↓</span>
                      <span title="改名" onClick={(e) => {
                        e.stopPropagation();
                        setEditingFolder(f.id);
                        setEditName(f.name);
                      }}>✎</span>
                      <span title="删除" onClick={(e) => { e.stopPropagation(); removeFolder(f); }}>✕</span>
                    </span>
                  )}
                </div>
              )
            )}

          {mayManage &&
            (showFolderInput ? (
              <input
                className="folder-edit-input"
                autoFocus
                placeholder="目录名称，如：庭审笔录"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onBlur={createFolder}
                onKeyDown={(e) => {
                  if (e.key === "Enter") createFolder();
                  if (e.key === "Escape") setShowFolderInput(false);
                }}
              />
            ) : (
              <button className="folder-add" onClick={() => setShowFolderInput(true)}>
                ＋ 新建目录
              </button>
            ))}
        </aside>

        <section className="folder-main">
          <div className="card">
            <h2>
              {selection === "all"
                ? `全部卷宗（${documents.length}）`
                : selection === "unfiled"
                ? `未分类（${unfiledCount}）`
                : `${folders.find((f) => f.id === selection)?.name ?? ""}（${visibleDocs.length}）`}
            </h2>

            {mayManage ? (
              <div
                className={`dropzone ${dragOver ? "drag" : ""}`}
                onClick={() => fileInput.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  handleFiles(e.dataTransfer.files);
                }}
              >
                <div className="big">
                  {uploading
                    ? "正在上传…"
                    : `点击选择或拖拽 PDF 到此处（归入：${uploadTargetName}）`}
                </div>
                <div>支持多文件，仅限 PDF；上传后自动抽取文本并建立全文索引</div>
                <input
                  ref={fileInput}
                  type="file"
                  accept="application/pdf,.pdf"
                  multiple
                  hidden
                  onChange={(e) => {
                    handleFiles(e.target.files);
                    e.target.value = "";
                  }}
                />
              </div>
            ) : (
              <div className="ok-banner">
                当前身份「{role === "lawyer" ? "承办律师" : ""}」仅有查看权限，上传与目录整理请由行政秘书操作。
              </div>
            )}

            {visibleDocs.length === 0 ? (
              <div className="empty">该目录下暂无卷宗。</div>
            ) : (
              visibleDocs.map((d) => (
                <div key={d.id} className="doc-row">
                  <span className="doc-icon">📄</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="doc-name">{d.filename}</div>
                    <div className="doc-sub">
                      {formatSize(d.size_bytes)} ·{" "}
                      {d.status === "indexed"
                        ? `已索引 ${d.page_count} 页 · ${formatDate(d.uploaded_at)}`
                        : d.status === "failed"
                        ? `索引失败：${d.error ?? "未知原因"}${
                            d.retry_count > 0 ? `（已重试 ${d.retry_count} 次）` : ""
                          }`
                        : d.status === "queued"
                        ? `排队等待索引…${
                            d.retry_count > 0 ? `（第 ${d.retry_count} 次重试）` : ""
                          }`
                        : "正在抽取文本、建立索引…"}
                    </div>
                  </div>

                  {d.status === "queued" && <span className="tag">排队中</span>}
                  {d.status === "processing" && <span className="tag warn">处理中</span>}
                  {d.status === "failed" && <span className="tag err">失败</span>}
                  {d.status === "failed" && mayManage && (
                    <button
                      className="btn sm"
                      title="重新解析并重建索引"
                      onClick={() => retryDoc(d)}
                    >
                      重试
                    </button>
                  )}

                  {d.status === "indexed" && (
                    <>
                      {mayManage && (
                        <select
                          className="move-select"
                          title="移动到目录"
                          value={d.folder_id == null ? "" : String(d.folder_id)}
                          onChange={(e) =>
                            moveDoc(d, e.target.value === "" ? null : Number(e.target.value))
                          }
                        >
                          <option value="">未分类</option>
                          {folders.map((f) => (
                            <option key={f.id} value={f.id}>{f.name}</option>
                          ))}
                        </select>
                      )}
                      {mayView ? (
                        <Link className="btn sm"
                          href={`/cases/${caseId}/documents/${d.id}/preview`}>
                          预览
                        </Link>
                      ) : (
                        <span className="tag err" title="按保密级别，当前角色无权查看正文">
                          🔒 内容受限
                        </span>
                      )}
                      {mayView && mayDownload && (
                        <a className="btn sm ghost"
                          href={downloadUrl(caseId, d.id)}>
                          下载
                        </a>
                      )}
                      {mayView && !mayDownload && (
                        <span className="tag" title="秘密级材料，律师可查看但不可下载">
                          禁止下载
                        </span>
                      )}
                      {mayManage && (
                        <button className="btn sm danger" onClick={() => removeDoc(d)}>
                          删除
                        </button>
                      )}
                    </>
                  )}
                </div>
              ))
            )}
          </div>

          {mayView ? (
            <div className="card">
              <h2>卷宗检索</h2>
              <form className="search-bar" onSubmit={doSearch}>
                <input
                  type="search"
                  placeholder={
                    selection === "all"
                      ? "在本案全部卷宗中检索，如：违约金、拖欠租金"
                      : selection === "unfiled"
                      ? "在未分类卷宗中检索"
                      : `在「${folders.find((f) => f.id === selection)?.name}」目录中检索`
                  }
                  value={kw}
                  onChange={(e) => setKw(e.target.value)}
                />
                <button className="btn" disabled={searching || !kw.trim()}>
                  {searching ? "检索中…" : "检索"}
                </button>
              </form>

              {searched && (
                <div style={{ marginTop: 16 }}>
                  {hitTotal === 0 ? (
                    <div className="empty">未找到「{kw}」相关内容。</div>
                  ) : (
                    <>
                      <div className="page-sub" style={{ marginBottom: 10 }}>
                        命中 {hitTotal} 页
                      </div>
                      {hits.map((h, i) => (
                        <div key={i} className="hit">
                          <div className="head">
                            <span className="file">{h.filename}</span>
                            {h.folder_name && (
                              <span className="tag cause">{h.folder_name}</span>
                            )}
                            <span className="tag">第 {h.page_no} 页</span>
                          </div>
                          <div className="snippet"
                            dangerouslySetInnerHTML={{ __html: h.snippet }} />
                          <Link className="btn sm ghost"
                            href={previewUrl(caseId, h.document_id, h.page_no)}
                            target="_blank">
                            打开该页 ↗
                          </Link>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="forbidden-panel">
              <div className="big">🔒 卷宗内容不可检索</div>
              <div>
                该案件为「{LEVEL_LABELS[level]}」级，当前身份无权查看卷宗正文与全文检索结果。
                如需查阅，请联系合伙人调整权限。
              </div>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
