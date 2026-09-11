"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, previewUrl, type SearchHit } from "@/lib/api";

const PAGE_SIZE = 10;

function SearchInner() {
  const sp = useSearchParams();
  const initialQ = sp.get("q") ?? "";
  const initialPage = Number(sp.get("page") ?? 1);

  const [input, setInput] = useState(initialQ);
  const [q, setQ] = useState(initialQ);
  const [page, setPage] = useState(initialPage);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!q) {
      setHits([]);
      setTotal(0);
      return;
    }
    setLoading(true);
    setErr("");
    api
      .search({ q, page })
      .then((r) => {
        setHits(r.hits);
        setTotal(r.total);
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [q, page]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const term = input.trim();
    setPage(1);
    setQ(term);
    const url = term
      ? `/search?q=${encodeURIComponent(term)}`
      : "/search";
    window.history.replaceState(null, "", url);
  }

  function go(p: number) {
    setPage(p);
    window.history.replaceState(
      null,
      "",
      `/search?q=${encodeURIComponent(q)}&page=${p}`
    );
  }

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <h1 className="page-title">卷宗全文检索</h1>
      <p className="page-sub">
        对全部已上传卷宗 PDF 的正文逐页检索；多个关键词之间为「并且」关系。
      </p>

      <div className="card">
        <form className="search-bar" onSubmit={submit}>
          <input
            type="search"
            autoFocus
            placeholder="输入关键词，如：违约金、拖欠租金、塔式起重机"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button className="btn" disabled={loading || !input.trim()}>
            {loading ? "检索中…" : "检索"}
          </button>
        </form>
      </div>

      {err && <div className="error-banner">{err}</div>}

      {q && !loading && !err && (
        <div className="page-sub">
          关键词「{q}」共命中 <b style={{ color: "var(--seal)" }}>{total}</b> 页卷宗
        </div>
      )}

      {!q ? (
        <div className="empty">
          输入关键词后在全部案件卷宗中全文检索，结果按相关度排序。
        </div>
      ) : loading ? (
        <div className="empty">检索中…</div>
      ) : total === 0 && !err ? (
        <div className="empty">未找到包含「{q}」的卷宗页面。</div>
      ) : (
        hits.map((h, i) => (
          <div key={`${h.document_id}-${h.page_no}-${i}`} className="hit">
            <div className="head">
              <Link href={`/cases/${h.case_id}`} className="case-t">
                {h.case_title}
              </Link>
              {h.case_no && <span className="tag">{h.case_no}</span>}
              {h.folder_name ? (
                <span className="tag cause">📁 {h.folder_name}</span>
              ) : (
                <span className="tag">未分类</span>
              )}
              <span className="file">
                {h.filename} · 第 {h.page_no} 页
              </span>
            </div>
            <div
              className="snippet"
              dangerouslySetInnerHTML={{ __html: h.snippet }}
            />
            <div className="row">
              <Link
                className="btn sm"
                href={previewUrl(h.case_id, h.document_id, h.page_no)}
                target="_blank"
              >
                预览原卷第 {h.page_no} 页 ↗
              </Link>
            </div>
          </div>
        ))
      )}

      {total > PAGE_SIZE && (
        <div className="pager">
          <button
            className="btn ghost sm"
            disabled={page <= 1}
            onClick={() => go(page - 1)}
          >
            上一页
          </button>
          <span className="doc-sub" style={{ alignSelf: "center" }}>
            第 {page} / {pageCount} 页
          </span>
          <button
            className="btn ghost sm"
            disabled={page >= pageCount}
            onClick={() => go(page + 1)}
          >
            下一页
          </button>
        </div>
      )}
    </>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<div className="empty">加载中…</div>}>
      <SearchInner />
    </Suspense>
  );
}
