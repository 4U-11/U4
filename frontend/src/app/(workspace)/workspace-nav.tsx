"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navigationItems = [
  { href: "/mine", label: "我的", symbol: "▤" },
  { href: "/upload", label: "上传", symbol: "＋" },
  { href: "/api", label: "API", symbol: "⌘" },
  { href: "/settings", label: "设置", symbol: "⚙" },
];

export default function WorkspaceNav() {
  const pathname = usePathname();

  return (
    <nav className="workspace-nav" aria-label="工作区导航">
      {navigationItems.map((item) => {
        const isActive =
          pathname === item.href || pathname.startsWith(`${item.href}/`);

        return (
          <Link
            key={item.href}
            href={item.href}
            className={`workspace-nav-link${isActive ? " is-active" : ""}`}
            aria-current={isActive ? "page" : undefined}
          >
            <span className="workspace-nav-symbol" aria-hidden="true">
              {item.symbol}
            </span>
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
