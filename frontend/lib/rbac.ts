// 角色与保密级别的客户端镜像（与后端 app/permissions.py 保持一致）
export type Role = "secretary" | "lawyer" | "partner";
export type SecurityLevel = "normal" | "secret" | "confidential";

export const ROLE_LABELS: Record<Role, string> = {
  secretary: "行政秘书",
  lawyer: "承办律师",
  partner: "合伙人",
};

export const LEVEL_LABELS: Record<SecurityLevel, string> = {
  normal: "普通",
  secret: "秘密",
  confidential: "机密",
};

const LEVEL_RANK: Record<SecurityLevel, number> = {
  normal: 0,
  secret: 1,
  confidential: 2,
};

const VIEW_MAX: Record<Role, number | null> = {
  secretary: LEVEL_RANK.normal,
  lawyer: LEVEL_RANK.secret,
  partner: null,
};
const DOWNLOAD_MAX: Record<Role, number | null> = {
  secretary: LEVEL_RANK.normal,
  lawyer: LEVEL_RANK.normal,
  partner: null,
};

export function canView(role: Role, level: SecurityLevel): boolean {
  const top = VIEW_MAX[role];
  return top === null || LEVEL_RANK[level] <= top;
}

export function canDownload(role: Role, level: SecurityLevel): boolean {
  const top = DOWNLOAD_MAX[role];
  return top === null || LEVEL_RANK[level] <= top;
}

export function canManage(role: Role): boolean {
  return role === "secretary" || role === "partner";
}

export function canSetSecurity(role: Role): boolean {
  return role === "partner";
}

export function canDeleteCase(role: Role): boolean {
  return role === "partner";
}

const ROLE_KEY = "archive.role";

export function getRole(): Role {
  if (typeof window === "undefined") return "secretary";
  const v = window.localStorage.getItem(ROLE_KEY);
  return v === "lawyer" || v === "partner" || v === "secretary" ? v : "secretary";
}

export function setRole(role: Role) {
  window.localStorage.setItem(ROLE_KEY, role);
  window.dispatchEvent(new Event("rolechange"));
}
