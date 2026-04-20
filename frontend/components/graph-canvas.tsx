"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

type RawNode = { id: string; label: string; roles: string[] };
type RawEdge = { source: string; target: string; relation: string };
type GraphData = { nodes: RawNode[]; edges: RawEdge[]; source: string };

const ROLES = [
  { key: "film",             label: "Film",        color: "#22d3ee" },
  { key: "director",         label: "Director",    color: "#f472b6" },
  { key: "cast_member",      label: "Cast",        color: "#fbbf24" },
  { key: "birth_place",      label: "Birth Place", color: "#4ade80" },
  { key: "country",          label: "Country",     color: "#fb7185" },
  { key: "award",            label: "Award",       color: "#a78bfa" },
  { key: "education_entity", label: "Education",   color: "#60a5fa" },
];

const ROLE_COLOR = Object.fromEntries(ROLES.map((r) => [r.key, r.color]));
const DEFAULT_ROLES = new Set(["film", "director"]);

function nodeColor(roles: string[]): string {
  for (const r of roles) if (ROLE_COLOR[r]) return ROLE_COLOR[r];
  return "#64748b";
}

function primaryRole(roles: string[]): string {
  const order = ["film", "director", "cast_member", "birth_place", "country", "award", "education_entity"];
  for (const r of order) if (roles.includes(r)) return r;
  return roles[0] ?? "unknown";
}

