import { unstable_noStore as noStore } from "next/cache";

import {
  activeCypher,
  chatMessages,
  chatStats,
  cypherResults,
  cypherStats,
  datasetColumns,
  domainBars,
  entityDistribution,
  evidenceRail,
  failureCases,
  gnnStats,
  hopTypeMetrics,
  knowledgeGraphStats,
  methodMetrics,
  pathFamilies,
  queryLibrary,
  questionGrid,
  seedEntities,
  successfulCase,
  xaiStats,
} from "@/lib/dashboard-data";

const BACKEND_FETCH_TIMEOUT_MS = 8000;

type GroqProviderDetails = {
  model?: string;
  plan_mode?: string;
  quota_snapshot?: {
    model?: string;
    remaining_requests?: number;
    remaining_tokens?: number;
  } | null;
  runtime_status?: {
    request_pacing_rpm?: number;
  } | null;
};

type GroqProviderSnapshot = {
  configured: boolean;
  mode?: string | null;
  details?: GroqProviderDetails;
};

type OverviewResponse = {
  graph: {
    cinema_stats?: Record<string, number>;
    node_count?: number;
    edge_count?: number;
    path_summary?: Array<{ template: string; count: number }>;
    seed_rankings?: {
      top_films?: Array<{ entity_id: string; name: string; supporting_edges: number }>;
      top_people?: Array<{ entity_id: string; name: string; relevant_edge_count: number }>;
    };
    top_roles?: Array<{ role: string; count: number }>;
  };
  dataset: {
    question_count?: number;
    distribution?: {
      question_type?: Record<string, number>;
    };
  };
  evaluation: {
    case_study_counts?: {
      success_cases: number;
      failure_cases: number;
    };
    method_summaries?: Array<{
      method: string;
      coverage: number;
      accuracy: number;
      exact_match: number;
      f1: number;
      retrieval_recall: number;
    }>;
  };
  groq: GroqProviderSnapshot;
};

type CypherLibraryResponse = {
  templates?: Array<{
    title: string;
    description?: string;
    statement: string;
    row_count?: number;
    sample_rows?: Array<Record<string, string>>;
  }>;
  verification?: Record<string, { row_count?: number; sample_rows?: Array<Record<string, string>> }>;
  entity_count?: number;
  relationship_count?: number;
};

type EntityDistributionResponse = {
  entity_types?: Array<{ role: string; label: string; count: number; tone: string }>;
};

type QuestionMetricsResponse = {
  questions?: Array<{ id: string; no_retrieval: number; vanilla_rag: number; vanilla_qe: number; kg_rag: number }>;
};

type QuestionTraceResponse = {
  question?: string;
  gold_answer?: { text?: string };
  kg_rag?: {
    prediction_text?: string;
    seed_entities?: Array<{ entity_name: string }>;
    structured_answer?: {
      candidate_texts?: string[];
    };
    activation_rounds?: Array<{
      round_index: number;
      selected_triples?: Array<{
        source_name: string;
        relation_label: string;
        target_name: string;
      }>;
    }>;
    expanded_query?: string;
    retrieved_documents?: Array<{ snippet: string }>;
  };
  baselines?: {
    no_retrieval?: { prediction_text?: string };
    vanilla_rag?: { prediction_text?: string };
    vanilla_qe?: { prediction_text?: string };
  };
};

function backendBaseUrl() {
  const configuredUrl =
    process.env.BACKEND_API_BASE_URL ??
    process.env.NEXT_PUBLIC_BACKEND_API_BASE_URL;

  return configuredUrl?.trim() || "http://127.0.0.1:8000";
}

function groqDetails(overview: OverviewResponse): GroqProviderDetails {
  return overview.groq.details ?? {};
}

