"""端到端冒烟测试：案件、上传、检索、PDF 预览。"""
import io
import sys
import urllib.parse
import urllib.request

import fitz

BASE = "http://127.0.0.1:8000"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return r.status, r.read()


def search(kw, case_id=None):
    qs = urllib.parse.urlencode({"q": kw, **({"case_id": case_id} if case_id else {})})
    _, body = get(f"/api/search?{qs}")
    import json
    return json.loads(body)


def main() -> int:
    ok = True

    print("== 案件列表 ==")
    _, body = get("/api/cases?page_size=20")
    import json
    listing = json.loads(body)
    print(f"  共 {listing['total']} 个案件")
    assert listing["total"] >= 2, "演示案件缺失"

    print("\n== 案件详情 ==")
    detail = json.loads(get("/api/cases/1")[1])
    print(f"  {detail['title']}，卷宗 {len(detail['documents'])} 份")
    doc = detail["documents"][0]
    assert doc["status"] == "indexed", f"索引未完成: {doc['status']} {doc.get('error')}"
    assert doc["page_count"] == 3, f"页数应为3，实际 {doc['page_count']}"

    for kw in ["违约金", "拖欠租金", "塔式起重机", "解除合同", "催告"]:
        r = search(kw)
        print(f"\n== 检索「{kw}」 total={r['total']} ==")
        assert r["total"] > 0, f"未检中任何结果: {kw}"
        for h in r["hits"][:3]:
            print(f"  案件#{h['case_id']} {h['case_title'][:16]} "
                  f"| {h['filename']} 第{h['page_no']}页 rank={h['rank']:.3f}")
            print(f"    {h['snippet'][:110]}")
            assert "<mark>" in h["snippet"], "摘要缺少高亮"

    # 按案件范围过滤
    r = search("违约金", case_id=2)
    assert all(h["case_id"] == 2 for h in r["hits"]) and r["total"] > 0
    print(f"\n== 案件#2 内检索「违约金」 total={r['total']}（范围过滤生效）==")

    # AND 语义：两个词同时出现在同一页
    r = search("被告 租金")
    assert r["total"] > 0
    print(f"== 多词 AND「被告 租金」 total={r['total']} ==")

    # PDF 预览可打开且内容可读
    status, body = get(f"/api/cases/1/documents/{doc['id']}/preview")
    pdf = fitz.open(stream=io.BytesIO(body), filetype="pdf")
    text = "".join(p.get_text() for p in pdf)
    assert "起诉状" in text and "拖欠租金" in text, "PDF 文本抽取不完整"
    print(f"\n== PDF 预览 HTTP {status}, {len(body)//1024}KB, "
          f"{pdf.page_count} 页，文本可检索 ==")

    # 空结果 / 停用词
    r = search("不存在的生僻词汇饕餮魑魅")
    assert r["total"] == 0
    print("== 无命中关键词返回空结果 OK ==")

    print("\n全部断言通过 ✅" if ok else "\n存在失败 ❌")
    return 0


if __name__ == "__main__":
    sys.exit(main())