export function GraphCanvas() {
  const [raw, setRaw] = useState<GraphData | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [activeRoles, setActiveRoles] = useState<Set<string>>(new Set(DEFAULT_ROLES));
  const [focusNode, setFocusNode] = useState<string>("");
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(860);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>(undefined);

  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_BACKEND_API_BASE_URL ?? "http://127.0.0.1:8000";
    fetch(`${base}/dashboard/graph-data`, { signal: AbortSignal.timeout(8000) })
      .then((r) => r.json())
      .then((data: GraphData) => {
        if (!data.nodes?.length) { setStatus("error"); return; }
        setRaw(data);
        setStatus("ok");
      })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((e) => setWidth(e[0].contentRect.width || 860));
    ro.observe(containerRef.current);
    setWidth(containerRef.current.clientWidth || 860);
    return () => ro.disconnect();
  }, []);

  // Films that appear in the graph, sorted alphabetically
  const filmOptions = useMemo(() => {
    if (!raw) return [];
    return raw.nodes
      .filter((n) => n.roles.includes("film"))
      .map((n) => n.label)
      .sort((a, b) => a.localeCompare(b));
  }, [raw]);

  const toggleRole = useCallback((key: string) => {
    setActiveRoles((prev) => {
      const next = new Set(prev);
      if (next.has(key)) { if (next.size > 1) next.delete(key); }
      else next.add(key);
      return next;
    });
    setFocusNode("");
  }, []);

  const filteredData = useMemo(() => {
    if (!raw) return { nodes: [], links: [] };

    let nodes: RawNode[];

    if (focusNode) {
      // Focus mode: show only the selected node + its direct neighbors (all types)
      const focal = raw.nodes.find(
        (n) => n.label.toLowerCase() === focusNode.toLowerCase()
      );
      if (focal) {
        const focalId = focal.id;
        const neighborIds = new Set<string>([focalId]);
        for (const e of raw.edges) {
          if (e.source === focalId) neighborIds.add(e.target);
          if (e.target === focalId) neighborIds.add(e.source);
        }
        nodes = raw.nodes.filter((n) => neighborIds.has(n.id));
      } else {
        nodes = raw.nodes.filter((n) => n.roles.some((r) => activeRoles.has(r)));
      }
    } else {
      nodes = raw.nodes.filter((n) => n.roles.some((r) => activeRoles.has(r)));
    }

    const visibleIds = new Set(nodes.map((n) => n.id));
    const links = raw.edges
      .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, label: e.relation }));

    return {
      nodes: nodes.map((n) => ({
        id: n.id,
        label: n.label,
        role: primaryRole(n.roles),
        color: (focusNode && n.label.toLowerCase() === focusNode.toLowerCase())
          ? "#ffffff"
          : nodeColor(n.roles),
      })),
      links,
    };
  }, [raw, activeRoles, focusNode]);

  const nodeCount = filteredData.nodes.length;
  const edgeCount = filteredData.links.length;
  const showLabels = nodeCount <= 60;

  return (
    <div className="graph-canvas-wrap">
      {/* Role filter chips */}
      <div className="graph-controls-row">
        <div className="graph-legend-row">
          {ROLES.map((r) => (
            <button
              key={r.key}
              className={`graph-legend-pill${activeRoles.has(r.key) ? " active" : " muted"}`}
              onClick={() => toggleRole(r.key)}
              title={`Toggle ${r.label} nodes`}
            >
              <span className="graph-legend-dot" style={{ background: activeRoles.has(r.key) ? r.color : "#334155" }} />
              {r.label}
            </button>
          ))}
        </div>

        <div className="graph-focus-row">
          <span className="graph-focus-label">Focus film</span>
          <select
            className="graph-focus-select"
            value={focusNode}
            onChange={(e) => {
              setFocusNode(e.target.value);
              if (e.target.value) setActiveRoles(new Set(ROLES.map((r) => r.key)));
            }}
          >
            <option value="">— select a film —</option>
            {filmOptions.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
          {focusNode && (
            <button
              className="graph-clear-btn"
              onClick={() => { setFocusNode(""); setActiveRoles(new Set(DEFAULT_ROLES)); }}
            >
              ✕ Clear
            </button>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="graph-stats-bar">
        <span>
          Showing <strong>{nodeCount}</strong> nodes · <strong>{edgeCount}</strong> edges
          {focusNode && <span className="graph-focus-hint"> — 1-hop neighborhood of <em>{focusNode}</em></span>}
        </span>
        {raw?.source && <span className="graph-source-tag">source: {raw.source}</span>}
      </div>

      {/* Graph */}
      <div ref={containerRef} className="graph-fg-wrap">
        {status === "loading" && (
          <div className="graph-status-overlay">Fetching graph from Neo4j Aura…</div>
        )}
        {status === "error" && (
          <div className="graph-status-overlay">
            Backend unavailable — start the backend and reload to view the live graph.
          </div>
        )}
        {status === "ok" && (
          <ForceGraph2D
            key={`${[...activeRoles].sort().join(",")}-${focusNode}`}
            ref={graphRef}
            graphData={filteredData}
            width={width}
            height={500}
            backgroundColor="transparent"
            nodeLabel="label"
            nodeColor="color"
            nodeRelSize={5}
            nodeCanvasObject={(node: Record<string, unknown>, ctx: CanvasRenderingContext2D, globalScale: number) => {
              const x = node.x as number;
              const y = node.y as number;
              const color = node.color as string;
              const label = node.label as string;
              const isFocal = !!focusNode && label.toLowerCase() === focusNode.toLowerCase();
              const r = isFocal ? 8 : Math.max(3, 5 - globalScale * 0.3);
              ctx.beginPath();
              ctx.arc(x, y, r, 0, 2 * Math.PI);
              ctx.fillStyle = color;
              ctx.fill();
              if (isFocal) {
                ctx.strokeStyle = "#ffffff";
                ctx.lineWidth = 2;
                ctx.stroke();
              }
              if (showLabels || isFocal || globalScale > 2.5) {
                const fs = Math.min(13, Math.max(8, 11 / Math.max(globalScale, 1)));
                ctx.font = `${isFocal ? "bold " : ""}${fs}px sans-serif`;
                ctx.fillStyle = isFocal ? "#ffffff" : "rgba(255,255,255,0.82)";
                const text = label.length > 26 ? label.slice(0, 24) + "…" : label;
                ctx.fillText(text, x + r + 2, y + fs * 0.35);
              }
            }}
            linkColor={() => "rgba(255,255,255,0.08)"}
            linkWidth={focusNode ? 1.2 : 0.6}
            linkDirectionalArrowLength={focusNode ? 5 : 2}
            linkDirectionalArrowRelPos={1}
            linkLabel="label"
            cooldownTicks={focusNode ? 80 : 150}
            d3AlphaDecay={focusNode ? 0.04 : 0.025}
            d3VelocityDecay={0.4}
          />
        )}
      </div>

      <p className="graph-hint">
        Scroll to zoom · Drag to pan · Hover a node for its name
        {nodeCount > 100 && " · Add filters above to reduce clutter"}
      </p>
    </div>
  );
}
