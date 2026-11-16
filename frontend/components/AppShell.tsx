"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";

export default function AppShell({
  role,
  children,
}: {
  role?: "manager" | "bank" | null;
  children: ReactNode;
}) {
  const pathname = usePathname() ?? "";
  const modeLabel =
    role === "manager" ? "管理会社モード" : role === "bank" ? "銀行モード" : null;

  return (
    <>
      <header className="shell-header">
        <div className="brand">
          <span className="brand-star">★</span>
          <Link href="/" className="brand-logo">
            はかろうもん
          </Link>
          <span className="brand-mvp">MVP</span>
          <span className="brand-tag">修繕積立金 見える化ツール</span>
        </div>
        {modeLabel && <span className="mode-chip">{modeLabel}</span>}
      </header>
      <div className="shell-body">
        <nav className="sidebar">
          <p className="sidebar-title">メニュー</p>
          <Link href="/" className={pathname === "/" ? "active" : ""}>
            案件一覧
          </Link>
          <Link
            href="#"
            className={pathname.startsWith("/cases/") ? "active" : ""}
            onClick={(e) => e.preventDefault()}
          >
            将来予測・判定結果
          </Link>
        </nav>
        <main className="shell-main">{children}</main>
      </div>
    </>
  );
}