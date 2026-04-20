"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

type HeaderStat = {
  label: string;
  value: string;
  hint: string;
  tone: "cyan" | "green" | "amber" | "pink";
};

type QuickPromptGroup = {
  key: string;
  label: string;
  description: string;
  tone: "cyan" | "green" | "amber" | "pink";
  prompts: string[];
};

type BootstrapPayload = {
  branding: {
    product_name: string;
    product_tagline: string;
    assistant_name: string;
    assistant_subtitle: string;
    status_label: string;
  };
  default_method: "kg_rag";
  quick_prompts: string[];
  quick_prompt_groups?: QuickPromptGroup[];
  graph_legend: Array<{ key: string; label: string; color: string }>;
  header_stats: HeaderStat[];
  quota_status: {
    configured: boolean;
    paused_for_rest_of_day: boolean;
    pause_state?: { reason?: string; resume_on_date?: string } | null;
    runtime_status?: {
      state?: {
        cooldown_until?: string | null;
      };
      cooldown_active?: boolean;
      request_pacing_rpm?: number;
    };
    snapshot?: {
      model?: string;
      remaining_requests?: number;
      remaining_tokens?: number;
    };
  };
};

type GraphNode = {
  id: string;
  label: string;
  canonical_name: string;
  description: string;
  roles: string[];
  kind: string;
  role: string;
  why_selected: string;
  linked_passages: string[];
  depth: number;
  order: number;
};

type GraphEdge = {
  id: string;
  source: string;
  target: string;
  relation_id: string;
  relation_label: string;
  role: string;
  score?: number;
};

type EvidenceGraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  active_node_id: string | null;
  legend: Array<{ key: string; label: string; color: string }>;
};

type EvidencePanel = {
  seed_entities: Array<{ entity_id?: string; entity_name: string; roles?: string[]; source?: string }>;
  selected_triples: Array<{
    source_name: string;
    relation_label: string;
    target_name: string;
    relation_id?: string;
  }>;
  expanded_query?: string | null;
  cypher_queries: Array<{
    label: string;
    purpose?: string;
    query: string;
    readable_query?: string;
    technical_query?: string;
    parameters?: Record<string, unknown>;
  }>;
  retrieved_documents: Array<{
    doc_id?: string;
    title?: string;
    snippet?: string;
    source_kind?: string;
  }>;
  answer_basis?: string | null;
};

type CypherQuery = EvidencePanel["cypher_queries"][number];

type ChatTurn = {
  turn_id: string;
  created_at?: string;
  updated_at?: string;
  status: string;
  method: string;
  user_message: string;
  assistant_message: string;
  error?: string | null;
  quota_snapshot?: Record<string, unknown> | null;
  evidence_graph?: EvidenceGraph | null;
  evidence_panel?: EvidencePanel | null;
};

type ChatSession = {
  session_id: string;
  created_at: string;
  updated_at: string;
  turns: ChatTurn[];
  latest_graph?: EvidenceGraph | null;
  latest_evidence?: EvidencePanel | null;
  latest_turn_id?: string | null;
  quota_status?: BootstrapPayload["quota_status"] | null;
};

type StreamEventPayloads = {
  ack: { session_id: string; method: string };
  turn_started: { session_id: string; turn: ChatTurn; session?: ChatSession; quota_status?: BootstrapPayload["quota_status"] };
  seed_entities: { seed_entities: EvidencePanel["seed_entities"]; graph?: EvidenceGraph };
  activation_round: { round: { round_index: number; selected_triples: EvidencePanel["selected_triples"] } };
  graph_patch: { graph: EvidenceGraph };
  expanded_query: { expanded_query: string };
  cypher_trace: { cypher_queries: EvidencePanel["cypher_queries"] };
  retrieved_documents: { retrieved_documents: EvidencePanel["retrieved_documents"] };
  answer_delta: { delta: string; assistant_message: string };
  turn_completed: { session: ChatSession; turn: ChatTurn };
  error: { error?: string; turn?: ChatTurn; session?: ChatSession };
  quota_status: { quota_status: BootstrapPayload["quota_status"] };
};

const GRAPH_WIDTH = 920;
const GRAPH_HEIGHT = 640;

