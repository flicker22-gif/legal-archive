# 案件归档检索系统

律所纸质卷宗电子化：秘书按案件录入当事人、案由、承办律师并上传卷宗 PDF，
系统自动抽取 PDF 正文、建立中文全文索引；律师可跨案件按关键词全文检索，
查看带高亮的命中摘要，并一键预览原卷对应页码。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 14 (App Router) + TypeScript + React 18 |
| 后端 | Python 3.11 + FastAPI + uvicorn |
| 数据库 | PostgreSQL 15（`tsvector` + GIN 索引全文检索） |
| PDF 解析 | PyMuPDF（逐页抽取文本） |
| 中文检索 | 字级二元组（bigram）+ PostgreSQL `tsvector`/GIN/短语查询 |

## 目录结构

```
10-project/
├── backend/                FastAPI 后端
│   ├── app/
│   │   ├── main.py             入口、CORS、建表
│   │   ├── db.py               连接池、表结构（cases/documents/document_pages）
│   │   ├── search.py           bigram 索引/查询构造、高亮摘要
│   │   ├── pdf_service.py      PDF 落盘、逐页抽取、写 tsvector
│   │   ├── routers_cases.py    案件录入/列表/详情/删除
│   │   ├── routers_documents.py 卷宗上传/状态/预览/下载/删除
│   │   └── routers_search.py   全文检索（分页、按案件过滤、相关度排序）
│   ├── seed_demo.py        演示案件 + 中文 PDF 生成/入库
│   └── smoke_test.py       端到端接口自测
├── frontend/               Next.js 前端
│   └── app/
│       ├── page.tsx            案件列表与筛选（首页）
│       ├── cases/new/          录入案件
│       ├── cases/[id]/         案件详情：上传卷宗、本案检索
│       ├── .../[docId]/preview PDF 预览（iframe，可定位页码）
│       └── search/             全局全文检索（高亮 + 跳转页码）
└── tools/                  便携版 PostgreSQL（免 root，deb 解包）
    ├── pgctl.sh                start/stop/status/psql
    ├── pgdata/                 数据目录
    └── pgroot/                 解包的 PG 程序
```

## 快速启动

前置：Python 3.11、Node.js ≥ 18（本仓库的 PG 与 Python 依赖均已在项目目录内就位，
无需系统安装 PostgreSQL）。

```bash
./start.sh                 # 启动 PG(55432) + 后端(8000) + 前端(4730)
```

- 前端：http://localhost:4730
- 后端 API 文档（Swagger）：http://localhost:8000/docs
- 停止：`./stop.sh`

### 首次/手动初始化（start.sh 已涵盖）

```bash
# 1) 数据库（tools/pgctl.sh 首次使用会自动 initdb；账号 archive/archive，端口 55432）
tools/pgctl.sh start

# 2) 后端
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000          # 首次启动自动建表

# 3) 演示数据（两个案件 + 两份多页中文 PDF，可重复执行）
.venv/bin/python seed_demo.py

# 4) 前端
cd ../frontend && npm install && npm run dev
```

## 使用流程

1. **录入案件**：首页「＋ 录入案件」填写案件名称、案号、案由、当事人（可多行）、
   承办律师。
2. **上传卷宗**：进入案件详情，将 PDF 拖入上传区（可多份）。
   后端异步逐页抽取文本、构造 bigram 索引并写入 `tsvector`，页面自动轮询
   `处理中 → 可检索` 状态；扫描件等无文本层 PDF 会标记「索引失败」。
3. **全文检索**：
   - 顶部「全文检索」跨所有案件检索；案件详情页可只在本案内检索。
   - 多关键词为 AND（如 `被告 租金`）；结果按 `ts_rank_cd` 相关度排序、分页。
   - 每条结果给出案件、卷宗、页码与 `<mark>` 高亮摘要，点「预览原卷第 N 页」
     在浏览器 PDF 查看器中直接定位到该页。

## 主要 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/cases` | 录入案件 |
| GET | `/api/cases?q=&page=` | 案件列表（按案号/名称/当事人/律师/案由筛选） |
| GET | `/api/cases/{id}` | 案件详情（含卷宗列表） |
| PUT/DELETE | `/api/cases/{id}` | 修改 / 删除（连带卷宗与文件） |
| POST | `/api/cases/{id}/documents` | 上传 PDF（multipart，≤50MB，后台索引） |
| GET | `/api/cases/{id}/documents/{doc}/status` | 索引状态轮询 |
| GET | `/api/cases/{id}/documents/{doc}/preview` | 内联 PDF（支持 `#page=N`） |
| GET | `/api/cases/{id}/documents/{doc}/download` | 下载 PDF |
| DELETE | `/api/cases/{id}/documents/{doc}` | 删除卷宗 |
| GET | `/api/search?q=&case_id=&page=` | 全文检索 |

自测：`cd backend && .venv/bin/python smoke_test.py`

## 中文检索的实现要点

PostgreSQL 自带分词器不能切分中文；纯 jieba 词典分词对「塔式起重机」这类
复合词切分不稳定（可能切成「塔式起重 + 机」），查询端扩展成 AND 后容易漏召回。
本系统采用 CJK 检索通行的 **bigram（相邻字二元组）** 方案：

- 索引：每个连续中文片段展开为相邻字二元组并保留出现位置，片段间插入唯一占位
  词元防止跨片段误配，另追加单字集合以支持单字检索；英文/数字按整词切分。
  例：`塔式起重机` → `塔式 式起 起重 重机`，故任意子串词（如「起重机」=
  `起重 → 重机`）都能命中，不依赖词典。
- 查询：中文词展开为相邻 bigram，用 PG 短语操作符 `<->` 连接
  （位置相邻，近似子串语义）；多个空格分隔的词之间为 AND；
  英文数字按整词匹配。
- 排序：`ts_rank_cd`；索引列为 GIN 倒排。
- 高亮：Python 侧在原文上做窗口截取与 `<mark>` 标注，输出前做 HTML 转义。
- PDF 抽取文本常在词中间插入换行，索引前会压缩汉字之间的空白。

## 数据模型

```text
cases(id, case_no, title, cause, parties, lawyer, remark, created_at)
documents(id, case_id→cases, filename, stored_name, page_count, size_bytes,
          status[processing|indexed|failed], error, uploaded_at, indexed_at)
document_pages(id, document_id→documents, page_no, raw_text, tsv TSVECTOR)
              UNIQUE(document_id,page_no);  GIN(tsv)
```

PDF 实体文件保存在 `backend/storage/<每千个文档分桶>/<uuid>_<原名>`。

## 已知边界（演示版）

- 无登录鉴权与多租户权限控制（律所内部系统，生产环境需补充）。
- 仅处理带文本层的 PDF；扫描件需先 OCR（可在 `pdf_service` 中接 tesseract）。
- 文件存本地磁盘；多实例部署建议换 S3/MinIO。
