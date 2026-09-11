"""端到端冒烟测试：案件、目录、上传、检索、PDF 预览（需先 seed_demo）。"""
import io
import sys
import urllib.parse
import urllib.request

import fitz

BASE = "http://127.0.0.1:8000"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return r.status, r.read()


def search(kw, case_id=None, folder_id=None):
    p = {"q": kw}
    if case_id:
        p["case_id"] = case_id
    if folder_id is not None:
        p["folder_id"] = folder_id
    _, body = get(f"/api/search?{urllib.parse.urlencode(p)}")
    import json
    return json.loads(body)


def main() -> int:
    import json

    print("== 案件列表 ==")
    _, body = get("/api/cases?page_size=20")
    listing = json.loads(body)
    assert listing["total"] >= 2, "演示案件缺失"
    print(f"  共 {listing['total']} 个案件")

    print("== 案件1详情：默认目录 + 分类卷宗 ==")
    detail = json.loads(get("/api/cases/1")[1])
    folders = {f["name"]: f for f in detail["folders"]}
    assert set(folders) >= {"诉讼文书", "证据材料", "裁判文书"}, "默认目录缺失"
    by_folder = {}
    for d in detail["documents"]:
        by_folder.setdefault(d["folder_name"], []).append(d["filename"])
        assert d["status"] == "indexed", f"{d['filename']} 未索引: {d.get('error')}"
    print("  目录分布:", {k: v for k, v in by_folder.items()})
    assert "民事起诉状.pdf" in by_folder.get("诉讼文书", [])
    assert "证据目录.pdf" in by_folder.get("证据材料", [])
    assert "民事判决书.pdf" in by_folder.get("裁判文书", [])
    assert folders["诉讼文书"]["doc_count"] == 2

    print("== 案件2含自定义目录 ==")
    d2 = json.loads(get("/api/cases/2")[1])
    f2 = {f["name"] for f in d2["folders"]}
    assert {"合同文件", "往来函件"} <= f2, f"自定义目录缺失: {f2}"
    print("  目录:", sorted(f2))

    for kw in ["违约金", "拖欠租金", "塔式起重机", "解除合同", "催告", "上诉"]:
        r = search(kw)
        print(f"检索「{kw}」 total={r['total']}")
        assert r["total"] > 0, f"未检中: {kw}"
        for h in r["hits"][:2]:
            assert "<mark>" in h["snippet"], "缺少高亮"
        # 命中均带目录归属
        assert all(("folder_name" in h) for h in r["hits"])

    # 目录范围过滤
    fid_panjue = folders["裁判文书"]["id"]
    r = search("判决", folder_id=fid_panjue)
    assert r["total"] == 1 and r["hits"][0]["filename"] == "民事判决书.pdf"
    print(f"== 裁判文书目录内检索「判决」={r['total']} ==")
    r = search("判决", folder_id=folders["证据材料"]["id"])
    assert r["total"] == 0
    print("== 证据材料目录内「判决」=0（目录隔离生效）==")

    # 多词 AND
    r = search("被告 租金")
    assert r["total"] > 0
    print(f"== 多词 AND「被告 租金」 total={r['total']} ==")

    # PDF 预览可打开且文本可读
    qs = next(d for d in detail["documents"] if d["filename"] == "民事起诉状.pdf")
    status, body = get(f"/api/cases/1/documents/{qs['id']}/preview")
    pdf = fitz.open(stream=io.BytesIO(body), filetype="pdf")
    text = "".join(p.get_text() for p in pdf)
    assert "起诉状" in text and "拖欠租金" in text
    print(f"== PDF 预览 HTTP {status}, {len(body)//1024}KB, 文本可检索 ==")

    # 空结果
    assert search("不存在的生僻词汇饕餮魑魅")["total"] == 0
    print("== 无命中关键词返回空结果 OK ==")

    print("\n全部断言通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
