import Link from "next/link";
import type { ReactNode } from "react";
import WorkspaceNav from "./workspace-nav";

export default function WorkspaceLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <div className="workspace-shell">
      <aside className="workspace-sidebar">
        <div className="workspace-brand-row">
          <Link href="/" className="workspace-brand" aria-label="返回首页">
            <span className="workspace-logo-placeholder">LOGO</span>
            <span>课程助手</span>
          </Link>
        </div>
        <WorkspaceNav />
      </aside>

      <div className="workspace-main">{children}</div>
    </div>
  );
}
