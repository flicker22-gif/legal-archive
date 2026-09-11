"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, downloadUrl, previewUrl, type CaseDetail } from "@/lib/api";
import {
  canDownload,
  canView,
  getRole,
  LEVEL_LABELS,
  type Role,
} from "@/lib/rbac";
import SecurityBadge from "@/components/SecurityBadge";

export default function PreviewPage({
  params,
}: {
  params: { id: string; docId: string };
}) {
  const caseId = params.id;
  const docId = params.docId;
  const [role, setRole] = useState<Role>("secretary");
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [denied, setDenied] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    const r = getRole();
    setRole(r);
    api
      .getCase(Number(caseId))
      .then((d) => {
        if (!canView(r, d.security_level)) {
          setDenied(true);
          return;
        }
        setDetail(d);
      })
      .catch((e: Error & { status?: number }) => {
        if (e.status === 403) setDenied(true);
        else setErr(e.message);
      });
  }, [caseId]);

  if (err) return <div className="error-banner">{err}</div>;
  if (denied)
    return (
      <div className="forbidden-panel">
        <div className="big">🔒 无权预览该卷宗</div>
        <div>该案件保密级别限制了当前身份的查看权限，请联系合伙人。</div>
        <div style={{ marginTop: 16 }}>
          <Link href={`/cases/${caseId}`} className="btn sm ghost">
            返回案件
          </Link>
        </div>
      </div>
    );
  if (!detail) return <div className="empty">加载中…</div>;

  const doc = detail.documents.find((d) => String(d.id) === docId);
  const mayDownload = canDownload(role, detail.security_level);

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <Link href={`/cases/${caseId}`} className="btn ghost sm">← 返回案件</Link>
        <Link href="/search" className="btn ghost sm">全文检索</Link>
        <div className="spacer" />
        <strong>{doc?.filename ?? "卷宗预览"}</strong>
        <SecurityBadge level={detail.security_level} />
        {doc && <span className="tag">{doc.page_count} 页</span>}
        {mayDownload ? (
          <a className="btn sm ghost" href={downloadUrl(Number(caseId), Number(docId))}>
            下载
          </a>
        ) : (
          <span className="tag err" title={`${LEVEL_LABELS[detail.security_level]}级材料禁止下载`}>
            禁止下载
          </span>
        )}
      </div>
      {/* #page=N 由 previewUrl 生成；?role= 携带当前身份；浏览器内置 PDF 查看器据此定位页码 */}
      <iframe
        className="pdf-frame"
        title="卷宗预览"
        src={previewUrl(Number(caseId), Number(docId))}
      />
    </>
  );
}
