import { LEVEL_LABELS, type SecurityLevel } from "@/lib/rbac";

const STYLE: Record<SecurityLevel, string> = {
  normal: "sec-normal",
  secret: "sec-secret",
  confidential: "sec-confidential",
};

export default function SecurityBadge({
  level,
  size = "sm",
}: {
  level: SecurityLevel;
  size?: "sm" | "md";
}) {
  return (
    <span className={`sec-badge ${STYLE[level]} ${size}`}>
      {level === "confidential" ? "🔒 " : level === "secret" ? "🔑 " : ""}
      {LEVEL_LABELS[level]}
    </span>
  );
}
