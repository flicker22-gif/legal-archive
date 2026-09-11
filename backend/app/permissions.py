"""基于角色与案件保密级别的权限控制（演示版，无真实登录）。

角色（X-User-Role 请求头，缺省 secretary）：
  - secretary 行政秘书：录入/上传/整理材料，但按级别限制能否看内容
  - lawyer    承办律师：可看普通/秘密卷宗，机密不可见
  - partner   合伙人：  全部可见、可下载、可改保密级别

保密级别：normal 普通 / secret 秘密 / confidential 机密

权限矩阵（can_view=能否预览正文、检索命中；can_download=能否下载原件；
can_manage=录入/上传/目录整理；can_set_level=修改保密级别）：

| 级别        | 秘书              | 律师        | 合伙人 |
|-------------|-------------------|-------------|--------|
| normal      | 查看+下载+管理    | 查看+下载   | 全部   |
| secret      | 仅管理（看不到内容）| 查看不可下载 | 全部   |
| confidential| 仅管理            | 不可见      | 全部   |
"""
from fastapi import Header, HTTPException, Query

ROLE_SECRETARY = "secretary"
ROLE_LAWYER = "lawyer"
ROLE_PARTNER = "partner"
ROLES = (ROLE_SECRETARY, ROLE_LAWYER, ROLE_PARTNER)
ROLE_LABELS = {
    ROLE_SECRETARY: "行政秘书",
    ROLE_LAWYER: "承办律师",
    ROLE_PARTNER: "合伙人",
}

LEVEL_NORMAL = "normal"
LEVEL_SECRET = "secret"
LEVEL_CONFIDENTIAL = "confidential"
SECURITY_LEVELS = (LEVEL_NORMAL, LEVEL_SECRET, LEVEL_CONFIDENTIAL)
LEVEL_LABELS = {
    LEVEL_NORMAL: "普通",
    LEVEL_SECRET: "秘密",
    LEVEL_CONFIDENTIAL: "机密",
}
LEVEL_ORDER = {LEVEL_NORMAL: 0, LEVEL_SECRET: 1, LEVEL_CONFIDENTIAL: 2}

# 各角色可“看到内容”的最高保密级别（None=任意，2=全部）
_VIEW_MAX_RANK = {
    ROLE_SECRETARY: LEVEL_ORDER[LEVEL_NORMAL],
    ROLE_LAWYER: LEVEL_ORDER[LEVEL_SECRET],
    ROLE_PARTNER: None,
}
# 可“下载原件”的最高保密级别
_DOWNLOAD_MAX_RANK = {
    ROLE_SECRETARY: LEVEL_ORDER[LEVEL_NORMAL],
    ROLE_LAWYER: LEVEL_ORDER[LEVEL_NORMAL],
    ROLE_PARTNER: None,
}


def current_role(
    x_user_role: str | None = Header(default=None),
    role: str | None = Query(default=None, description="角色兜底参数（用于 PDF iframe/下载链接）"),
) -> str:
    """FastAPI 依赖：解析当前角色。优先请求头 X-User-Role，其次 ?role=。
    演示环境缺省为行政秘书。"""
    raw = (x_user_role or role or ROLE_SECRETARY).strip().lower()
    if raw not in ROLES:
        raise HTTPException(400, f"未知角色：{raw}")
    return raw


def can_view(role: str, level: str) -> bool:
    """能否查看该级别案件的卷宗正文/检索命中。"""
    top = _VIEW_MAX_RANK[role]
    return top is None or LEVEL_ORDER[level] <= top


def can_download(role: str, level: str) -> bool:
    top = _DOWNLOAD_MAX_RANK[role]
    return top is None or LEVEL_ORDER[level] <= top


def can_manage(role: str) -> bool:
    """录入/上传/目录整理：秘书与合伙人。"""
    return role in (ROLE_SECRETARY, ROLE_PARTNER)


def can_set_security(role: str) -> bool:
    return role == ROLE_PARTNER


def require_view(role: str, level: str) -> None:
    if not can_view(role, level):
        raise HTTPException(
            403, f"该案件为「{LEVEL_LABELS[level]}」级，您的角色无权查看卷宗内容"
        )


def require_download(role: str, level: str) -> None:
    if not can_download(role, level):
        raise HTTPException(
            403, f"该案件为「{LEVEL_LABELS[level]}」级，您的角色无权下载原件"
        )


def require_manage(role: str) -> None:
    if not can_manage(role):
        raise HTTPException(403, "仅行政秘书/合伙人可执行录入、上传或目录整理操作")


def require_set_security(role: str) -> None:
    if not can_set_security(role):
        raise HTTPException(403, "仅合伙人可修改案件保密级别")