async function fetchBackend<T>(path: string): Promise<T | null> {
  noStore();
  try {
    const response = await fetch(`${backendBaseUrl()}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(BACKEND_FETCH_TIMEOUT_MS),
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

function titleCase(value: string) {
  return value
    .replaceAll("_", " ")
    .split(" ")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export async function getKnowledgeGraphViewModel() {
  const [overview, entityDist] = await Promise.all([
    fetchBackend<OverviewResponse>("/dashboard/overview"),
    fetchBackend<EntityDistributionResponse>("/dashboard/entity-distribution"),
  ]);

  const liveEntityDist =
    entityDist?.entity_types?.map((e) => ({
      label: e.label,
      value: e.count,
      tone: e.tone as "cyan" | "amber" | "green" | "pink",
    })) ?? entityDistribution;

  if (!overview) {
    return {
      stats: knowledgeGraphStats,
      seedEntities,
      pathFamilies,
      datasetColumns,
      entityDistribution: liveEntityDist,
    };
  }

  const totalPathCount =
    overview.graph.path_summary?.reduce((sum, item) => sum + item.count, 0) ?? 0;
  const questionTypes = overview.dataset.distribution?.question_type ?? {};

  const liveStats = [
    {
      label: "Cinema Nodes",
      value: String(overview.graph.node_count ?? knowledgeGraphStats[0].value),
      hint: "Filtered Türkiye + cinema subgraph",
      tone: "cyan" as const,
    },
    {
      label: "Relationships",
      value: String(overview.graph.edge_count ?? knowledgeGraphStats[1].value),
      hint: "Loaded into Neo4j Aura",
      tone: "amber" as const,
    },
    {
      label: "Verified Paths",
      value: totalPathCount.toLocaleString("en-US"),
      hint: "Path candidates mined from Wikidata5M",
      tone: "green" as const,
    },
    {
      label: "QA Dataset",
      value: String(overview.dataset.question_count ?? 50),
      hint: `${questionTypes.two_hop ?? 30} two-hop, ${questionTypes.three_hop ?? 15} three-hop, ${questionTypes.comparison ?? 5} comparison`,
      tone: "pink" as const,
    },
  ];

  const liveSeeds = [
    ...(overview.graph.seed_rankings?.top_people ?? []).slice(0, 3).map((person) => ({
      id: person.entity_id,
      name: person.name,
      type: "person",
      links: person.relevant_edge_count,
    })),
    ...(overview.graph.seed_rankings?.top_films ?? []).slice(0, 3).map((film) => ({
      id: film.entity_id,
      name: film.name,
      type: "film",
      links: film.supporting_edges,
    })),
  ];

  const livePathFamilies =
    overview.graph.path_summary?.map((item) => ({
      label: titleCase(item.template),
      value: item.count,
    })) ?? pathFamilies;

  return {
    stats: liveStats,
    seedEntities: liveSeeds.length > 0 ? liveSeeds : seedEntities,
    pathFamilies: livePathFamilies,
    datasetColumns,
    entityDistribution: liveEntityDist,
  };
}

export async function getCypherViewModel() {
  const response = await fetchBackend<CypherLibraryResponse>("/dashboard/cypher-library");
  if (!response) {
    return {
      stats: cypherStats,
      queryLibrary,
      activeStatement: activeCypher,
      results: cypherResults,
    };
  }

  const verificationValues = Object.values(response.verification ?? {});
  const rowCount = verificationValues.reduce((sum, item) => sum + (item.row_count ?? 0), 0);
  const activeTemplate = response.templates?.[1] ?? response.templates?.[0];
  const activeResultRows = verificationValues[1]?.sample_rows ?? verificationValues[0]?.sample_rows ?? [];

  return {
    stats: [
      {
        label: "Query Templates",
        value: String(response.templates?.length ?? 0),
        hint: "Verified reusable Cypher patterns",
        tone: "cyan" as const,
      },
      {
        label: "Max Hops",
        value: "3",
        hint: "Matches dataset design boundary",
        tone: "green" as const,
      },
      {
        label: "Graph Nodes",
        value: String(response.entity_count ?? 0),
        hint: "Current Aura subset size",
        tone: "amber" as const,
      },
      {
        label: "Result Rows",
        value: String(rowCount),
        hint: "Saved verification outputs",
        tone: "pink" as const,
      },
    ],
    queryLibrary:
      response.templates?.map((template) => {
        const t = template.title.toLowerCase();
        const badge = t.startsWith("3-hop") ? "3-hop"
          : t.startsWith("2-hop") ? "2-hop"
          : t.startsWith("1-hop") ? "1-hop"
          : t.startsWith("agg") ? "agg"
          : "multi";
        const name = template.title.replace(/^\d+-hop:\s*/i, "").replace(/^(Aggregation|Comparison):\s*/i, "");
        return {
          name,
          badge,
          description: template.description ?? "",
          statement: template.statement,
          row_count: template.row_count ?? 0,
          sample_rows: template.sample_rows ?? [],
        };
      }) ?? queryLibrary.map((q) => ({ ...q, description: "", statement: activeCypher, row_count: 0, sample_rows: [] as Record<string, string>[] })),
    activeStatement: activeTemplate?.statement ?? activeCypher,
    results: activeResultRows.length > 0 ? activeResultRows : cypherResults,
  };
}

export async function getEvaluationViewModel() {
  const [overview, qMetrics] = await Promise.all([
    fetchBackend<OverviewResponse>("/dashboard/overview"),
    fetchBackend<QuestionMetricsResponse>("/dashboard/question-metrics"),
  ]);

  const liveQuestionGrid =
    qMetrics?.questions && qMetrics.questions.length > 0
      ? qMetrics.questions.map((q) => ({ nr: q.no_retrieval, vr: q.vanilla_rag, vq: q.vanilla_qe, kg: q.kg_rag }))
      : questionGrid;

  if (!overview) {
    return {
      stats: gnnStats,
      methodMetrics,
      domainBars,
      hopTypeMetrics,
      questionGrid: liveQuestionGrid,
    };
  }

  const summaries = overview.evaluation.method_summaries ?? [];
  const kgSummary = summaries.find((item) => item.method === "kg_infused_rag");

  return {
    stats: [
      {
        label: "Experimental Lane",
        value: "R-GAT",
        hint: "Reserved for future graph learning work",
        tone: "cyan" as const,
      },
      {
        label: "Best F1",
        value: kgSummary ? kgSummary.f1.toFixed(3) : "0.980",
        hint: "Current evaluation winner is KG-RAG",
        tone: "green" as const,
      },
      {
        label: "Question Coverage",
        value: "100%",
        hint: "All 50 questions evaluated",
        tone: "pink" as const,
      },
      {
        label: "Method Set",
        value: String(summaries.length || 4),
        hint: "Direct comparison from saved artifacts",
        tone: "amber" as const,
      },
    ],
    methodMetrics:
      summaries.length > 0
        ? summaries.map((item) => ({
            method: titleCase(item.method),
            accuracy: item.accuracy,
            exactMatch: item.exact_match,
            f1: item.f1,
            recall: item.retrieval_recall,
            tone:
              item.method === "kg_infused_rag"
                ? "green"
                : item.method === "vanilla_rag"
                  ? "amber"
                  : item.method === "vanilla_qe"
                    ? "cyan"
                    : "pink",
          }))
        : methodMetrics,
    domainBars,
    hopTypeMetrics,
    questionGrid: liveQuestionGrid,
  };
}

export async function getQuestionTraceViewModel(questionId = "qa_104db2fbbec9") {
  return fetchBackend<QuestionTraceResponse>(`/dashboard/question-trace?question_id=${questionId}`);
}

export async function getXaiViewModel() {
  const [overview, successTrace] = await Promise.all([
    fetchBackend<OverviewResponse>("/dashboard/overview"),
    getQuestionTraceViewModel("qa_104db2fbbec9"),
  ]);

  if (!overview || !successTrace) {
    return {
      stats: xaiStats,
      successCase: successfulCase,
      failures: failureCases,
    };
  }

  const kgMetric = overview.evaluation.method_summaries?.find((item) => item.method === "kg_infused_rag");
  const successRounds =
    successTrace.kg_rag?.activation_rounds?.map(
      (round) =>
        `R${round.round_index}: ${round.selected_triples?.map((triple) => `${triple.source_name} -> ${triple.relation_label} -> ${triple.target_name}`).join("; ") ?? "No triple selected."}`,
    ) ?? successfulCase.rounds;

  return {
    stats: [
      {
        label: "Case Studies",
        value: String(
          (overview.evaluation.case_study_counts?.success_cases ?? 0) +
            (overview.evaluation.case_study_counts?.failure_cases ?? 0),
        ),
        hint: "5 success + 5 failure",
        tone: "cyan" as const,
      },
      {
        label: "Trace Coverage",
        value: "50 / 50",
        hint: "Every KG-RAG answer has a saved trace",
        tone: "green" as const,
      },
      {
        label: "KG-RAG EM",
        value: `${Math.round((kgMetric?.exact_match ?? 0.98) * 100)}%`,
        hint: "Final exact-match score on the full set",
        tone: "pink" as const,
      },
      {
        label: "Dominant Error",
        value: "KG Gap",
        hint: "Missing education grounding still appears",
        tone: "amber" as const,
      },
    ],
    successCase: {
      question: successTrace.question ?? successfulCase.question,
      gold: successTrace.gold_answer?.text ?? successfulCase.gold,
      prediction: successTrace.kg_rag?.prediction_text ?? successfulCase.prediction,
      seed: successTrace.kg_rag?.seed_entities?.[0]?.entity_name ?? successfulCase.seed,
      path:
        successTrace.kg_rag?.activation_rounds?.flatMap((round) =>
          (round.selected_triples ?? []).map((triple, index) => ({
            label: index === 0 ? `round ${round.round_index}` : triple.relation_label,
            value: `${triple.source_name} -> ${triple.target_name}`,
          })),
        ) ?? successfulCase.path,
      rounds: successRounds,
    },
    failures: failureCases,
  };
}

export async function getChatViewModel() {
  const [overview, trace] = await Promise.all([
    fetchBackend<OverviewResponse>("/dashboard/overview"),
    getQuestionTraceViewModel("qa_104db2fbbec9"),
  ]);

  if (!overview || !trace) {
    return {
      stats: chatStats,
      messages: chatMessages,
      evidenceRail,
    };
  }

  const kgMetric = overview.evaluation.method_summaries?.find((item) => item.method === "kg_infused_rag");
  const groq = groqDetails(overview);
  const quotaSnapshot = groq.quota_snapshot ?? undefined;
  const requestPacingRpm = groq.runtime_status?.request_pacing_rpm ?? 12;

  return {
    stats: [
      {
        label: "Primary Model",
        value: quotaSnapshot?.model ?? groq.model ?? "openai/gpt-oss-120b",
        hint: `Groq ${groq.plan_mode ?? "free"} plan paced at ${requestPacingRpm} RPM`,
        tone: "cyan" as const,
      },
      {
        label: "Default Method",
        value: "KG-RAG",
        hint: `Best EM ${Math.round((kgMetric?.exact_match ?? 0.98) * 100)}%`,
        tone: "green" as const,
      },
      {
        label: "Question Bank",
        value: String(overview.dataset.question_count ?? 50),
        hint: "Verified multi-hop cinema set",
        tone: "amber" as const,
      },
      {
        label: "Quota Left",
        value: quotaSnapshot?.remaining_requests != null ? String(quotaSnapshot.remaining_requests) : "n/a",
        hint:
          quotaSnapshot?.remaining_tokens != null
            ? `Tokens left ${quotaSnapshot.remaining_tokens}`
            : "Probe quota from the chat workspace",
        tone: "pink" as const,
      },
    ],
    messages: [
      {
        role: "user",
        text: trace.question ?? chatMessages[0].text,
      },
      {
        role: "assistant",
        text:
          trace.kg_rag?.prediction_text
            ? `${trace.kg_rag.prediction_text}.`
            : chatMessages[1].text,
      },
      {
        role: "assistant",
        text:
          trace.kg_rag?.expanded_query
            ? `Expanded query used: ${trace.kg_rag.expanded_query}`
            : chatMessages[2].text,
      },
    ],
    evidenceRail: {
      entities:
        trace.kg_rag?.seed_entities?.map((entity) => entity.entity_name) ?? evidenceRail.entities,
      triples:
        trace.kg_rag?.activation_rounds?.flatMap((round) =>
          (round.selected_triples ?? []).map(
            (triple) => `${triple.source_name} -> ${triple.relation_label} -> ${triple.target_name}`,
          ),
        ) ?? evidenceRail.triples,
      expandedQuery: trace.kg_rag?.expanded_query ?? evidenceRail.expandedQuery,
      passages:
        trace.kg_rag?.retrieved_documents?.slice(0, 3).map((doc) => doc.snippet) ??
        evidenceRail.passages,
    },
  };
}
