"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type CaseItem } from "@/lib/api";

function CaseListInner() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<CaseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    const t = setTimeout(() => {
      setLoading(true);
      api
        .listCases(q)
        .then((d) => {
          setItems(d.items);
          setTotal(d.total);
          setErr("");
        })
        .catch((e) => setErr(e.message))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    router.replace(q ? `/?q=${encodeURIComponent(q)}` : "/");
  }

  return (
    <>
      <h1 className="page-title">案件归档</h1>
      <p className="page-sub">按案件登记当事人、案由、承办律师，并上传卷宗 PDF。</p>

      {err && <div className="error-banner">{err}</div>}

      <div className="card">
        <form className="search-bar" onSubmit={onSubmit}>
          <input
            type="search"
            placeholder="筛选案号 / 案件名称 / 当事人 / 承办律师 / 案由"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <Link href="/cases/new" className="btn">
            ＋ 录入案件
          </Link>
        </form>
      </div>

      <div className="stat-row">
        <div className="stat">
          <div className="n">{total}</div>
          <div className="l">在档案件{q ? "（筛选结果）" : ""}</div>
        </div>
      </div>

      {loading ? (
        <div className="empty">加载中…</div>
      ) : items.length === 0 ? (
        <div className="empty">没有符合条件的案件，点击右上角「录入案件」新建。</div>
      ) : (
        items.map((c) => (
          <Link key={c.id} href={`/cases/${c.id}`} className="case-item">
            <div className="t">{c.title}</div>
            <div className="meta">
              {c.case_no && <span>案号：{c.case_no}</span>}
              {c.cause && (
                <span className="tag cause">{c.cause}</span>
              )}
              <span>当事人：{c.parties.replace(/\n/g, "、")}</span>
              <span className="tag lawyer">承办：{c.lawyer}</span>
            </div>
          </Link>
        ))
      )}
    </>
  );
}

export default function CaseListPage() {
  return (
    <Suspense>
      <CaseListInner />
    </Suspense>
  );
}
