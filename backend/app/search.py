"""中文全文检索：字级二元组（bigram）+ PostgreSQL tsvector。

为什么不用纯 jieba：词典分词对「塔式起重机」这类复合词切分不稳定
（可能切成「塔式起重 + 机」），查询端无论怎么扩展都可能漏召回。
bigram 是 CJK 检索的通行做法（Elasticsearch CJK analyzer 同理）：

- 索引侧：每个连续中文片段展开为相邻字二元组，保留全部出现位置
  （重复不去重，使 tsvector 记录多位置），片段间插入占位词元防止跨片段
  误配；末尾追加单字集合（支持单字检索）与英文/数字词。
- 查询侧：中文词展开为相邻 bigram，用 PG 短语操作符 <-> 连接
  （近"子串"语义）；多个词之间为 AND；ts_rank_cd 排序。
- 高亮在 Python 原文上做窗口截取与 <mark> 标注，输出前 HTML 转义。
"""
import html
import re

CJK = re.compile(r"[一-鿿]+")
ALNUM = re.compile(r"[0-9a-z]+")
TOKEN_CHARS = re.compile(r"[0-9A-Za-z一-鿿]")

# 单字停用词（仅影响长度为 1 的查询词）
STOPWORDS = set("的 了 和 与 及 在 是 我 你 他 她 它 们 这 那 就 都 很 也 被 把 "
                "让 给 向 于 对 为 中 之 其 或 等 有 无 不 以 上 下".split())


def _cjk_bigrams(run: str) -> list[str]:
    if len(run) == 1:
        return [run] if run not in STOPWORDS else []
    return [run[i : i + 2] for i in range(len(run) - 1)]


def index_tokens(text: str) -> str:
    """构造喂给 to_tsvector('simple', ...) 的空格分隔词元串。"""
    # PDF 抽取常在词语中间插入换行/空格，先压缩汉字之间的空白，
    # 避免「塔式起\n重机」被切成两个片段导致短语匹配失败
    compact = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", text or "")
    stream: list[str] = []
    unigrams: list[str] = []
    uni_seen: set[str] = set()

    runs = CJK.findall(compact)
    for idx, run in enumerate(runs):
        if idx > 0:
            # 唯一占位词元：保证跨片段的 bigram 不会"位置相邻"造成误配
            stream.append(f"zbnd{idx:06d}z")
        bgs = _cjk_bigrams(run)
        stream.extend(bgs if len(run) > 1 else [])
        for ch in run:
            if ch not in STOPWORDS and ch not in uni_seen:
                uni_seen.add(ch)
                unigrams.append(ch)

    words = []
    wseen: set[str] = set()
    for w in ALNUM.findall((text or "").lower()):
        if w not in wseen:
            wseen.add(w)
            words.append(w)

    return " ".join(stream + unigrams + words)


def _quote(t: str) -> str:
    return "'" + t.replace("'", "''") + "'"


def build_tsquery(query: str) -> str | None:
    """中文词 -> bigram 短语（<-> 相邻），词间 AND；英文数字整词匹配。

    如「华信 起重机」-> '华信' & '起重' <-> '重机'。无有效词元返回 None。
    """
    clauses: list[str] = []
    for run in CJK.findall(query or ""):
        if len(run) == 1:
            if run not in STOPWORDS:
                clauses.append(_quote(run))
        else:
            bgs = [run[i : i + 2] for i in range(len(run) - 1)]
            clauses.append(" <-> ".join(_quote(b) for b in bgs))
    for word in ALNUM.findall((query or "").lower()):
        clauses.append(_quote(word))
    if not clauses:
        return None
    return " & ".join(clauses)


def highlight_terms(query: str) -> list[str]:
    """高亮词：用户原始检索片段（长度>=2 或英文数字），长词优先。"""
    terms: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[\s,，、;；。.：:？?！!（）()\[\]【】\"'《》<>]+", query or ""):
        t = raw.strip()
        if len(t) >= 2 and TOKEN_CHARS.search(t) and t not in seen:
            seen.add(t)
            terms.append(t)
    terms.sort(key=len, reverse=True)
    return terms


def make_snippet(text: str, terms: list[str], radius: int = 60,
                 max_windows: int = 3) -> str:
    """在原文中定位命中词，截取前后 radius 字符的窗口并加 <mark>。"""
    if not text or not terms:
        return ""
    pattern = re.compile("|".join(re.escape(t) for t in terms))
    marks = [(m.start(), m.end()) for m in pattern.finditer(text)]
    if not marks:
        return html.escape(re.sub(r"\s+", " ", text[: radius * 2]).strip())

    windows: list[tuple[int, int]] = []
    for start, end in marks:
        wl, wr = max(0, start - radius), min(len(text), end + radius)
        if windows and wl <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(wr, windows[-1][1]))
        else:
            windows.append((wl, wr))
        if len(windows) >= max_windows:
            break

    out: list[str] = []
    for i, (wl, wr) in enumerate(windows):
        seg = text[wl:wr]
        # 先转义原文，再在转义后的文本上标注，避免 XSS
        seg = html.escape(seg)
        esc_terms = sorted({html.escape(t) for t in terms}, key=len, reverse=True)
        pat = re.compile("|".join(re.escape(t) for t in esc_terms))
        seg = pat.sub(lambda m: f"<mark>{m.group(0)}</mark>", seg)
        seg = re.sub(r"\s+", " ", seg).strip()
        if i > 0 or wl > 0:
            seg = "… " + seg
        if wr < len(text):
            seg = seg + " …"
        out.append(seg)
    return " ".join(out)