const FALLBACK_BOOTSTRAP: BootstrapPayload = {
  branding: {
    product_name: "Turkiye Cinema KG-RAG",
    product_tagline: "Wikidata5M x Neo4j x Groq",
    assistant_name: "Graph-RAG AI Assistant",
    assistant_subtitle: "Live KG-guided reasoning over the Turkiye cinema domain",
    status_label: "Backend required",
  },
  default_method: "kg_rag",
  quick_prompts: [
    "Where was the director of Aci Zafer born?",
    "Which award was received by the director of Bir Avuç Toprak?",
    "Where did the director of Ember study?",
    "Were the directors of Ah Nerede and Arabesk born in the same country?",
  ],
  quick_prompt_groups: [
    {
      key: "verified",
      label: "Verified dataset prompts",
      description: "Questions sampled from the validated Phase 4 dataset.",
      tone: "green",
      prompts: [
        "Where was the director of Aci Zafer born?",
        "Which award was received by the director of Bir Avuç Toprak?",
        "Where did the director of Ember study?",
        "Were the directors of Ah Nerede and Arabesk born in the same country?",
      ],
    },
    {
      key: "exploratory",
      label: "Exploratory edge cases",
      description: "Questions that are useful for testing graph coverage and may return unknown.",
      tone: "amber",
      prompts: [
        "Kemal Sunal nerede doğmuştur?",
        "Did the directors of Aci Zafer and Arabesk study in the same country?",
        "Where did the cast member of Arabesk study?",
      ],
    },
  ],
  graph_legend: [
    { key: "film", label: "Film", color: "#19e4ff" },
    { key: "person", label: "Person", color: "#8b5cf6" },
    { key: "answer_path", label: "Answer Path", color: "#18f58f" },
  ],
  header_stats: [
    { label: "Primary Model", value: "openai/gpt-oss-120b", hint: "Backend connection required", tone: "cyan" },
    { label: "Best Phase 7 F1", value: "0.98", hint: "Saved experiment result", tone: "green" },
    { label: "Quota Left", value: "?", hint: "Live quota appears after connect", tone: "amber" },
    { label: "Question Memory", value: "Adaptive", hint: "Used only for follow-up questions", tone: "pink" },
  ],
  quota_status: {
    configured: false,
    paused_for_rest_of_day: false,
    runtime_status: { cooldown_active: false, request_pacing_rpm: 12 },
    snapshot: { model: "openai/gpt-oss-120b" },
  },
};

function backendBaseUrl() {
  return process.env.NEXT_PUBLIC_BACKEND_API_BASE_URL ?? "http://127.0.0.1:8000";
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${backendBaseUrl()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(`Request failed with ${response.status}`);
  }
  return (await response.json()) as T;
}

function emptySession(sessionId: string): ChatSession {
  const now = new Date().toISOString();
  return {
    session_id: sessionId,
    created_at: now,
    updated_at: now,
    turns: [],
    latest_graph: null,
    latest_evidence: emptyEvidencePanel(),
    latest_turn_id: null,
    quota_status: FALLBACK_BOOTSTRAP.quota_status,
  };
}

function emptyEvidencePanel(): EvidencePanel {
  return {
    seed_entities: [],
    selected_triples: [],
    expanded_query: "",
    cypher_queries: [],
    retrieved_documents: [],
    answer_basis: "",
  };
}

function classForTone(tone: HeaderStat["tone"]) {
  return `live-chat-stat tone-${tone}`;
}

function nodeColor(node: GraphNode) {
  switch (node.kind) {
    case "film":
      return "#19e4ff";
    case "person":
      return "#8b5cf6";
    case "school":
      return "#18f58f";
    case "place":
      return "#f59e0b";
    case "award":
      return "#ff5d6d";
    case "country":
      return "#ffd166";
    default:
      return "#5f789d";
  }
}

function edgeColor(edge: GraphEdge, focusedRole: string) {
  if (focusedRole === "seeds" && edge.role !== "answer_path") {
    return "rgba(80, 103, 136, 0.35)";
  }
  if (focusedRole === "answer_path" && edge.role !== "answer_path") {
    return "rgba(80, 103, 136, 0.28)";
  }
  if (edge.role === "answer_path") {
    return "#18f58f";
  }
  return "rgba(155, 176, 209, 0.4)";
}

function layoutGraph(graph: EvidenceGraph | null) {
  if (!graph || graph.nodes.length === 0) {
    return new Map<string, { x: number; y: number }>();
  }

  const groups = new Map<number, GraphNode[]>();
  graph.nodes.forEach((node) => {
    const depth = Number.isFinite(node.depth) ? node.depth : 0;
    const bucket = groups.get(depth) ?? [];
    bucket.push(node);
    groups.set(depth, bucket);
  });

  const sortedDepths = [...groups.keys()].sort((a, b) => a - b);
  const positions = new Map<string, { x: number; y: number }>();

  sortedDepths.forEach((depth, depthIndex) => {
    const nodes = (groups.get(depth) ?? []).sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));
    const x =
      sortedDepths.length === 1
        ? GRAPH_WIDTH / 2
        : 120 + (depthIndex * (GRAPH_WIDTH - 240)) / Math.max(sortedDepths.length - 1, 1);
    const gap = GRAPH_HEIGHT / (nodes.length + 1);
    nodes.forEach((node, index) => {
      const y = gap * (index + 1);
      const wave = ((index % 2 === 0 ? 1 : -1) * (depthIndex % 2 === 0 ? 18 : 24));
      positions.set(node.id, { x, y: y + wave });
    });
  });

  return positions;
}

async function streamSse(
  path: string,
  body: Record<string, unknown>,
  onEvent: <K extends keyof StreamEventPayloads>(eventName: K, payload: StreamEventPayloads[K]) => void,
) {
  const response = await fetch(`${backendBaseUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    throw new Error(`Streaming request failed with ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";

    for (const chunk of chunks) {
      const eventName = chunk
        .split("\n")
        .find((line) => line.startsWith("event: "))
        ?.replace("event: ", "")
        .trim() as keyof StreamEventPayloads | undefined;
      const dataText = chunk
        .split("\n")
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.replace("data: ", ""))
        .join("\n");

      if (!eventName || !dataText) {
        continue;
      }

      onEvent(eventName, JSON.parse(dataText));
    }

    if (done) {
      break;
    }
  }
}

