"""索引任务队列：后台线程执行、进程重启恢复与僵死任务巡检。

可恢复性保证：
- 上传/重试只负责把状态置为 queued 并 enqueue；worker 认领后才执行。
- 进程重启时 recover_interrupted_tasks() 重新发现所有未完成任务：
  processing（崩溃中断）记一次重试后重排，queued 直接重新投入。
- 后台巡检线程把 processing 超时（worker 卡死）的任务同样重排。
- 自动重试超过 INDEX_MAX_AUTO_RETRIES 次的任务明确标记 failed 并给出
  可读原因——绝不一直停在「处理中」伪装成进行中或成功。
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from psycopg.rows import tuple_row

from .config import (
    INDEX_MAX_AUTO_RETRIES,
    INDEX_SWEEP_INTERVAL_SEC,
    INDEX_TASK_TIMEOUT_SEC,
    INDEX_WORKERS,
)
from .db import pool
from .pdf_service import index_document

log = logging.getLogger("indexer")

_executor = ThreadPoolExecutor(
    max_workers=INDEX_WORKERS, thread_name_prefix="indexer"
)
_stop = threading.Event()
_sweeper: threading.Thread | None = None


def enqueue(document_id: int) -> None:
    """把 queued 状态的卷宗投入后台索引（重复投入安全：认领有守卫）。"""
    _executor.submit(_run_safe, document_id)


def _run_safe(document_id: int) -> None:
    """兜底异常处理：worker 自身出错也不能让任务停在 processing。"""
    try:
        index_document(document_id)
    except Exception:
        log.exception("索引任务异常 doc=%s", document_id)
        try:
            with pool.connection() as conn:
                conn.row_factory = tuple_row
                conn.execute(
                    """
                    UPDATE documents
                       SET status='failed', task_started_at=NULL,
                           error='索引任务异常中断，请重试'
                     WHERE id=%s AND status='processing'
                    """,
                    (document_id,),
                )
                conn.commit()
        except Exception:
            log.exception("兜底标记失败也失败 doc=%s", document_id)


def _requeue_interrupted(stale_where: str, params: dict) -> list[int]:
    """把符合条件的 processing 任务重排（或超限判失败），返回全部待执行 id。"""
    with pool.connection() as conn:
        conn.row_factory = tuple_row
        # 未超自动重试上限：记一次重试并重新排队
        conn.execute(
            f"""
            UPDATE documents
               SET status='queued', retry_count=retry_count+1,
                   task_started_at=NULL
             WHERE status='processing' AND retry_count < %(max)s
               AND {stale_where}
            """,
            {**params, "max": INDEX_MAX_AUTO_RETRIES},
        )
        # 超过上限：明确失败，不能停在 processing 伪装成进行中/成功
        conn.execute(
            f"""
            UPDATE documents
               SET status='failed', task_started_at=NULL,
                   error='索引任务多次中断或超时，已停止自动重试，请手动重试'
             WHERE status='processing' AND NOT (retry_count < %(max)s)
               AND {stale_where}
            """,
            {**params, "max": INDEX_MAX_AUTO_RETRIES},
        )
        queued = conn.execute(
            "SELECT id FROM documents WHERE status='queued'"
        ).fetchall()
        conn.commit()
    return [r[0] for r in queued]


def recover_interrupted_tasks() -> list[int]:
    """进程启动时调用：重新发现所有未完成任务并重新投入执行。

    进程刚启动，凡 processing 状态的任务其执行者必然已死，全部重排。
    返回重新投入执行的任务 id 列表。
    """
    ids = _requeue_interrupted("TRUE", {})
    for doc_id in ids:
        enqueue(doc_id)
    if ids:
        log.info("恢复未完成的索引任务：%s", ids)
    return ids


def _sweep_loop() -> None:
    """定期把 processing 超时（worker 卡死）的任务重新排队或判失败。"""
    while not _stop.wait(INDEX_SWEEP_INTERVAL_SEC):
        try:
            ids = _requeue_interrupted(
                "task_started_at < now() - make_interval(secs => %(timeout)s)",
                {"timeout": INDEX_TASK_TIMEOUT_SEC},
            )
            for doc_id in ids:
                enqueue(doc_id)
        except Exception:
            log.exception("索引任务巡检失败")


def start_sweeper() -> None:
    global _sweeper
    if _sweeper is None:
        _sweeper = threading.Thread(
            target=_sweep_loop, daemon=True, name="index-sweeper"
        )
        _sweeper.start()


def shutdown() -> None:
    """停止巡检与线程池；未完成的 queued 任务留待下次启动恢复。"""
    _stop.set()
    if _sweeper is not None:
        _sweeper.join(timeout=2)
    _executor.shutdown(wait=False, cancel_futures=True)
