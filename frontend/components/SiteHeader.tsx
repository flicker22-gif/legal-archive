"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import RoleSwitcher from "./RoleSwitcher";

const LINKS = [
  { href: "/", label: "案件归档", match: (p: string) => p === "/" || p.startsWith("/cases") },
  { href: "/search", label: "全文检索", match: (p: string) => p.startsWith("/search") },
];

export default function SiteHeader() {
  const pathname = usePathname();
  return (
    <header className="site-header">
      <div className="inner">
        <Link href="/" className="brand">
          <span className="seal-dot" />
          案件归档检索系统
        </Link>
        <nav className="site-nav">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={l.match(pathname) ? "active" : ""}
            >
              {l.label}
            </Link>
          ))}
        </nav>
        <RoleSwitcher />
      </div>
    </header>
  );
}