function formatTime(value?: string) {
  if (!value) {
    return "now";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "now";
  }
  return parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function CypherQueryBlock({ query }: Readonly<{ query: CypherQuery }>) {
  return (
    <div className="cypher-readable-block">
      <div className="cypher-readable-note">Live Neo4j query shown in a readable form with real entity names and relation labels.</div>
      <pre className="code">
        <code>{query.readable_query ?? query.query}</code>
      </pre>
    </div>
  );
}

function UserAvatarGem() {
  return (
    <svg aria-hidden="true" fill="none" viewBox="0 0 22 22" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="user-gem-frame" x1="0%" x2="100%" y1="0%" y2="100%">
          <stop offset="0%" stopColor="#ff5d8f" />
          <stop offset="100%" stopColor="#ffbf47" />
        </linearGradient>
        <linearGradient id="user-gem-core" x1="100%" x2="0%" y1="0%" y2="100%">
          <stop offset="0%" stopColor="#9d6fff" stopOpacity="0.7" />
          <stop offset="100%" stopColor="#19e4ff" stopOpacity="0.6" />
        </linearGradient>
      </defs>
      <rect fill="url(#user-gem-frame)" height="22" opacity="0.22" rx="6" width="22" />
      <polygon
        fill="none"
        opacity="0.8"
        points="11,3 19,8 19,14 11,19 3,14 3,8"
        stroke="url(#user-gem-frame)"
        strokeWidth="1.3"
      />
      <circle cx="11" cy="11" fill="url(#user-gem-core)" opacity="0.9" r="3.5" />
      <circle cx="11" cy="11" fill="#ffbf47" opacity="0.75" r="1.5" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg aria-hidden="true" fill="none" height="14" viewBox="0 0 14 14" width="14" xmlns="http://www.w3.org/2000/svg">
      <path d="M7 2.5V11.5M2.5 7H11.5" stroke="currentColor" strokeLinecap="round" strokeWidth="1.6" />
    </svg>
  );
}

function SendArrowIcon() {
  return (
    <svg aria-hidden="true" fill="none" height="15" viewBox="0 0 15 15" width="15" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M7.5 13V2M3 6.5L7.5 2L12 6.5"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.7"
      />
    </svg>
  );
}

function MessageList({
  turns,
  activeTurnId,
  streamedAssistantMessage,
  streamedCypherQueries,
  isStreaming,
}: Readonly<{
  turns: ChatTurn[];
  activeTurnId: string | null;
  streamedAssistantMessage: string;
  streamedCypherQueries: EvidencePanel["cypher_queries"];
  isStreaming: boolean;
}>) {
  if (turns.length === 0) {
    return (
      <div className="live-chat-empty-thread turn">
        <div className="msg-assistant">
          <div className="msg-meta">
            <div className="avatar avatar-assistant">KG</div>
            <span className="msg-name">Graph-RAG</span>
            <span className="msg-time">Ready</span>
          </div>
          <div className="bubble">
            Ask a free-form question about the Turkiye cinema graph. The answer will stream live, the graph will reset
            for the active turn, and the Cypher trace will be preserved inside the thread.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="live-chat-thread-list thread-inner">
      {turns.map((turn) => {
        const assistantText =
          activeTurnId === turn.turn_id && streamedAssistantMessage
            ? streamedAssistantMessage
            : turn.assistant_message;
        const cypherQueries =
          activeTurnId === turn.turn_id && streamedCypherQueries.length > 0
            ? streamedCypherQueries
            : turn.evidence_panel?.cypher_queries ?? [];
        return (
          <div className="turn" key={turn.turn_id}>
            <div className="msg-user">
              <div className="msg-meta">
                <span className="msg-time">{formatTime(turn.created_at)}</span>
                <div className="avatar avatar-user">
                  <UserAvatarGem />
                </div>
              </div>
              <div className="bubble">{turn.user_message}</div>
            </div>

            <div className="msg-assistant">
              <div className="msg-meta">
                <div className="avatar avatar-assistant">KG</div>
                <span className="msg-name">Graph-RAG</span>
                <span className="msg-time">
                  {turn.status}
                  {" · "}
                  {formatTime(turn.updated_at ?? turn.created_at)}
                </span>
              </div>
              <div className="bubble">
                {assistantText || (activeTurnId === turn.turn_id && isStreaming ? <TypingDots /> : "Waiting for response...")}
              </div>
              {cypherQueries.length > 0 ? (
                <details className="inline-trace">
                  <summary>
                    <span className="trace-chevron" />
                    <span className="trace-label">Cypher trace</span>
                  </summary>
                  <div className="inline-trace-body">
                    {cypherQueries.map((query, index) => (
                      <div className="inline-trace-block" key={`${turn.turn_id}-${query.label}-${index}`}>
                        <div className="trace-block-head">
                          <strong>{query.label}</strong>
                          {query.purpose ? <p>{query.purpose}</p> : null}
                        </div>
                        <CypherQueryBlock query={query} />
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function TypingDots() {
  return (
    <div className="live-chat-typing">
      <span />
      <span />
      <span />
    </div>
  );
}

function PromptLibrary({
  groups,
  isOpen,
  onToggle,
  onPickPrompt,
}: Readonly<{
  groups: QuickPromptGroup[];
  isOpen: boolean;
  onToggle: () => void;
  onPickPrompt: (prompt: string) => void;
}>) {
  return (
    <div className={`prompt-library ${isOpen ? "is-open" : ""}`}>
      <button
        className={`prompt-library-trigger ${isOpen ? "is-open" : ""}`}
        onClick={onToggle}
        type="button"
      >
        <span>Prompt library</span>
        <span className="prompt-library-meta">
          {groups.reduce((total, group) => total + group.prompts.length, 0)} prompts
        </span>
      </button>

      {isOpen ? (
        <div className="prompt-library-popover">
          {groups.map((group, index) => (
            <details className="prompt-library-group" key={group.key} open={index === 0}>
              <summary>
                <span className={`prompt-library-tone tone-${group.tone}`} />
                <span className="prompt-library-group-text">
                  <strong>{group.label}</strong>
                  <small>{group.description}</small>
                </span>
                <span className="prompt-library-count">{group.prompts.length}</span>
              </summary>
              <div className="prompt-library-list">
                {group.prompts.map((prompt) => (
                  <button
                    className={`prompt-library-item tone-${group.tone}`}
                    key={`${group.key}-${prompt}`}
                    onClick={() => onPickPrompt(prompt)}
                    type="button"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </details>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function EvidenceGraphView({
  graph,
  selectedNodeId,
  onSelectNode,
  focusMode,
}: Readonly<{
  graph: EvidenceGraph | null;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  focusMode: "all" | "seeds" | "answer_path";
}>) {
  const positions = useMemo(() => layoutGraph(graph), [graph]);
  const [viewport, setViewport] = useState({ x: 0, y: 0, scale: 1 });
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);
  const draggingRef = useRef<{ active: boolean; x: number; y: number } | null>(null);

  useEffect(() => {
    setViewport({ x: 0, y: 0, scale: 1 });
  }, [graph?.active_node_id]);

  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="graph-stage">
        <div className="graph-head">
          <div className="graph-actions">
            <button className="gact-btn" type="button">
              +
            </button>
            <button className="gact-btn" type="button">
              -
            </button>
            <button className="gact-btn" type="button">
              Fit
            </button>
          </div>
          <span className="graph-readout">Hover an edge</span>
        </div>
        <div className="graph-canvas">
          <div className="graph-empty-label">
            <div>
              <strong>Live Evidence Graph</strong>
              <p>Shows seed entities, selected triples, and the answer path for the active question.</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const activeNodeId = selectedNodeId ?? graph.active_node_id ?? graph.nodes[0]?.id ?? null;
  const activeEdge = graph.edges.find((edge) => edge.id === hoveredEdgeId) ?? null;

  return (
    <div className="graph-stage">
      <div className="graph-head">
        <div className="graph-actions">
          <button className="gact-btn" type="button" onClick={() => setViewport((state) => ({ ...state, scale: state.scale + 0.12 }))}>
            +
          </button>
          <button className="gact-btn" type="button" onClick={() => setViewport((state) => ({ ...state, scale: Math.max(0.6, state.scale - 0.12) }))}>
            -
          </button>
          <button className="gact-btn" type="button" onClick={() => setViewport({ x: 0, y: 0, scale: 1 })}>
            Fit
          </button>
        </div>
        <span className="graph-readout">
          {activeEdge ? `${activeEdge.relation_label} | ${activeEdge.role.replaceAll("_", " ")}` : "Hover an edge"}
        </span>
      </div>

      <div
        className="graph-canvas"
        onMouseDown={(event) => {
          draggingRef.current = { active: true, x: event.clientX, y: event.clientY };
        }}
        onMouseMove={(event) => {
          if (!draggingRef.current?.active) {
            return;
          }
          const deltaX = event.clientX - draggingRef.current.x;
          const deltaY = event.clientY - draggingRef.current.y;
          draggingRef.current = { active: true, x: event.clientX, y: event.clientY };
          setViewport((state) => ({ ...state, x: state.x + deltaX, y: state.y + deltaY }));
        }}
        onMouseUp={() => {
          draggingRef.current = null;
        }}
        onMouseLeave={() => {
          draggingRef.current = null;
        }}
      >
        <svg className="graph-svg" preserveAspectRatio="xMidYMid meet" viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`}>
          <g transform={`translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`}>
            {graph.edges.map((edge) => {
              const source = positions.get(edge.source);
              const target = positions.get(edge.target);
              if (!source || !target) {
                return null;
              }
              return (
                <line
                  className={`live-chat-edge ${edge.role === "answer_path" ? "is-answer" : ""}`}
                  key={edge.id}
                  onMouseEnter={() => setHoveredEdgeId(edge.id)}
                  onMouseLeave={() => setHoveredEdgeId(null)}
                  stroke={edgeColor(edge, focusMode)}
                  strokeDasharray={edge.role === "answer_path" ? "0" : "5 5"}
                  strokeWidth={edge.role === "answer_path" ? 3 : 2}
                  x1={source.x}
                  x2={target.x}
                  y1={source.y}
                  y2={target.y}
                />
              );
            })}

            {graph.nodes.map((node) => {
              const point = positions.get(node.id);
              if (!point) {
                return null;
              }
              const radius = node.role === "answer" ? 34 : node.role === "seed" ? 32 : 26;
              const isDimmed =
                focusMode === "seeds"
                  ? node.role !== "seed" && node.role !== "answer"
                  : focusMode === "answer_path"
                    ? node.role !== "answer" && node.role !== "seed"
                    : false;
              return (
                <g
                  className={`live-chat-node ${activeNodeId === node.id ? "is-active" : ""} ${isDimmed ? "is-dimmed" : ""}`}
                  key={node.id}
                  onClick={() => onSelectNode(node.id)}
                >
                  <circle cx={point.x} cy={point.y} fill="rgba(7, 17, 29, 0.95)" r={radius} stroke={nodeColor(node)} strokeWidth={3} />
                  <circle cx={point.x} cy={point.y} fill={nodeColor(node)} opacity={0.12} r={radius + 10} />
                  <text x={point.x} y={point.y + radius + 20}>
                    {node.label}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
    </div>
  );
}

export function ChatPage() {
  const [bootstrap, setBootstrap] = useState<BootstrapPayload>(FALLBACK_BOOTSTRAP);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [currentGraph, setCurrentGraph] = useState<EvidenceGraph | null>(null);
  const [currentEvidence, setCurrentEvidence] = useState<EvidencePanel | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamedAssistantMessage, setStreamedAssistantMessage] = useState("");
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [focusMode, setFocusMode] = useState<"all" | "seeds" | "answer_path">("all");
  const [isPromptLibraryOpen, setIsPromptLibraryOpen] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(400);
  const [viewportWidth, setViewportWidth] = useState(() =>
    typeof window !== "undefined" ? window.innerWidth : 1440,
  );
  const sessionIdRef = useRef<string | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const resizingRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function initialise() {
      setIsLoading(true);
      try {
        const loadedBootstrap = await fetchJson<BootstrapPayload>("/chat/bootstrap");
        if (cancelled) {
          return;
        }
        setBootstrap(loadedBootstrap);
        const nextSession = await fetchJson<ChatSession>("/chat/sessions", { method: "POST" });
        if (cancelled) {
          return;
        }
        sessionIdRef.current = nextSession.session_id;
        setSession(nextSession);
        setCurrentGraph(nextSession.latest_graph ?? null);
        setCurrentEvidence(nextSession.latest_evidence ?? emptyEvidencePanel());
        setSelectedNodeId(nextSession.latest_graph?.active_node_id ?? null);
      } catch (error) {
        if (!cancelled) {
          setErrorMessage(error instanceof Error ? error.message : "Failed to connect to the backend.");
          const localSession = emptySession("preview_session");
          setSession(localSession);
          setCurrentGraph(localSession.latest_graph ?? null);
          setCurrentEvidence(localSession.latest_evidence ?? emptyEvidencePanel());
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void initialise();
    return () => {
      cancelled = true;
    };
  }, []);

  const activeNode = useMemo(() => {
    if (!currentGraph) {
      return null;
    }
    const fallbackId = currentGraph.active_node_id ?? currentGraph.nodes[0]?.id ?? null;
    return currentGraph.nodes.find((node) => node.id === (selectedNodeId ?? fallbackId)) ?? null;
  }, [currentGraph, selectedNodeId]);

  const turns = session?.turns ?? [];
  const promptGroups =
    bootstrap.quick_prompt_groups && bootstrap.quick_prompt_groups.length > 0
      ? bootstrap.quick_prompt_groups
      : FALLBACK_BOOTSTRAP.quick_prompt_groups ?? [];
  const isCompactLayout = viewportWidth <= 1180;
  const sidebarMaxWidth = Math.max(440, Math.min(680, Math.floor(viewportWidth * 0.45)));
  const effectiveSidebarWidth = Math.min(Math.max(sidebarWidth, 400), sidebarMaxWidth);
  const quotaStatus = session?.quota_status ?? bootstrap.quota_status;
  const inputBlocked = isStreaming || quotaStatus?.paused_for_rest_of_day;
  const statusToneClass = quotaStatus?.paused_for_rest_of_day
    ? "is-paused"
    : quotaStatus?.runtime_status?.cooldown_active
      ? "is-cooldown"
      : "is-online";
  const statusLabel = quotaStatus?.paused_for_rest_of_day
    ? "Paused"
    : quotaStatus?.runtime_status?.cooldown_active
      ? "Cooldown"
      : "Online";

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) {
      return;
    }
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`;
  }, [input]);

  useEffect(() => {
    const element = threadRef.current;
    if (!element) {
      return;
    }
    element.scrollTop = element.scrollHeight;
  }, [turns.length, streamedAssistantMessage, isLoading]);

  useEffect(() => {
    const handleResize = () => {
      setViewportWidth(window.innerWidth);
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  useEffect(() => {
    setSidebarWidth((current) => Math.min(Math.max(current, 400), sidebarMaxWidth));
  }, [sidebarMaxWidth]);

  useEffect(() => {
    if (isCompactLayout) {
      resizingRef.current = false;
      return;
    }

    const handlePointerMove = (event: MouseEvent) => {
      if (!resizingRef.current || !workspaceRef.current) {
        return;
      }
      const bounds = workspaceRef.current.getBoundingClientRect();
      const nextWidth = event.clientX - bounds.left;
      setSidebarWidth(Math.min(Math.max(Math.round(nextWidth), 400), sidebarMaxWidth));
    };

    const stopResizing = () => {
      resizingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    window.addEventListener("mousemove", handlePointerMove);
    window.addEventListener("mouseup", stopResizing);
    return () => {
      window.removeEventListener("mousemove", handlePointerMove);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [isCompactLayout, sidebarMaxWidth]);

  async function ensureSession() {
    if (sessionIdRef.current) {
      return sessionIdRef.current;
    }
    const nextSession = await fetchJson<ChatSession>("/chat/sessions", { method: "POST" });
    sessionIdRef.current = nextSession.session_id;
    setSession(nextSession);
    return nextSession.session_id;
  }

  async function handleNewChat() {
    if (isStreaming) {
      return;
    }
    setErrorMessage(null);
    setStreamedAssistantMessage("");
    setActiveTurnId(null);
    setFocusMode("all");
    setCurrentGraph(null);
    setSelectedNodeId(null);
    setCurrentEvidence(emptyEvidencePanel());
    setInput("");
    setIsPromptLibraryOpen(false);
    try {
      const nextSession = await fetchJson<ChatSession>("/chat/sessions", { method: "POST" });
      sessionIdRef.current = nextSession.session_id;
      setSession(nextSession);
      setCurrentGraph(nextSession.latest_graph ?? null);
      setCurrentEvidence(nextSession.latest_evidence ?? emptyEvidencePanel());
      setSelectedNodeId(nextSession.latest_graph?.active_node_id ?? null);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not start a new chat session.");
      const localSession = emptySession(`preview_${Date.now()}`);
      sessionIdRef.current = localSession.session_id;
      setSession(localSession);
    }
  }

  async function handleSend(messageText: string) {
    const message = messageText.trim();
    if (!message || inputBlocked) {
      return;
    }
    setErrorMessage(null);
    setIsPromptLibraryOpen(false);
    setStreamedAssistantMessage("");
    setActiveTurnId(null);
    setIsStreaming(true);
    setFocusMode("all");
    setCurrentGraph(null);
    setSelectedNodeId(null);
    setCurrentEvidence(emptyEvidencePanel());

    try {
      const sessionId = await ensureSession();
      await streamSse(
        `/chat/sessions/${sessionId}/messages/stream`,
        {
          message,
          method: bootstrap.default_method,
          stream: true,
        },
        (eventName, payload) => {
          switch (eventName) {
            case "turn_started":
              {
                const turnStarted = payload as StreamEventPayloads["turn_started"];
                if (turnStarted.session) {
                setSession(turnStarted.session);
              }
              setActiveTurnId(turnStarted.turn.turn_id);
              setStreamedAssistantMessage("");
              setCurrentGraph(null);
              setSelectedNodeId(null);
              setCurrentEvidence(emptyEvidencePanel());
              const nextQuota = turnStarted.quota_status;
              if (nextQuota) {
                setBootstrap((state) => ({ ...state, quota_status: nextQuota }));
                }
              }
              break;
            case "seed_entities":
              {
                const seedPayload = payload as StreamEventPayloads["seed_entities"];
                setCurrentEvidence((state) => ({
                  seed_entities: seedPayload.seed_entities,
                  selected_triples: state?.selected_triples ?? [],
                  expanded_query: state?.expanded_query ?? "",
                  cypher_queries: state?.cypher_queries ?? [],
                  retrieved_documents: state?.retrieved_documents ?? [],
                  answer_basis: state?.answer_basis ?? "",
                }));
                if (seedPayload.graph) {
                  setCurrentGraph(seedPayload.graph);
                  setSelectedNodeId(seedPayload.graph.active_node_id ?? null);
                }
              }
              break;
            case "activation_round":
              {
                const roundPayload = payload as StreamEventPayloads["activation_round"];
                setCurrentEvidence((state) => ({
                  seed_entities: state?.seed_entities ?? [],
                  selected_triples: [
                    ...(state?.selected_triples ?? []),
                    ...roundPayload.round.selected_triples,
                  ],
                  expanded_query: state?.expanded_query ?? "",
                  cypher_queries: state?.cypher_queries ?? [],
                  retrieved_documents: state?.retrieved_documents ?? [],
                  answer_basis: state?.answer_basis ?? "",
                }));
              }
              break;
            case "graph_patch":
              {
                const graphPayload = payload as StreamEventPayloads["graph_patch"];
                setCurrentGraph(graphPayload.graph);
                setSelectedNodeId((current) => current ?? graphPayload.graph.active_node_id ?? null);
              }
              break;
            case "expanded_query":
              {
                const expandedPayload = payload as StreamEventPayloads["expanded_query"];
                setCurrentEvidence((state) => ({
                  seed_entities: state?.seed_entities ?? [],
                  selected_triples: state?.selected_triples ?? [],
                  expanded_query: expandedPayload.expanded_query,
                  cypher_queries: state?.cypher_queries ?? [],
                  retrieved_documents: state?.retrieved_documents ?? [],
                  answer_basis: state?.answer_basis ?? "",
                }));
              }
              break;
            case "cypher_trace":
              {
                const cypherPayload = payload as StreamEventPayloads["cypher_trace"];
                setCurrentEvidence((state) => ({
                  seed_entities: state?.seed_entities ?? [],
                  selected_triples: state?.selected_triples ?? [],
                  expanded_query: state?.expanded_query ?? "",
                  cypher_queries: cypherPayload.cypher_queries,
                  retrieved_documents: state?.retrieved_documents ?? [],
                  answer_basis: state?.answer_basis ?? "",
                }));
              }
              break;
            case "retrieved_documents":
              {
                const retrievedPayload = payload as StreamEventPayloads["retrieved_documents"];
                setCurrentEvidence((state) => ({
                  seed_entities: state?.seed_entities ?? [],
                  selected_triples: state?.selected_triples ?? [],
                  expanded_query: state?.expanded_query ?? "",
                  cypher_queries: state?.cypher_queries ?? [],
                  retrieved_documents: retrievedPayload.retrieved_documents,
                  answer_basis: state?.answer_basis ?? "",
                }));
              }
              break;
            case "answer_delta":
              {
                const answerPayload = payload as StreamEventPayloads["answer_delta"];
                setStreamedAssistantMessage(answerPayload.assistant_message);
              }
              break;
            case "turn_completed":
              {
                const completedPayload = payload as StreamEventPayloads["turn_completed"];
                setSession(completedPayload.session);
                setCurrentGraph(
                  completedPayload.turn.evidence_graph ?? completedPayload.session.latest_graph ?? null,
                );
                setCurrentEvidence(
                  completedPayload.turn.evidence_panel ?? completedPayload.session.latest_evidence ?? emptyEvidencePanel(),
                );
                setSelectedNodeId(
                  completedPayload.turn.evidence_graph?.active_node_id ??
                    completedPayload.session.latest_graph?.active_node_id ??
                    null,
                );
                setStreamedAssistantMessage(completedPayload.turn.assistant_message);
              }
              break;
            case "quota_status":
              {
                const quotaPayload = payload as StreamEventPayloads["quota_status"];
                setBootstrap((state) => ({ ...state, quota_status: quotaPayload.quota_status }));
                setSession((state) => (state ? { ...state, quota_status: quotaPayload.quota_status } : state));
              }
              break;
            case "error":
              {
                const errorPayload = payload as StreamEventPayloads["error"];
                setErrorMessage(errorPayload.error ?? "Live chat run failed.");
              }
              break;
            default:
              break;
          }
        },
      );
      const latestSessionId = sessionIdRef.current;
      if (latestSessionId) {
        const syncedSession = await fetchJson<ChatSession>(`/chat/sessions/${latestSessionId}`);
        setSession(syncedSession);
        setCurrentGraph(syncedSession.latest_graph ?? null);
        setCurrentEvidence(syncedSession.latest_evidence ?? emptyEvidencePanel());
        setSelectedNodeId(syncedSession.latest_graph?.active_node_id ?? null);
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Streaming request failed.");
    } finally {
      setIsStreaming(false);
      setInput("");
    }
  }

  return (
    <div className="live-chat-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">KG</div>
          <span className="brand-title" title={bootstrap.branding.product_tagline}>
            {bootstrap.branding.product_name}
          </span>
        </div>

        <Link className="topbar-back-link" href="/dashboard">
          Back to Dashboard
        </Link>

        <div className="topbar-divider" />

        <div className="topbar-badges">
          {bootstrap.header_stats.map((stat) => (
            <div className={`tbadge tone-${stat.tone}`} key={stat.label} title={stat.hint}>
              {stat.label === "Quota Left" ? <span className="tbadge-dot" /> : null}
              <span className="tbadge-label">{stat.label}</span>
              <span className="tbadge-value">{stat.value}</span>
            </div>
          ))}
          <div className={`tbadge is-status ${statusToneClass}`} title={bootstrap.branding.status_label}>
            <span className={`tbadge-dot ${statusToneClass}`} />
            <span className="tbadge-value">{statusLabel}</span>
          </div>
        </div>
      </header>

      <div
        className="workspace"
        ref={workspaceRef}
        style={
          isCompactLayout
            ? undefined
            : { gridTemplateColumns: `${effectiveSidebarWidth}px 12px minmax(0, 1fr)` }
        }
      >
        <aside className="sidebar">
          <div className="sidebar-head">
            <span className="sidebar-head-title">Conversation</span>
            <button className="new-chat-btn" disabled={isStreaming} onClick={() => void handleNewChat()} title="New chat" type="button">
              <PlusIcon />
            </button>
          </div>

          {errorMessage ? <div className="live-chat-banner error">{errorMessage}</div> : null}
          {quotaStatus?.paused_for_rest_of_day ? (
            <div className="live-chat-banner warning">
              Groq is paused for the rest of the day. Resume date: {quotaStatus.pause_state?.resume_on_date ?? "unknown"}.
            </div>
          ) : null}
          {quotaStatus?.runtime_status?.cooldown_active ? (
            <div className="live-chat-banner info">
              Temporary cooldown active until {quotaStatus.runtime_status.state?.cooldown_until ?? "the next slot"}.
            </div>
          ) : null}

          <div className="thread" id="thread" ref={threadRef}>
            {isLoading ? <div className="live-chat-loading">Connecting to the live chat backend...</div> : null}
            <MessageList
              turns={turns}
              activeTurnId={activeTurnId}
              streamedAssistantMessage={streamedAssistantMessage}
              streamedCypherQueries={currentEvidence?.cypher_queries ?? []}
              isStreaming={isStreaming}
            />
          </div>

          <div className="sidebar-footer">
            <PromptLibrary
              groups={promptGroups}
              isOpen={isPromptLibraryOpen}
              onPickPrompt={(prompt) => {
                setInput(prompt);
                setIsPromptLibraryOpen(false);
                requestAnimationFrame(() => {
                  textareaRef.current?.focus();
                });
              }}
              onToggle={() => setIsPromptLibraryOpen((state) => !state)}
            />

            <div className="composer" id="composer">
              <textarea
                disabled={inputBlocked}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void handleSend(input);
                  }
                }}
                placeholder="Ask a live question about the Turkiye cinema graph..."
                ref={textareaRef}
                rows={1}
                value={input}
              />
              <button className="send-btn" disabled={inputBlocked || !input.trim()} onClick={() => void handleSend(input)} title="Send" type="button">
                <SendArrowIcon />
              </button>
            </div>
          </div>
        </aside>

        {!isCompactLayout ? (
          <div
            aria-label="Resize chat panel"
            className="sidebar-resizer"
            onMouseDown={() => {
              resizingRef.current = true;
              document.body.style.cursor = "col-resize";
              document.body.style.userSelect = "none";
            }}
            role="separator"
            tabIndex={-1}
          >
            <span />
          </div>
        ) : null}

        <section className="main-panel">
          <div className="toolbar">
            <div className="toolbar-left">
              <button
                className={`tb-btn ${focusMode === "all" ? "active" : ""}`}
                onClick={() => setFocusMode("all")}
                type="button"
              >
                All evidence
              </button>
              <button
                className={`tb-btn ${focusMode === "seeds" ? "active" : ""}`}
                onClick={() => setFocusMode("seeds")}
                type="button"
              >
                Highlight seeds
              </button>
              <button
                className={`tb-btn ${focusMode === "answer_path" ? "active" : ""}`}
                onClick={() => setFocusMode("answer_path")}
                type="button"
              >
                Highlight answer path
              </button>
            </div>
            <div className="toolbar-right">
              <span className="toolbar-meta">KG-Infused RAG</span>
              <span className="toolbar-meta">|</span>
              <span className="toolbar-meta">Adaptive Follow-Up</span>
            </div>
          </div>

          <div className="analysis-grid">
            <div className="graph-panel">
              <EvidenceGraphView
                focusMode={focusMode}
                graph={currentGraph}
                onSelectNode={setSelectedNodeId}
                selectedNodeId={selectedNodeId}
              />
            </div>

            <aside className="bottom-panels">
              <section className="panel-card p-node">
                <div className="panel-head">
                  <h3>Node inspector</h3>
                  <span>{activeNode?.kind ?? "idle"}</span>
                </div>
                {activeNode ? (
                  <div className="panel-body">
                    <div className="node-name">{activeNode.label}</div>
                    <div className="node-desc">{activeNode.description || activeNode.why_selected}</div>
                    <div className="chip-row">
                      {activeNode.roles.map((role, index) => (
                        <span className="chip" key={`${role}-${index}`}>
                          {role}
                        </span>
                      ))}
                    </div>
                    <div className="stack">
                      {activeNode.linked_passages.length > 0 ? (
                        activeNode.linked_passages.map((passage, index) => (
                          <div className="si" key={`${activeNode.id}-passage-${index}`}>
                            {passage}
                          </div>
                        ))
                      ) : (
                        <p className="muted">No linked passages yet.</p>
                      )}
                    </div>
                  </div>
                ) : (
                  <p className="muted">Select a node to inspect why it was chosen.</p>
                )}
              </section>

              <section className="panel-card p-evidence">
                <div className="panel-head">
                  <h3>Evidence rail</h3>
                  <span>{(currentEvidence?.selected_triples ?? []).length} triples</span>
                </div>
                <div className="panel-body">
                  {(currentEvidence?.seed_entities ?? []).length > 0 ? (
                    (currentEvidence?.seed_entities ?? []).map((entity) => (
                      <div className="si ev-seed" key={`${entity.entity_name}-${entity.source ?? "seed"}`}>
                        {entity.entity_name}
                        {entity.source ? <small>{entity.source}</small> : null}
                      </div>
                    ))
                  ) : (
                    <p className="muted">Seed entities will appear here.</p>
                  )}

                  {(currentEvidence?.selected_triples ?? []).length > 0 ? (
                    (currentEvidence?.selected_triples ?? []).map((triple, index) => (
                      <div className="si ev-triple" key={`${triple.source_name}-${triple.target_name}-${index}`}>
                        {triple.source_name} {"->"} {triple.relation_label} {"->"} {triple.target_name}
                        <small>Selected KG triple</small>
                      </div>
                    ))
                  ) : null}

                  <div className="si ev-expanded">
                    Expanded query: <strong>{currentEvidence?.expanded_query || "Waiting for KG-guided query expansion..."}</strong>
                    <small>Sent to retrieval stage</small>
                  </div>

                  {currentEvidence?.answer_basis ? (
                    <div className="si ev-answer">
                      {currentEvidence.answer_basis}
                      <small>Answer basis</small>
                    </div>
                  ) : null}

                  {(currentEvidence?.retrieved_documents ?? []).length > 0 ? (
                    (currentEvidence?.retrieved_documents ?? []).map((document, index) => (
                      <div className="si" key={`${document.doc_id ?? document.title ?? index}`}>
                        <strong>{document.title ?? "Retrieved document"}</strong>
                        <p>{document.snippet ?? "No snippet available."}</p>
                      </div>
                    ))
                  ) : null}
                </div>
              </section>
            </aside>
          </div>
        </section>
      </div>
    </div>
  );
}
