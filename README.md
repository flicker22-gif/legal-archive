# 案件归档检索系统

律所纸质卷宗电子化：秘书按案件录入当事人、案由、承办律师，建立自定义**卷宗目录**
（默认：诉讼文书 / 证据材料 / 裁判文书，可新建、改名、排序、删除）并把卷宗 PDF
归入目录；系统自动抽取 PDF 正文、建立中文全文索引；律师可跨案件/按目录按关键词
全文检索，查看带高亮的命中摘要，并一键预览原卷对应页码。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 14 (App Router) + TypeScript + React 18 |
| 后端 | Python 3.11 + FastAPI + uvicorn |
| 数据库 | PostgreSQL 15（`tsvector` + GIN 索引全文检索） |
| PDF 解析 | PyMuPDF（逐页抽取文本） |
| 中文检索 | 字级二元组（bigram）+ PostgreSQL `tsvector`/GIN/短语查询 |
| 权限 | 保密级别（普通/秘密/机密）× 角色（秘书/律师/合伙人）RBAC |

## 目录结构

```
10-project/
├── backend/                FastAPI 后端
│   ├── app/
│   │   ├── main.py             入口、CORS、建表
│   │   ├── db.py               连接池、表结构（cases/documents/document_pages）
│   │   ├── models.py             Pydantic 模型
│   │   ├── search.py           bigram 索引/查询构造、高亮摘要
│   │   ├── pdf_service.py      PDF 落盘、逐页抽取、写 tsvector
│   │   ├── storage.py          磁盘文件清理
│   │   ├── routers_cases.py    案件录入/列表/详情/删除
│   │   ├── routers_folders.py  卷宗目录增删改/排序
│   │   ├── routers_documents.py 卷宗上传/移动/状态/预览/下载/删除
│   │   └── routers_search.py   全文检索（分页、按案件/目录过滤、相关度排序）
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

## 角色与保密级别

每个案件有保密级别 **普通 normal / 秘密 secret / 机密 confidential**（仅合伙人可调整）；
系统有三种角色，顶栏「身份」可切换（演示用 `X-User-Role` 请求头模拟登录，
PDF 链接因浏览器直接加载用 `?role=` 兜底）：

| 能力 | 行政秘书 secretary | 承办律师 lawyer | 合伙人 partner |
|---|---|---|---|
| 案件列表 | 全部（需管理） | 普通+秘密（机密不可见） | 全部 |
| 普通件 查看正文/检索 | ✅ | ✅ | ✅ |
| 普通件 下载 | ✅ | ✅ | ✅ |
| 秘密件 查看正文/检索 | ❌ | ✅ | ✅ |
| 秘密件 下载 | ❌ | ❌ | ✅ |
| 机密件 任何内容 | ❌ | ❌（详情 403、检索过滤） | ✅ |
| 录入案件/上传/目录整理/移动 | ✅ | ❌ | ✅ |
| 修改保密级别 / 删除整案 | ❌ | ❌ | ✅ |

秘书/律师仍能看到秘密/机密案件的**登记信息和卷宗清单**（便于归档管理），
但无权查看 PDF 正文、下载原件或得到检索命中；越权请求后端返回 403，
前端对应按钮隐藏并显示「内容受限」。

## 使用流程

1. **录入案件**：首页「＋ 录入案件」填写案件名称、案号、案由、当事人（可多行）、
   承办律师。保存后系统自动建立三个默认目录：**诉讼文书 / 证据材料 / 裁判文书**。
2. **整理卷宗目录**：案件详情左侧目录栏可新建自定义目录（如「庭审笔录」「往来函件」）、
   改名、↑↓ 调整顺序、删除（删除目录不会删除卷宗，其内卷宗自动回到「未分类」）。
3. **上传卷宗**：先在目录栏选中目标目录，再将 PDF 拖入上传区（可多份），文件即归入该目录；
   也可在每份卷宗右侧的下拉框中随时移动目录。后端异步逐页抽取文本、构造 bigram 索引，
   页面自动轮询 `处理中 → 可检索`；扫描件等无文本层 PDF 会标记「索引失败」。
4. **全文检索**：
   - 顶部「全文检索」跨所有案件检索，结果带目录标签；案件详情页可只在本案、
     甚至当前选中目录内检索。
   - 多关键词为 AND（如 `被告 租金`）；结果按 `ts_rank_cd` 相关度排序、分页。
   - 每条结果给出案件、目录、卷宗、页码与 `<mark>` 高亮摘要，点「预览原卷第 N 页」
     在浏览器 PDF 查看器中直接定位到该页。

## 主要 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/cases` | 录入案件（同时建默认目录） |
| GET | `/api/cases?q=&page=` | 案件列表（按案号/名称/当事人/律师/案由筛选） |
| GET | `/api/cases/{id}` | 案件详情（含 folders 及卷宗的目录归属） |
| PUT/DELETE | `/api/cases/{id}` | 修改 / 删除（连带目录、卷宗、索引与文件；删除仅合伙人） |
| PATCH | `/api/cases/{id}/security-level` | 合伙人调整保密级别 |
| POST | `/api/cases/{id}/folders` | 新建目录（秘书/合伙人） |
| PUT/DELETE | `/api/cases/{id}/folders/{fid}` | 改名 / 删除（卷宗回未分类） |
| POST | `/api/cases/{id}/folders/reorder` | 按传入 id 顺序重排目录 |
| POST | `/api/cases/{id}/documents` | 上传 PDF（multipart 字段 file + 可选 folder_id，≤50MB） |
| PATCH | `/api/cases/{id}/documents/{doc}/move` | 移动卷宗到目录（folder_id=null=未分类） |
| GET | `/api/cases/{id}/documents/{doc}/status` | 索引状态轮询 |
| GET | `/api/cases/{id}/documents/{doc}/preview` | 内联 PDF（支持 `#page=N`） |
| GET | `/api/cases/{id}/documents/{doc}/download` | 下载 PDF |
| DELETE | `/api/cases/{id}/documents/{doc}` | 删除卷宗 |
| GET | `/api/search?q=&case_id=&folder_id=&page=` | 全文检索（folder_id=0 表示未分类；按角色过滤保密级别） |

