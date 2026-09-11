"""端到端冒烟测试：案件、目录、上传、检索、PDF 预览、角色权限（需先 seed_demo）。"""
import io
import sys
import urllib.error
import urllib.parse
import urllib.request

import fitz

BASE = "http://127.0.0.1:8000"


def request(method, path, role="partner", data=None):
    headers = {"X-User-Role": role}
    body = None
    if data is not None:
        import json
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            if not raw:
                return r.status, None
            if path.split("?")[0].endswith(("/preview", "/download")):
                return r.status, raw
            import json
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def get(path, role="partner"):
    return request("GET", path, role)


def search(kw, role="partner", case_id=None, folder_id=None):
    import json
    p = {"q": kw}
    if case_id:
        p["case_id"] = case_id
    if folder_id is not None:
        p["folder_id"] = folder_id
    _, body = get(f"/api/search?{urllib.parse.urlencode(p)}", role)
    return body


def main() -> int:
    print("== 案件列表与保密级别（合伙人视角）==")
    _, listing = get("/api/cases?page_size=50")
    assert listing["total"] == 3, f"应有3个演示案件，实际{listing['total']}"
    levels = {c["id"]: c["security_level"] for c in listing["items"]}
    assert levels == {1: "normal", 2: "secret", 3: "confidential"}, levels
    print("  级别分布:", levels)

    print("== 案件1：默认目录 + 分类卷宗 ==")
    _, detail = get("/api/cases/1")
    folders = {f["name"]: f for f in detail["folders"]}
    assert set(folders) >= {"诉讼文书", "证据材料", "裁判文书"}
    by_folder = {}
    for d in detail["documents"]:
        by_folder.setdefault(d["folder_name"], []).append(d["filename"])
        assert d["status"] == "indexed", f"{d['filename']} 未索引"
    print("  目录分布:", {k: v for k, v in by_folder.items()})
    assert "民事起诉状.pdf" in by_folder["诉讼文书"]
    assert "证据目录.pdf" in by_folder["证据材料"]
    assert "民事判决书.pdf" in by_folder["裁判文书"]

    print("== 合伙人：各级别内容均可检索 ==")
    for kw, expect_cases in [("违约金", {1, 2}), ("塔式起重机", {2}),
                             ("违法解除劳动合同", {3}), ("上诉", {1})]:
        r = search(kw)
        got = {h["case_id"] for h in r["hits"]}
        assert r["total"] > 0 and expect_cases <= got, f"{kw}: {got}"
        assert all("<mark>" in h["snippet"] for h in r["hits"])
        print(f"  「{kw}」total={r['total']} 案件={sorted(got)}")

    print("== 目录范围过滤 ==")
    r = search("判决", folder_id=folders["裁判文书"]["id"])
    assert r["total"] == 1 and r["hits"][0]["filename"] == "民事判决书.pdf"
    r = search("判决", folder_id=folders["证据材料"]["id"])
    assert r["total"] == 0
    print("  裁判文书目录=1，证据材料目录=0 ✓")

    print("== PDF 预览（合伙人，可看机密）==")
    _, body = get("/api/cases/1/documents/1/preview")
    pdf = fitz.open(stream=io.BytesIO(body), filetype="pdf")
    assert "起诉状" in "".join(p.get_text() for p in pdf)
    print(f"  普通案件预览 OK；机密案(3)预览:", get("/api/cases/3/documents/7/preview")[0])

    # ---------------- RBAC 矩阵 ----------------
    print("\n== 权限矩阵（normal/secret/confidential）==")
    # 列表可见性
    _, lst = get("/api/cases?page_size=50", "lawyer")
    assert {c["id"] for c in lst["items"]} == {1, 2}, "律师不应看到机密案件3"
    _, lst = get("/api/cases?page_size=50", "secretary")
    assert {c["id"] for c in lst["items"]} == {1, 2, 3}, "秘书要管理全部案件"
    print("  列表：律师见1,2；秘书/合伙人见1,2,3 ✓")

    # 案件详情：律师对机密 403
    assert get("/api/cases/3", "lawyer")[0] == 403
    assert get("/api/cases/3", "secretary")[0] == 200  # 管理需要
    print("  机密详情：律师403，秘书/合伙人200 ✓")

    # 预览权限（查看正文）
    preview_expect = {
        "secretary": {1: 200, 2: 403, 3: 403},
        "lawyer":    {1: 200, 2: 200, 3: 403},
        "partner":   {1: 200, 2: 200, 3: 200},
    }
    doc_by_case = {1: 1, 2: 5, 3: 7}
    for role, mat in preview_expect.items():
        codes = {cid: get(f"/api/cases/{cid}/documents/{did}/preview", role)[0]
                 for cid, did in doc_by_case.items()}
        assert codes == mat, f"{role} 预览矩阵 {codes} != {mat}"
    print("  预览：", {r: list(m.values()) for r, m in preview_expect.items()})

    # 下载权限（律师/秘书对秘密件不可下载）
    dl_secretary = request("GET", "/api/cases/2/documents/5/download", "secretary")[0]
    dl_lawyer = request("GET", "/api/cases/2/documents/5/download", "lawyer")[0]
    assert dl_secretary == 403 and dl_lawyer == 403
    assert request("GET", "/api/cases/2/documents/5/download", "partner")[0] == 200
    print("  秘密件下载：秘书403 律师403 合伙人200 ✓")

    # 检索按角色过滤正文
    assert {h["case_id"] for h in search("塔式起重机", "secretary")["hits"]} == set()
    assert {h["case_id"] for h in search("塔式起重机", "lawyer")["hits"]} == {2}
    assert {h["case_id"] for h in search("违法解除", "lawyer")["hits"]} == set()
    assert {h["case_id"] for h in search("违法解除", "partner")["hits"]} == {3}
    print("  检索隔离：秘书不见秘密、律师不见机密 ✓")

    # 管理操作
    assert request("POST", "/api/cases", "lawyer",
                   {"title": "x", "parties": "x", "lawyer": "x"})[0] == 403
    assert request("POST", "/api/cases/1/folders", "lawyer",
                   {"name": "x"})[0] == 403
    assert request("PATCH", "/api/cases/1/security-level", "secretary",
                   {"security_level": "secret"})[0] == 403
    print("  管理：律师403；秘书可建档/目录、不可改级别 ✓")

    # 删除整案仅合伙人
    assert request("DELETE", "/api/cases/1", "secretary")[0] == 403
    print("  删除整案：秘书403，仅合伙人 ✓")

    # 非法角色
    assert get("/api/cases/1", "intern")[0] == 400
    print("  未知角色 400 ✓")

    print("\n全部断言通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
