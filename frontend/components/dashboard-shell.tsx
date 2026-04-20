import Link from "next/link";
import type { ReactNode } from "react";

import type { NavKey } from "@/lib/dashboard-data";
import { mastheadChips, navItems } from "@/lib/dashboard-data";

export function DashboardShell({
  active,
  children,
}: Readonly<{
  active: NavKey;
  children: ReactNode;
}>) {
  return (
    <main className="app-shell">
      <div className="grid-backdrop" />
      <header className="masthead">
        <div className="brand-lockup">
          <div className="brand-mark">KG</div>
          <div>
            <p className="eyebrow">Multi-Hop Question Answering with KG-Infused RAG</p>
            <h1>Using Wikidata5M — Türkiye Cinema Domain</h1>
          </div>
        </div>
        <div className="chip-row">
          {mastheadChips.map((chip) => (
            <span className="chip" key={chip}>
              {chip}
            </span>
          ))}
        </div>
      </header>

      <nav className="top-nav">
        {navItems.map((item) => (
          <Link
            className={`nav-link ${item.key === active ? "is-active" : ""}`}
            href={item.href}
            key={item.key}
          >
            <span>{item.label}</span>
            {item.badge ? <span className="nav-badge">{item.badge}</span> : null}
          </Link>
        ))}
      </nav>

      <section className="page-body">{children}</section>
    </main>
  );
}
