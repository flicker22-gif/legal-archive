"""PostgreSQL 连接池与建表初始化（psycopg3）。"""
from psycopg.rows import tuple_row
from psycopg_pool import ConnectionPool

from .config import DATABASE_URL

# 默认元组行；需要字典的调用方显式 conn.row_factory = dict_row。
# reset 回调在连接归还池中时把行工厂恢复，防止借用者设置的 dict_row
# 污染下一个复用该连接的调用方。
def _reset_conn(conn) -> None:
    conn.row_factory = tuple_row


pool = ConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=8,
    open=False,
    kwargs={"row_factory": tuple_row},
    reset=_reset_conn,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cases (
    id          BIGSERIAL PRIMARY KEY,
    case_no     VARCHAR(100),                       -- 案号
    title       VARCHAR(300) NOT NULL,             -- 案件名称
    cause       VARCHAR(200),                      -- 案由
    parties     TEXT NOT NULL,                     -- 当事人（可多个）
    lawyer      VARCHAR(100) NOT NULL,             -- 承办律师
    remark      TEXT,                              -- 备注
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 案件内自定义卷宗目录（起诉状 / 证据 / 判决书 等，用户可自建改名排序）
CREATE TABLE IF NOT EXISTS folders (
    id          BIGSERIAL PRIMARY KEY,
    case_id     BIGINT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    name        VARCHAR(100) NOT NULL,
    position    INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (case_id, name)
);
CREATE INDEX IF NOT EXISTS idx_folders_case ON folders(case_id);

CREATE TABLE IF NOT EXISTS documents (
    id           BIGSERIAL PRIMARY KEY,
    case_id      BIGINT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    folder_id    BIGINT,                            -- NULL=未分类
    filename     VARCHAR(500) NOT NULL,            -- 原始文件名
    stored_name  VARCHAR(500) NOT NULL,            -- 存储路径中的文件名
    page_count   INT NOT NULL DEFAULT 0,
    size_bytes   BIGINT NOT NULL DEFAULT 0,
    status       VARCHAR(20) NOT NULL DEFAULT 'processing',
                                           -- processing / indexed / failed
    error        TEXT,
    uploaded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    indexed_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_documents_case ON documents(case_id);

-- 卷宗按页抽取的正文与全文检索向量
CREATE TABLE IF NOT EXISTS document_pages (
    id           BIGSERIAL PRIMARY KEY,
    document_id  BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no      INT NOT NULL,
    raw_text     TEXT NOT NULL,                    -- 该页原始文本（用于生成摘要）
    tsv          TSVECTOR NOT NULL,                -- 中文 bigram 检索向量
    UNIQUE (document_id, page_no)
);

-- GIN 倒排索引，加速全文检索
CREATE INDEX IF NOT EXISTS idx_pages_tsv ON document_pages USING GIN (tsv);

-- 旧库幂等迁移
ALTER TABLE documents ADD COLUMN IF NOT EXISTS folder_id BIGINT;
CREATE INDEX IF NOT EXISTS idx_documents_folder ON documents(folder_id);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'documents_folder_id_fkey'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT documents_folder_id_fkey
            FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL;
    END IF;
END $$;
"""

# 新建案件时的默认目录（position 从 0 起）
DEFAULT_FOLDERS = ["诉讼文书", "证据材料", "裁判文书"]


def init_pool() -> None:
    pool.open(wait=True)


def init_schema() -> None:
    with pool.connection() as conn:
        conn.execute(SCHEMA_SQL)
        # 旧案件补建默认目录（仅当该案件尚无任何目录时）
        conn.execute(
            """
            INSERT INTO folders (case_id, name, position)
            SELECT c.id, f.name, f.pos
              FROM cases c
              CROSS JOIN (VALUES ('诉讼文书', 0), ('证据材料', 1),
                                  ('裁判文书', 2)) AS f(name, pos)
             WHERE NOT EXISTS (SELECT 1 FROM folders fo WHERE fo.case_id = c.id)
            """
        )
        conn.commit()


def close_pool() -> None:
    pool.close()
