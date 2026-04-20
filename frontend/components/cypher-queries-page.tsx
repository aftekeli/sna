"use client";

import { useState, useTransition } from "react";
import { DashboardShell } from "@/components/dashboard-shell";
import { Panel, MetricPill, StatCard } from "@/components/ui";
import { activeCypher, cypherResults, cypherStats, queryLibrary } from "@/lib/dashboard-data";
import type { StatCardData } from "@/lib/dashboard-data";

type QueryItem = {
  name: string;
  badge: string;
  description?: string;
  statement: string;
  row_count: number;
  sample_rows: Record<string, string>[];
};

type RunResult = {
  rows: Record<string, string>[];
  row_count: number;
  elapsed_ms: number;
  error: string | null;
};

const FALLBACK_QUERIES: QueryItem[] = queryLibrary.map((q, i) => ({
  ...q,
  description: "",
  statement: activeCypher,
  row_count: i < 3 ? 5 : 0,
  sample_rows: i === 0 ? cypherResults : [],
}));

export function CypherQueriesPage({
  stats = cypherStats,
  queries = FALLBACK_QUERIES,
}: Readonly<{
  stats?: StatCardData[];
  queries?: QueryItem[];
}>) {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [liveResult, setLiveResult] = useState<RunResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [isPending, startTransition] = useTransition();

  const selected = queries[selectedIdx];
  const displayRows = (liveResult ? liveResult.rows : selected?.sample_rows) ?? [];
  const displayColumns =
    displayRows.length > 0 ? Object.keys(displayRows[0]) : ["film", "director", "school"];

  function handleSelect(idx: number) {
    setSelectedIdx(idx);
    setLiveResult(null);
    setRunError(null);
  }

  function handleCopy() {
    if (!selected?.statement) return;
    navigator.clipboard.writeText(selected.statement).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }

  function handleRun() {
    setRunError(null);
    setLiveResult(null);
    startTransition(async () => {
      try {
        const base = process.env.NEXT_PUBLIC_BACKEND_API_BASE_URL ?? "http://127.0.0.1:8000";
        const res = await fetch(`${base}/dashboard/run-cypher`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query_index: selectedIdx }),
          signal: AbortSignal.timeout(10000),
        });
        const data: RunResult = await res.json();
        if (data.error) {
          setRunError(data.error);
        } else {
          setLiveResult(data);
        }
      } catch {
        setRunError("Request failed — is the backend running?");
      }
    });
  }

  const badgeTone = (badge: string) =>
    badge === "1-hop" ? "cyan" : badge === "2-hop" ? "amber" : badge === "3-hop" ? "green" : "pink";

  const resultTitle = liveResult
    ? `Live Result — ${liveResult.row_count} rows · ${liveResult.elapsed_ms} ms`
    : selected?.row_count
    ? `Query Results — ${selected.row_count} verified rows`
    : "Query Results — no sample data";

  return (
    <DashboardShell active="cypher-queries">
      <div className="stats-grid">
        {stats.map((card) => (
          <StatCard key={card.label} {...card} />
        ))}
      </div>

      <div className="cypher-layout">
        {/* ── Query Library ── */}
        <Panel title="Query Library">
          <div className="query-list">
            {queries.map((query, index) => (
              <button
                key={query.name}
                className={`query-item${index === selectedIdx ? " is-active" : ""}`}
                onClick={() => handleSelect(index)}
              >
                <div className="query-item-body">
                  <span className="query-item-name">{query.name}</span>
                </div>
                <div className="query-item-right">
                  {query.row_count > 0 && (
                    <span className="query-verified-dot" title={`${query.row_count} verified rows`}>
                      ✓
                    </span>
                  )}
                  <MetricPill text={query.badge} tone={badgeTone(query.badge)} />
                </div>
              </button>
            ))}
          </div>
        </Panel>

        {/* ── Right column ── */}
        <div className="cypher-right">
          {/* Cypher Statement */}
          <Panel
            title="Cypher Statement"
            actions={
              <button className="copy-btn" onClick={handleCopy}>
                {copied ? "Copied ✓" : "Copy"}
              </button>
            }
          >
              <pre className="code-block cypher-code">{selected?.statement ?? activeCypher}</pre>
          </Panel>

          {/* Description box */}
          {selected?.description && (
            <div className="query-desc-box">
              <span className="query-desc-box-label">What this query does</span>
              <p className="query-desc-box-text">{selected.description}</p>
            </div>
          )}

          {/* Query Results */}
          <Panel
            title={resultTitle}
            actions={
              <button
                className={`run-live-btn${isPending ? " is-running" : ""}`}
                onClick={handleRun}
                disabled={isPending}
              >
                {isPending ? "Running…" : "Run Live ▶"}
              </button>
            }
          >
            {runError && <p className="run-error">{runError}</p>}
            {displayRows.length > 0 ? (
              <div className="table-wrap cypher-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      {displayColumns.map((key) => (
                        <th key={key}>{key}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {displayRows.map((row, i) => (
                      <tr key={i}>
                        {displayColumns.map((key) => (
                          <td key={key}>{row[key] ?? "—"}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              !runError && (
                <p className="no-sample-hint">
                  No sample data — click <strong>Run Live ▶</strong> to execute against Neo4j.
                </p>
              )
            )}
            {liveResult && (
              <p className="result-source-tag">source: neo4j aura · {liveResult.elapsed_ms} ms</p>
            )}
          </Panel>
        </div>
      </div>
    </DashboardShell>
  );
}
