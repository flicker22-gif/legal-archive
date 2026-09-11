"use client";

import { useEffect, useState } from "react";
import {
  getRole,
  ROLE_LABELS,
  setRole,
  type Role,
} from "@/lib/rbac";

const ROLES: Role[] = ["secretary", "lawyer", "partner"];

export default function RoleSwitcher() {
  const [role, setRoleState] = useState<Role>("secretary");

  useEffect(() => {
    const sync = () => setRoleState(getRole());
    sync();
    window.addEventListener("rolechange", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("rolechange", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return (
    <label className="role-switcher" title="演示：切换当前登录身份">
      <span className="role-label">身份</span>
      <select
        value={role}
        onChange={(e) => {
          const r = e.target.value as Role;
          setRole(r);
          // 切换角色后刷新页面，避免残留无权数据
          window.location.reload();
        }}
      >
        {ROLES.map((r) => (
          <option key={r} value={r}>
            {ROLE_LABELS[r]}
          </option>
        ))}
      </select>
    </label>
  );
}
