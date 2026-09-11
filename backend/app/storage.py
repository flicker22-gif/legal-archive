"""卷宗文件存储的磁盘清理。"""
from pathlib import Path

from .config import STORAGE_DIR


def _path_of(document_id: int, stored_name: str) -> Path | None:
    if not stored_name:
        return None
    return STORAGE_DIR / f"{document_id // 1000:04d}" / stored_name


def delete_document_file(document_id: int, stored_name: str) -> None:
    p = _path_of(document_id, stored_name)
    if p and p.exists():
        p.unlink()


def delete_case_files(rows) -> None:
    for doc_id, stored_name in rows:
        delete_document_file(doc_id, stored_name)
