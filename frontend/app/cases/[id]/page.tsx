"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  formatDate,
  formatSize,
  previewUrl,
  type CaseDetail,
  type SearchHit,
} from "@/lib/api";

export default function CaseDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const caseId = Number(params.id);

  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [loadErr, setLoadErr] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadErr, setUploadErr] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const [kw, setKw] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [hitTotal, setHitTotal] = useState(0);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);

  const load = useCallback(() => {
    api
      .getCase(caseId)
      .then((d) => {
        setDetail(d);
        setLoadErr("");
      })
      .catch((e) => setLoadErr(e.message));
  }, [caseId]);

  useEffect(load, [load]);

  // 有处理中的卷宗时轮询索引状态
  const processing =
    detail?.documents.some((d) => d.status === "processing") ?? false;
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [processing, load]);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploadErr("");
    for (const file of Array.from(files)) {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setUploadErr(`「${file.name}」不是 PDF 文件，已跳过。`);
        continue;
      }
      setUploading(true);
      try {
        await api.uploadPdf(caseId, file);
        load();
      } catch (e) {
        setUploadErr((e as Error).message);
      } finally {
        setUploading(false);
      }
    }
  }

  async function doSearch(e?: React.FormEvent) {
    e?.preventDefault();
    if (!kw.trim()) return;
    setSearching(true);
    setSearched(true);
    try {
      const r = await api.search({ q: kw.trim(), caseId });
      setHits(r.hits);
      setHitTotal(r.total);
    } catch (e) {
      setUploadErr((e as Error).message);
    } finally {
      setSearching(false);
    }
  }

  if (loadErr)
    return <div className="error-banner">加载失败：{loadErr}</div>;
  if (!detail) return <div className="empty">加载中…</div>;

  return (
    <>
      <div className="row" style={{ marginBottom: 6 }}>
        <Link href="/" className="btn ghost sm">← 案件列表</Link>
      </div>
      <h1 className="page-title">{detail.title}</h1>
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
          <div className="k">立案时间</div>
          <div className="v">{formatDate(detail.created_at)}</div>
          {detail.remark && (
            <>
              <div className="k">备注</div>
              <div className="v">{detail.remark}</div>
            </>
          )}
        </div>
      </div>

      <div className="card">
        <h2>卷宗材料（{detail.documents.length}）</h2>

        <div
          className={`dropzone ${dragOver ? "drag" : ""}`}
          onClick={() => fileInput.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            handleFiles(e.dataTransfer.files);
          }}
        >
          <div className="big">
            {uploading ? "正在上传…" : "点击选择或拖拽 PDF 卷宗到此处"}
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
        {uploadErr && (
          <div className="error-banner" style={{ marginTop: 12 }}>
            {uploadErr}
          </div>
        )}

        {detail.documents.length === 0 ? (
          <div className="empty">尚未上传卷宗。</div>
        ) : (
          detail.documents.map((d) => (
            <div key={d.id} className="doc-row">
              <span className="doc-icon">📄</span>
              <div style={{ flex: 1 }}>
                <div className="doc-name">{d.filename}</div>
                <div className="doc-sub">
                  {formatSize(d.size_bytes)} ·{" "}
                  {d.status === "indexed"
                    ? `已索引 ${d.page_count} 页 · ${formatDate(d.uploaded_at)}`
                    : d.status === "failed"
                    ? `索引失败：${d.error}`
                    : "正在抽取文本、建立索引…"}
                </div>
              </div>
              {d.status === "indexed" && (
                <>
                  <span className="tag ok">可检索</span>
                  <Link
                    className="btn sm"
                    href={`/cases/${caseId}/documents/${d.id}/preview`}
                  >
                    预览
                  </Link>
                  <a
                    className="btn sm ghost"
                    href={`/api/cases/${caseId}/documents/${d.id}/download`}
                  >
                    下载
                  </a>
                </>
              )}
              {d.status === "processing" && (
                <span className="tag warn">处理中</span>
              )}
              {d.status === "failed" && (
                <span className="tag err">失败</span>
              )}
            </div>
          ))
        )}
      </div>

      <div className="card">
        <h2>本案卷宗检索</h2>
        <form className="search-bar" onSubmit={doSearch}>
          <input
            type="search"
            placeholder="在本案卷宗中检索关键词，如：违约金、拖欠租金"
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
              <div className="empty">本案卷宗中未找到「{kw}」相关内容。</div>
            ) : (
              <>
                <div className="page-sub" style={{ marginBottom: 10 }}>
                  命中 {hitTotal} 页
                </div>
                {hits.map((h, i) => (
                  <div key={i} className="hit">
                    <div className="head">
                      <span className="file">{h.filename}</span>
                      <span className="tag">第 {h.page_no} 页</span>
                    </div>
                    <div
                      className="snippet"
                      dangerouslySetInnerHTML={{ __html: h.snippet }}
                    />
                    <Link
                      className="btn sm ghost"
                      href={previewUrl(caseId, h.document_id, h.page_no)}
                      target="_blank"
                    >
                      打开该页 ↗
                    </Link>
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </div>
    </>
  );
}
