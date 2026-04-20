import { DashboardShell } from "@/components/dashboard-shell";
import { Panel, StatCard } from "@/components/ui";
import { failureCases, successfulCase, xaiStats } from "@/lib/dashboard-data";
import type { StatCardData } from "@/lib/dashboard-data";

const ERROR_CATEGORY_COLORS: Record<string, string> = {
  "KG Data Deficiency": "var(--signal-rose)",
  "Entity Linking Error": "var(--signal-pink)",
  "Turkish-English Mismatch": "var(--signal-cyan)",
  "LLM Selection Error": "var(--signal-amber)",
  "Retrieval Error": "var(--signal-blue)",
};

export function XaiEvidencePage({
  stats = xaiStats,
  success = successfulCase,
  failures = failureCases,
}: Readonly<{
  stats?: StatCardData[];
  success?: typeof successfulCase;
  failures?: typeof failureCases;
}>) {
  // Compute error category frequency from the failure cases
  const categoryCounts = failures.reduce<Record<string, number>>((acc, fc) => {
    acc[fc.error_category] = (acc[fc.error_category] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <DashboardShell active="xai-evidence">
      <div className="stats-grid">
        {stats.map((card) => (
          <StatCard key={card.label} {...card} />
        ))}
      </div>

      {/* ── Success case ── */}
      <Panel title="Case Study — Successful KG-RAG Trace">
        <div className="two-column">
          <div className="stack">
            <div className="quote-box">{success.question}</div>
            <div className="reasoning-path">
              {success.path.map((step) => (
                <div className="path-step" key={`${step.label}-${step.value}`}>
                  <span>{step.label}</span>
                  <strong>{step.value}</strong>
                </div>
              ))}
            </div>
            <div className="result-line">
              <span>Gold Answer: {success.gold}</span>
              <span>System Answer: {success.prediction}</span>
            </div>
          </div>

          <div className="stack">
            <div className="trace-flow">
              {success.path.map((step, index) => {
                const isFirst = index === 0;
                const isLast = index === success.path.length - 1;
                return (
                  <div key={`${step.label}-${step.value}`} className="trace-flow-segment">
                    {!isFirst && (
                      <div className="trace-edge">
                        <span className="trace-edge-label">{step.label}</span>
                        <span className="trace-edge-arrow">↓</span>
                      </div>
                    )}
                    <div className={`trace-node${isFirst ? " is-seed" : ""}${isLast ? " is-answer" : ""}`}>
                      {isFirst && <span className="trace-node-tag">Seed</span>}
                      {isLast && <span className="trace-node-tag is-gold">Answer ✓</span>}
                      <strong>{step.value}</strong>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </Panel>

      {/* ── Error taxonomy legend ── */}
      <Panel title="Error Category Taxonomy (PDF Phase 6 — Section 7.3)">
        <div className="error-taxonomy-grid">
          {[
            { cat: "KG Data Deficiency", desc: "Required information not in Wikidata5M. Path cannot be completed.", n: categoryCounts["KG Data Deficiency"] ?? 0 },
            { cat: "Entity Linking Error", desc: "Entity in query cannot be found in KG. Incorrect entity matching.", n: categoryCounts["Entity Linking Error"] ?? 0 },
            { cat: "Turkish-English Mismatch", desc: "Turkish name exists only in English in KG. No alias match.", n: categoryCounts["Turkish-English Mismatch"] ?? 0 },
            { cat: "LLM Selection Error", desc: "LLM selects wrong triples or produces hallucinated answer without evidence.", n: categoryCounts["LLM Selection Error"] ?? 0 },
            { cat: "Retrieval Error", desc: "Relevant passage not in corpus or wrong passage retrieved.", n: categoryCounts["Retrieval Error"] ?? 0 },
          ].map(({ cat, desc, n }) => (
            <div className="error-cat-card" key={cat}>
              <div className="error-cat-head">
                <span
                  className="error-cat-dot"
                  style={{ background: ERROR_CATEGORY_COLORS[cat] ?? "var(--muted)" }}
                />
                <strong>{cat}</strong>
                <span className="error-cat-count">{n} / {failures.length}</span>
              </div>
              <p>{desc}</p>
            </div>
          ))}
        </div>
      </Panel>

      {/* ── All 5 failure cases ── */}
      <Panel title="Failure Case Analysis — All 5 Cases">
        <div className="failure-cases-list">
          {failures.map((fc, index) => (
            <div className="failure-case-card" key={`${fc.method}-${index}`}>
              <div className="fc-head">
                <span
                  className="fc-category-badge"
                  style={{ borderColor: ERROR_CATEGORY_COLORS[fc.error_category] ?? "var(--muted)", color: ERROR_CATEGORY_COLORS[fc.error_category] ?? "var(--muted)" }}
                >
                  {fc.error_category}
                </span>
                <span className="fc-method">{fc.method}</span>
              </div>
              <p className="fc-question">{fc.question}</p>
              <div className="fc-answers">
                <span className="fc-answer-row">
                  <span className="fc-answer-label">Expected</span>
                  <span className="fc-answer-value is-gold">{fc.expected}</span>
                </span>
                <span className="fc-answer-row">
                  <span className="fc-answer-label">Predicted</span>
                  <span className="fc-answer-value is-wrong">{fc.prediction}</span>
                </span>
              </div>
              <p className="fc-note">{fc.note}</p>
              <p className="fc-suggestion">
                <strong>Suggestion:</strong> {fc.suggestion}
              </p>
            </div>
          ))}
        </div>
      </Panel>

      {/* ── Attention heatmap ── */}
      <Panel title="Attention Heatmap — Relation Salience">
        <div className="heatmap-grid">
          {[0.96, 0.88, 0.72, 0.41, 0.85, 0.67, 0.58, 0.94].map((value) => (
            <div className="heatmap-cell" key={value} style={{ opacity: value }}>
              {value.toFixed(2)}
            </div>
          ))}
        </div>
      </Panel>
    </DashboardShell>
  );
}
