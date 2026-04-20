import { DashboardShell } from "@/components/dashboard-shell";
import { Panel, StatCard } from "@/components/ui";
import { domainBars, gnnStats, hopTypeMetrics, methodMetrics, questionGrid } from "@/lib/dashboard-data";
import type { StatCardData } from "@/lib/dashboard-data";

type QuestionGridItem = { nr: number; vr: number; vq: number; kg: number };

const METHOD_GRID_CONFIG = [
  { key: "kg" as const, label: "KG-Infused RAG", tone: "var(--signal-green)" },
  { key: "vr" as const, label: "Vanilla RAG", tone: "var(--signal-amber)" },
  { key: "vq" as const, label: "Vanilla QE", tone: "var(--signal-cyan)" },
  { key: "nr" as const, label: "No Retrieval", tone: "var(--signal-rose)" },
];

export function GnnPage({
  stats = gnnStats,
  methods = methodMetrics,
  bars = domainBars,
  hopTypes = hopTypeMetrics,
  questionGrid: qGrid = questionGrid,
}: Readonly<{
  stats?: StatCardData[];
  methods?: typeof methodMetrics;
  bars?: typeof domainBars;
  hopTypes?: typeof hopTypeMetrics;
  questionGrid?: QuestionGridItem[];
}>) {
  return (
    <DashboardShell active="gnn">
      <div className="stats-grid">
        {stats.map((card) => (
          <StatCard key={card.label} {...card} />
        ))}
      </div>

      {/* Pipeline Flow Diagram */}
      <Panel title="KG-Infused RAG — Pipeline Flow">
        <div className="pipeline-flow">
          <div className="pipeline-module mod-amber">
            <div className="pm-badge">Module 1</div>
            <strong>KG-Guided Spreading Activation</strong>
            <p>Seed entity selection → iterative 1-hop expansion → LLM triple selection → activation memory</p>
            <div className="pm-params">k_e = 3 · max_rounds = 6 · Neo4j Aura</div>
          </div>
          <div className="pipeline-arrow">→</div>
          <div className="pipeline-module mod-cyan">
            <div className="pm-badge">Module 2</div>
            <strong>KG-Based Query Expansion</strong>
            <p>KG subgraph summary fed to Groq → expanded query generated → dual-query corpus retrieval</p>
            <div className="pm-params">Groq llama-3.3-70b · 12 RPM paced</div>
          </div>
          <div className="pipeline-arrow">→</div>
          <div className="pipeline-module mod-green">
            <div className="pm-badge">Module 3</div>
            <strong>KG-Augmented Answer Generation</strong>
            <p>Passage note + KG facts → fact-enhanced note → final answer generation conditioned on enriched context</p>
            <div className="pm-params">SQLite corpus · 2 200 docs</div>
          </div>
        </div>
      </Panel>

      <div className="two-column">
        <Panel title="R-GAT Architecture — Conceptual Design">
          <p style={{ margin: "0 0 1rem", fontSize: "0.82rem", color: "var(--muted)" }}>
            Conceptual design for a trainable graph-attention extension. Not trained in this project — KG-Infused RAG uses spreading activation over Neo4j directly.
          </p>
          <div className="architecture-grid">
            <div className="arch-box accent-amber">
              <span>Input</span>
              <strong>629 nodes</strong>
              <small>Entity features + relation tags</small>
            </div>
            <div className="arch-arrow">↓</div>
            <div className="arch-box accent-cyan">
              <span>Layer Stack</span>
              <strong>4 relational blocks</strong>
              <small>Attention over selected relation neighborhoods</small>
            </div>
            <div className="arch-arrow">↓</div>
            <div className="arch-box accent-green">
              <span>Output</span>
              <strong>Answer candidate scores</strong>
              <small>Future extension lane for trainable ranking</small>
            </div>
          </div>
        </Panel>

        <Panel title="Method Comparison — Phase 7 Results">
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Method</th>
                  <th>Acc</th>
                  <th>EM</th>
                  <th>F1</th>
                  <th>Recall</th>
                </tr>
              </thead>
              <tbody>
                {methods.map((row) => (
                  <tr key={row.method}>
                    <td>{row.method}</td>
                    <td>{row.accuracy.toFixed(2)}</td>
                    <td>{row.exactMatch.toFixed(2)}</td>
                    <td>{row.f1.toFixed(2)}</td>
                    <td>{row.recall.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      {/* Question-Type Breakdown — computed from real phase-7 metrics */}
      <Panel title="Question-Type Performance Breakdown (2-hop / 3-hop / Comparison)">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Type</th>
                <th>n</th>
                <th>KG-RAG Acc</th>
                <th>KG-RAG F1</th>
                <th>KG-RAG EM</th>
                <th>Vanilla RAG Acc</th>
                <th>Vanilla RAG F1</th>
                <th>No Retrieval Acc</th>
              </tr>
            </thead>
            <tbody>
              {hopTypes.map((row) => (
                <tr key={row.type}>
                  <td>{row.type}</td>
                  <td>{row.n}</td>
                  <td>{row.kg_acc.toFixed(2)}</td>
                  <td>{row.kg_f1.toFixed(3)}</td>
                  <td>{row.kg_em.toFixed(2)}</td>
                  <td>{row.rag_acc.toFixed(2)}</td>
                  <td>{row.rag_f1.toFixed(3)}</td>
                  <td>{row.nor_acc.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p style={{ margin: "0.75rem 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
          KG-Infused RAG consistently matches or exceeds baselines. The only gap appears in the Education template (film_director_education, n=5), where a missing USC education triple causes 1 failure.
        </p>
      </Panel>

      {/* ── Per-question heatmap ── */}
      <Panel title="Per-Question Accuracy Grid — All 50 Questions × 4 Methods">
        <div className="method-grid-set">
          {METHOD_GRID_CONFIG.map(({ key, label, tone }) => {
            const correct = qGrid.filter((q) => q[key] === 1).length;
            return (
              <div className="method-mini-wrap" key={key}>
                <div className="method-mini-grid">
                  {qGrid.map((q, i) => (
                    <div
                      key={i}
                      className={`q-cell ${q[key] === 1 ? "pass" : "fail"}`}
                      style={q[key] === 1 ? { background: tone } : undefined}
                      title={`Q${i + 1}: ${q[key] === 1 ? "✓" : "✗"}`}
                    />
                  ))}
                </div>
                <div className="method-mini-label">
                  <span style={{ color: tone }}>{label}</span>
                  <strong>{correct} / 50</strong>
                </div>
              </div>
            );
          })}
        </div>
        <p style={{ margin: "0.75rem 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
          Each cell = one question. Green = correct answer, red = wrong. KG-Infused RAG correctly answers 49/50 questions — only one failure caused by a missing Wikidata5M triple.
        </p>
      </Panel>

      <Panel title="Template-Level F1 Profile — KG-Infused RAG vs Vanilla RAG">
        <div className="bar-compare-grid">
          {bars.map((bar) => (
            <div className="bar-compare-item" key={bar.label}>
              <p>{bar.label}</p>
              <div className="dual-bars">
                <div className="dual-bar">
                  <span className="dual-bar-label">KG-RAG</span>
                  <div className="progress-track">
                    <div className="progress-fill tone-green" style={{ width: `${bar.kg * 100}%` }} />
                  </div>
                  <span className="dual-bar-value">{bar.kg.toFixed(2)}</span>
                </div>
                <div className="dual-bar">
                  <span className="dual-bar-label">Vanilla RAG</span>
                  <div className="progress-track">
                    <div className="progress-fill tone-amber" style={{ width: `${bar.rag * 100}%` }} />
                  </div>
                  <span className="dual-bar-value">{bar.rag.toFixed(2)}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
        <p style={{ margin: "0.75rem 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
          Values computed from phase-7 evaluation artifacts. Education gap reflects one KG-missing USC triple (see XAI Evidence page).
        </p>
      </Panel>
    </DashboardShell>
  );
}
