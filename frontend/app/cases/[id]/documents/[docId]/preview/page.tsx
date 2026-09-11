"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, previewUrl, type CaseDetail } from "@/lib/api";

export default function PreviewPage({
  params,
}: {
  params: { id: string; docId: string };
}) {
  const caseId = params.id;
  const docId = params.docId;
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .getCase(Number(caseId))
      .then(setDetail)
      .catch((e) => setErr(e.message));
  }, [caseId]);

  const doc = detail?.documents.find((d) => String(d.id) === docId);

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <Link href={`/cases/${caseId}`} className="btn ghost sm">
          ← 返回案件
        </Link>
        <Link href="/search" className="btn ghost sm">
          全文检索
        </Link>
        <div className="spacer" />
        <strong>{doc?.filename ?? "卷宗预览"}</strong>
        {doc && <span className="tag">{doc.page_count} 页</span>}
        <a
          className="btn sm ghost"
          href={`/api/cases/${caseId}/documents/${docId}/download`}
        >
          下载
        </a>
      </div>
      {err ? (
        <div className="error-banner">{err}</div>
      ) : (
        // #page=N 由 previewUrl 生成；浏览器内置 PDF 查看器据此定位页码
        <iframe
          className="pdf-frame"
          title="卷宗预览"
          src={previewUrl(Number(caseId), Number(docId))}
        />
      )}
    </>
  );
}
