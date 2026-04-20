import { DashboardShell } from "@/components/dashboard-shell";
import { GraphCanvas } from "@/components/graph-canvas";
import { Panel, ProgressBar, StatCard } from "@/components/ui";
import {
  datasetColumns,
  entityDistribution,
  knowledgeGraphStats,
  pathFamilies,
  seedEntities,
} from "@/lib/dashboard-data";
import type { StatCardData } from "@/lib/dashboard-data";

type SeedRow = {
  id: string;
  name: string;
  type: string;
  links: number;
};

type PathItem = {
  label: string;
  value: number;
};

type DatasetSection = {
  title: string;
  items: string[];
};

type EntityDistItem = {
  label: string;
  value: number;
  tone: string;
};

const DIST_TONE_MAP: Record<string, string> = {
  cyan: "var(--signal-cyan)",
  amber: "var(--signal-amber)",
  green: "var(--signal-green)",
  pink: "var(--signal-pink)",
  rose: "var(--signal-rose)",
  blue: "var(--signal-blue)",
};

export function KnowledgeGraphPage({
  stats = knowledgeGraphStats,
  seeds = seedEntities,
  pathItems = pathFamilies,
  datasetSections = datasetColumns,
  entityDist = entityDistribution,
}: Readonly<{
  stats?: StatCardData[];
  seeds?: SeedRow[];
  pathItems?: PathItem[];
  datasetSections?: DatasetSection[];
  entityDist?: EntityDistItem[];
}>) {
  return (
    <DashboardShell active="knowledge-graph">
      <div className="stats-grid">
        {stats.map((card) => (
          <StatCard key={card.label} {...card} />
        ))}
      </div>

      {/* ── Live Neo4j Graph ── */}
      <Panel title="Türkiye Cinema Knowledge Graph — Live from Neo4j Aura">
        <GraphCanvas />
      </Panel>

      {/* ── Entity Distribution + Path Families ── */}
      <div className="two-column">
        <Panel title="Subgraph Entity Type Distribution">
          <div className="entity-dist-list">
            {entityDist.map((item) => {
              const maxVal = entityDist[0]?.value ?? 207;
              const pct = Math.round((item.value / maxVal) * 100);
              return (
                <div className="entity-dist-row" key={item.label}>
                  <span className="entity-dist-label">{item.label}</span>
                  <div className="entity-dist-bar-track">
                    <div
                      className="entity-dist-bar-fill"
                      style={{
                        width: `${pct}%`,
                        background: DIST_TONE_MAP[item.tone] ?? "var(--signal-cyan)",
                      }}
                    />
                  </div>
                  <span className="entity-dist-value">{item.value}</span>
                </div>
              );
            })}
          </div>
        </Panel>

        <Panel title="Path-Rich Relation Families">
          <div className="progress-list">
            {pathItems.map((item) => (
              <ProgressBar
                key={item.label}
                label={item.label}
                value={Math.round((item.value / 585) * 100)}
                suffix={` (${item.value})`}
              />
            ))}
          </div>
        </Panel>
      </div>

      {/* ── Seed Entities ── */}
      <Panel title="Seed Entities — Cinema Domain">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Wikidata ID</th>
                <th>Name</th>
                <th>Type</th>
                <th>Links</th>
              </tr>
            </thead>
            <tbody>
              {seeds.map((row) => (
                <tr key={row.id}>
                  <td>{row.id}</td>
                  <td>{row.name}</td>
                  <td>{row.type}</td>
                  <td>{row.links}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* ── Dataset Summary ── */}
      <Panel title="Verified QA Dataset Summary">
        <div className="dataset-columns">
          {datasetSections.map((column) => (
            <div className="dataset-column" key={column.title}>
              <h3>{column.title}</h3>
              <ul>
                {column.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Panel>
    </DashboardShell>
  );
}