所有接口读取请求头 `X-User-Role: secretary|lawyer|partner`（缺省秘书）；
PDF 预览/下载是浏览器直接打开的链接，支持 `?role=` 携带身份。

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
cases(id, case_no, title, cause, parties, lawyer, remark,
      security_level[normal|secret|confidential], created_at)
folders(id, case_id→cases, name, position, created_at)  UNIQUE(case_id,name)
documents(id, case_id→cases, folder_id→folders[ON DELETE SET NULL],
          filename, stored_name, page_count, size_bytes,
          status[processing|indexed|failed], error, uploaded_at, indexed_at)
document_pages(id, document_id→documents, page_no, raw_text, tsv TSVECTOR)
              UNIQUE(document_id,page_no);  GIN(tsv)
```

每个案件建档时自动创建默认目录 诉讼文书/证据材料/裁判文书（position 0–2）；
卷宗可不属于任何目录（folder_id 为 NULL，界面显示「未分类」）。

PDF 实体文件保存在 `backend/storage/<每千个文档分桶>/<uuid>_<原名>`。

## 已知边界（演示版）

- 鉴权为**演示态**：用 `X-User-Role` 头（顶栏切换写入 localStorage）模拟登录，
  没有真实账号、会话与密码；生产环境应接 SSO/JWT，并在律师与具体案件间建立
  承办关联（目前律师是全局角色，非"本案承办律师"粒度）。
- 仅处理带文本层的 PDF；扫描件需先 OCR（可在 `pdf_service` 中接 tesseract）。
- 文件存本地磁盘；多实例部署建议换 S3/MinIO。
