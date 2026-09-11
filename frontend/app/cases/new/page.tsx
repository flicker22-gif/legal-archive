"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  canManage,
  canSetSecurity,
  getRole,
  LEVEL_LABELS,
  type Role,
  type SecurityLevel,
} from "@/lib/rbac";

const EMPTY = {
  case_no: "",
  title: "",
  cause: "",
  parties: "",
  lawyer: "",
  remark: "",
};

export default function NewCasePage() {
  const router = useRouter();
  const [form, setForm] = useState(EMPTY);
  const [level, setLevel] = useState<SecurityLevel>("normal");
  const [role, setRole] = useState<Role>("secretary");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    const r = getRole();
    setRole(r);
    if (!canManage(r)) {
      setErr("当前角色（承办律师）无权录入案件，请切换为行政秘书或合伙人。");
    }
  }, []);

  const set = (k: keyof typeof EMPTY) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    if (!form.title.trim() || !form.parties.trim() || !form.lawyer.trim()) {
      setErr("案件名称、当事人、承办律师为必填项。");
      return;
    }
    setSaving(true);
    try {
      const c = await api.createCase({
        case_no: form.case_no || null,
        title: form.title.trim(),
        cause: form.cause || null,
        parties: form.parties.trim(),
        lawyer: form.lawyer.trim(),
        remark: form.remark || null,
        security_level: level,
      });
      router.push(`/cases/${c.id}`);
    } catch (e) {
      setErr((e as Error).message);
      setSaving(false);
    }
  }

  return (
    <>
      <h1 className="page-title">录入案件</h1>
      <p className="page-sub">登记案件基本信息，保存后可在案件详情页上传卷宗 PDF。</p>

      <form className="card" onSubmit={submit}>
        {err && <div className="error-banner">{err}</div>}

        <label className="field">
          <span className="lbl">案件名称<span className="req">*</span></span>
          <input type="text" value={form.title} onChange={set("title")}
            placeholder="例：张伟诉李伟房屋租赁合同纠纷案" />
        </label>

        <label className="field">
          <span className="lbl">案号</span>
          <input type="text" value={form.case_no} onChange={set("case_no")}
            placeholder="例：(2026)京0105民初1234号" />
        </label>

        <div className="row" style={{ gap: 16 }}>
          <label className="field" style={{ flex: 1 }}>
            <span className="lbl">案由</span>
            <input type="text" value={form.cause} onChange={set("cause")}
              placeholder="例：房屋租赁合同纠纷" />
          </label>
          {canSetSecurity(role) && (
            <label className="field" style={{ flex: "0 0 180px" }}>
              <span className="lbl">保密级别</span>
              <select
                value={level}
                onChange={(e) => setLevel(e.target.value as SecurityLevel)}
              >
                <option value="normal">{LEVEL_LABELS.normal}</option>
                <option value="secret">{LEVEL_LABELS.secret}（律师不可下载）</option>
                <option value="confidential">
                  {LEVEL_LABELS.confidential}（仅合伙人可看）
                </option>
              </select>
            </label>
          )}
        </div>

        <label className="field">
          <span className="lbl">当事人<span className="req">*</span></span>
          <textarea value={form.parties} onChange={set("parties")}
            placeholder={"原告：张伟\n被告：李伟"} />
          <div className="hint">多名当事人请换行填写。</div>
        </label>

        <label className="field">
          <span className="lbl">承办律师<span className="req">*</span></span>
          <input type="text" value={form.lawyer} onChange={set("lawyer")}
            placeholder="例：王律师" />
        </label>

        <label className="field">
          <span className="lbl">备注</span>
          <textarea value={form.remark} onChange={set("remark")}
            placeholder="案情摘要、进展等（可选）" />
        </label>

        <div className="row">
          <button className="btn" type="submit"
            disabled={saving || !canManage(role)}>
            {saving ? "保存中…" : "保存案件"}
          </button>
          <button type="button" className="btn ghost"
            onClick={() => router.back()}>
            返回
          </button>
        </div>
      </form>
    </>
  );
}

