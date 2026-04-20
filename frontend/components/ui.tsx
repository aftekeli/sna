import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  hint,
  tone = "cyan",
}: Readonly<{
  label: string;
  value: string;
  hint: string;
  tone?: "cyan" | "amber" | "green" | "pink";
}>) {
  return (
    <article className={`stat-card tone-${tone}`}>
      <p className="stat-label">{label}</p>
      <p className="stat-value">{value}</p>
      <p className="stat-hint">{hint}</p>
    </article>
  );
}

export function Panel({
  title,
  children,
  actions,
}: Readonly<{
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}>) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{title}</h2>
        {actions ? <div>{actions}</div> : null}
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function ProgressBar({
  label,
  value,
  suffix = "",
}: Readonly<{
  label: string;
  value: number;
  suffix?: string;
}>) {
  const normalized = Math.max(4, Math.min(100, value));

  return (
    <div className="progress-item">
      <div className="progress-meta">
        <span>{label}</span>
        <span>{`${value}${suffix}`}</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${normalized}%` }} />
      </div>
    </div>
  );
}

export function MetricPill({
  text,
  tone = "cyan",
}: Readonly<{
  text: string;
  tone?: "cyan" | "amber" | "green" | "pink";
}>) {
  return <span className={`metric-pill tone-${tone}`}>{text}</span>;
}
