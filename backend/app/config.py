import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://archive:archive@127.0.0.1:55432/archive",
)

# 卷宗 PDF 本地存储目录
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", BASE_DIR / "storage"))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# 检索参数
SNIPPET_RADIUS = 60          # 命中关键词前后保留的字符数
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50
MAX_UPLOAD_MB = 50

# 索引任务（可恢复的后台任务：queued → processing → indexed/failed）
INDEX_WORKERS = 4                # 后台索引线程数
INDEX_TASK_TIMEOUT_SEC = 600     # processing 超过该时长视为僵死，自动重排
INDEX_SWEEP_INTERVAL_SEC = 30    # 僵死任务巡检间隔
INDEX_MAX_AUTO_RETRIES = 3       # 中断/超时后的自动重试上限（手动重试不限）
