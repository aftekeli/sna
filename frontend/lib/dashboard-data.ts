export type NavKey =
  | "knowledge-graph"
  | "cypher-queries"
  | "gnn"
  | "xai-evidence"
  | "chat";

export type StatCardData = {
  label: string;
  value: string;
  hint: string;
  tone?: "cyan" | "amber" | "green" | "pink";
};

export const navItems: Array<{ key: NavKey; label: string; href: string; badge?: string }> = [
  { key: "knowledge-graph", label: "Knowledge Graph", href: "/knowledge-graph", badge: "629" },
  { key: "cypher-queries", label: "Cypher Queries", href: "/cypher-queries", badge: "8" },
  { key: "gnn", label: "GNN", href: "/gnn", badge: "exp" },
  { key: "xai-evidence", label: "XAI Evidence", href: "/xai-evidence", badge: "10" },
  { key: "chat", label: "Chat", href: "/chat", badge: "live" },
];

export const mastheadChips = ["CSE 474/5074", "Wikidata5M", "Neo4j", "Groq"];

export const knowledgeGraphStats: StatCardData[] = [
  { label: "Cinema Nodes", value: "629", hint: "Filtered Türkiye + cinema subgraph", tone: "cyan" },
  { label: "Relationships", value: "1,516", hint: "Loaded into Neo4j Aura", tone: "amber" },
  { label: "Verified Paths", value: "1,186", hint: "Path candidates mined from Wikidata5M", tone: "green" },
  { label: "QA Dataset", value: "50", hint: "30 two-hop, 15 three-hop, 5 comparison", tone: "pink" },
];

export const graphNodes = [
  { label: "Türkiye", x: 48, y: 48, tone: "amber" },
  { label: "Angel's Fall", x: 66, y: 68, tone: "red" },
  { label: "Do Not Forget Me Istanbul", x: 78, y: 46, tone: "red" },
  { label: "Semih Kaplanoğlu", x: 76, y: 24, tone: "cyan" },
  { label: "Zeki Demirkubuz", x: 56, y: 24, tone: "cyan" },
  { label: "Istanbul University", x: 40, y: 76, tone: "green" },
  { label: "Dokuz Eylül University", x: 22, y: 62, tone: "green" },
  { label: "Istanbul", x: 30, y: 22, tone: "blue" },
  { label: "Trabzon", x: 12, y: 44, tone: "blue" },
  { label: "USC", x: 88, y: 18, tone: "pink" },
];

export const graphEdges = [
  { from: "Türkiye", to: "Istanbul", label: "contains" },
  { from: "Türkiye", to: "Trabzon", label: "contains" },
  { from: "Türkiye", to: "Angel's Fall", label: "country" },
  { from: "Türkiye", to: "Do Not Forget Me Istanbul", label: "country" },
  { from: "Angel's Fall", to: "Semih Kaplanoğlu", label: "director" },
  { from: "Do Not Forget Me Istanbul", to: "Zeki Demirkubuz", label: "director" },
  { from: "Semih Kaplanoğlu", to: "Dokuz Eylül University", label: "educated at" },
  { from: "Zeki Demirkubuz", to: "Istanbul University", label: "educated at" },
  { from: "Zeki Demirkubuz", to: "USC", label: "contrast path" },
];

export const domainShare = [
  { label: "Film", value: 270, tone: "red" },
  { label: "People", value: 359, tone: "cyan" },
  { label: "Universities", value: 12, tone: "green" },
  { label: "Places", value: 38, tone: "blue" },
  { label: "Awards", value: 20, tone: "pink" },
];

export const seedEntities = [
  { id: "Q43", name: "Türkiye", type: "country", links: 148 },
  { id: "Q36689", name: "Zeki Demirkubuz", type: "person", links: 12 },
  { id: "Q1129300", name: "Semih Kaplanoğlu", type: "person", links: 10 },
  { id: "Q1869346", name: "Nuri Bilge Ceylan", type: "person", links: 14 },
  { id: "Q2642235", name: "Istanbul University", type: "org", links: 9 },
  { id: "Q981624", name: "Dokuz Eylül University", type: "org", links: 7 },
];

export const pathFamilies = [
  { label: "cast -> birth place", value: 585 },
  { label: "cast -> birth place -> country", value: 312 },
  { label: "director -> birth place", value: 132 },
  { label: "director -> birth place -> country", value: 57 },
  { label: "cast -> award", value: 43 },
  { label: "director -> education", value: 23 },
  { label: "director -> education -> country", value: 22 },
  { label: "director -> award", value: 12 },
];

export const datasetColumns = [
  {
    title: "2-Hop Questions (30)",
    items: [
      "Film -> Director -> Birth place",
      "Film -> Director -> Award",
      "Film -> Director -> Education",
      "Film -> Cast member -> Birth place",
      "Film -> Cast member -> Award",
    ],
  },
  {
    title: "3-Hop Questions (15)",
    items: [
      "Film -> Director -> Birth place -> Country",
      "Film -> Director -> Education -> Country",
      "Film -> Cast member -> Birth place -> Country",
    ],
  },
  {
    title: "Comparison Questions (5)",
    items: [
      "Same birth country?",
      "Same education country?",
      "Cross-film comparison with verified paths",
    ],
  },
];

export const cypherStats: StatCardData[] = [
  { label: "Query Templates", value: "8", hint: "Verified reusable Cypher patterns", tone: "cyan" },
  { label: "Max Hops", value: "3", hint: "Matches dataset design boundary", tone: "green" },
  { label: "Graph Nodes", value: "629", hint: "Current Aura subset size", tone: "amber" },
  { label: "Result Rows", value: "50+", hint: "Saved verification outputs", tone: "pink" },
];

export const queryLibrary = [
  { name: "Türkiye Root Entity", badge: "1-hop" },
  { name: "Film -> Director -> Birth Place", badge: "2-hop" },
  { name: "Film -> Director -> Education", badge: "2-hop" },
  { name: "Film -> Cast -> Birth Place", badge: "2-hop" },
  { name: "Film -> Director -> Birth Place -> Country", badge: "3-hop" },
  { name: "Film -> Cast -> Birth Place -> Country", badge: "3-hop" },
  { name: "Comparison Seed Resolver", badge: "multi" },
  { name: "Relation Frequency Summary", badge: "agg" },
];

export const activeCypher = `MATCH (film:Entity {canonical_name: "Angel's Fall"})-[:REL {label: "director"}]->(director:Entity)
MATCH (director)-[:REL {label: "educated at"}]->(school:Entity)
RETURN film.canonical_name AS film,
       director.canonical_name AS director,
       school.canonical_name AS school
LIMIT 5`;

export const cypherResults = [
  { film: "Angel's Fall", director: "Semih Kaplanoğlu", school: "Dokuz Eylül University" },
  { film: "Ember", director: "Zeki Demirkubuz", school: "Istanbul University" },
  { film: "Do Not Forget Me Istanbul", director: "Hany Abu-Assad", school: "The University of Southern California" },
];

export const methodMetrics = [
  { method: "No Retrieval", accuracy: 0.18, exactMatch: 0.08, f1: 0.1001, recall: 0.0, tone: "pink" },
  { method: "Vanilla RAG", accuracy: 0.96, exactMatch: 0.82, f1: 0.9371, recall: 1.0, tone: "amber" },
  { method: "Vanilla QE", accuracy: 0.96, exactMatch: 0.8, f1: 0.9145, recall: 1.0, tone: "cyan" },
  { method: "KG-Infused RAG", accuracy: 0.98, exactMatch: 0.98, f1: 0.98, recall: 0.97, tone: "green" },
];

export const gnnStats: StatCardData[] = [
  { label: "Experimental Lane", value: "R-GAT", hint: "Reserved for future graph learning work", tone: "cyan" },
  { label: "Best F1", value: "0.980", hint: "Current evaluation winner is KG-RAG", tone: "green" },
  { label: "Question Coverage", value: "100%", hint: "All 50 questions evaluated", tone: "pink" },
  { label: "Method Set", value: "4", hint: "Direct comparison from saved artifacts", tone: "amber" },
];

// Real F1 values computed from artifacts/phase-7/latest/metrics.json grouped by question template family.
export const domainBars = [
  { label: "Director — Birth Place", kg: 1.0, rag: 0.97 },
  { label: "Cast — Birth Place", kg: 1.0, rag: 0.93 },
  { label: "Education", kg: 0.90, rag: 0.93 },
  { label: "Awards", kg: 1.0, rag: 0.88 },
  { label: "Comparison", kg: 1.0, rag: 1.0 },
];

// Per-question-type breakdown (2-hop / 3-hop / comparison) computed from real metrics.
export const hopTypeMetrics = [
  { type: "2-hop", n: 30, kg_acc: 0.97, kg_f1: 0.967, kg_em: 0.97, rag_acc: 0.93, rag_f1: 0.923, nor_acc: 0.13 },
  { type: "3-hop", n: 15, kg_acc: 1.00, kg_f1: 1.000, kg_em: 1.00, rag_acc: 1.00, rag_f1: 0.944, nor_acc: 0.13 },
  { type: "Comparison", n: 5,  kg_acc: 1.00, kg_f1: 1.000, kg_em: 1.00, rag_acc: 1.00, rag_f1: 1.000, nor_acc: 0.60 },
];

export const xaiStats: StatCardData[] = [
  { label: "Case Studies", value: "10", hint: "5 success + 5 failure", tone: "cyan" },
  { label: "Trace Coverage", value: "50 / 50", hint: "Every KG-RAG answer has a saved trace", tone: "green" },
  { label: "KG-RAG EM", value: "98%", hint: "Final exact-match score on the full set", tone: "pink" },
  { label: "Dominant Error", value: "KG Gap", hint: "Missing education evidence still appears", tone: "amber" },
];

export const successfulCase = {
  question: "Where did the director of Ember study?",
  gold: "Istanbul University",
  prediction: "Istanbul University",
  seed: "Ember",
  path: [
    { label: "seed", value: "Ember" },
    { label: "director", value: "Zeki Demirkubuz" },
    { label: "educated at", value: "Istanbul University" },
  ],
  rounds: [
    "R1: seed entity Ember matched to film profile and director edge.",
    "R2: director neighborhood surfaced education triples and eliminated biography-only noise.",
    "R3: structured answer normalization snapped the final entity to the gold surface form.",
  ],
};

export const failureCase = {
  question: "Where did the director of Do Not Forget Me Istanbul study?",
  expected: "The University of Southern California",
  prediction: "unknown",
  note: "The USC education triple for Zeki Demirkubuz is absent from Wikidata5M. KG-Infused RAG correctly returns unknown rather than hallucinating.",
};

// All 5 failure cases with PDF error taxonomy categories (from phase-7/latest/case_studies.json).
export const failureCases = [
  {
    method: "KG-Infused RAG",
    question: "Where did the director of Do Not Forget Me Istanbul study?",
    expected: "The University of Southern California",
    prediction: "unknown",
    error_category: "KG Data Deficiency",
    error_category_tone: "rose" as const,
    note: "The Demirkubuz → educated at → USC triple is absent from Wikidata5M. KG activation terminates without a grounded answer.",
    suggestion: "Augment subgraph with DBpedia / Wikidata live API to fill missing education triples.",
  },
  {
    method: "No Retrieval",
    question: "Were the directors of Angel's Fall and Do Not Forget Me Istanbul educated in the same country?",
    expected: "no",
    prediction: "Yes.",
    error_category: "LLM Selection Error",
    error_category_tone: "amber" as const,
    note: "LLM hallucinates a confident comparison answer without any evidence. Turkish-US education paths are conflated.",
    suggestion: "Enforce a refusal policy in NoR prompt for comparison questions lacking structured evidence.",
  },
  {
    method: "No Retrieval",
    question: "In which country is the school attended by the director of Angel's Fall located?",
    expected: "Turkey",
    prediction: "Unknown",
    error_category: "Retrieval Error",
    error_category_tone: "amber" as const,
    note: "3-hop chain exceeds parametric recall. Method has zero corpus access, so the LLM falls back to Unknown.",
    suggestion: "Baseline limitation — use as negative reference to quantify KG-Infused RAG gain on 3-hop questions.",
  },
  {
    method: "No Retrieval",
    question: "Where did the director of Ember study?",
    expected: "Istanbul University",
    prediction: "Zeki Demirkubuz studied engineering.",
    error_category: "LLM Selection Error",
    error_category_tone: "amber" as const,
    note: "LLM generates a sentence-level hallucination instead of a single entity name.",
    suggestion: "Constrain output format to a single entity name or unknown to prevent sentence-level hallucination.",
  },
  {
    method: "No Retrieval",
    question: "In which country was Ali Düşenkalkar, a cast member of Devrim Arabaları, born?",
    expected: "Cyprus",
    prediction: "Turkey",
    error_category: "LLM Selection Error",
    error_category_tone: "amber" as const,
    note: "Turkish-domain bias causes the LLM to predict Turkey. KG-Infused RAG correctly traces the P19 → P17 path to Cyprus.",
    suggestion: "Demonstrates the value of KG grounding — include as positive evidence for the KG-RAG approach in the final report.",
  },
];

export const entityDistribution = [
  { label: "Film", value: 207, tone: "cyan" as const },
  { label: "Cast Member", value: 193, tone: "amber" as const },
  { label: "Birth Place", value: 109, tone: "green" as const },
  { label: "Director", value: 47, tone: "pink" as const },
  { label: "Country", value: 25, tone: "rose" as const },
  { label: "Award", value: 13, tone: "blue" as const },
];

export const questionGrid = [
  {nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:1,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},
  {nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},
  {nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:1,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:0},
  {nr:0,vr:1,vq:1,kg:1},{nr:1,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},
  {nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},
  {nr:0,vr:1,vq:1,kg:1},{nr:0,vr:0,vq:0,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:0,vq:0,kg:1},{nr:1,vr:1,vq:1,kg:1},
  {nr:1,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},
  {nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},
  {nr:1,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},
  {nr:1,vr:1,vq:1,kg:1},{nr:1,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},{nr:1,vr:1,vq:1,kg:1},{nr:0,vr:1,vq:1,kg:1},
];

export const chatStats: StatCardData[] = [
  { label: "Primary Model", value: "GPT-OSS 120B", hint: "Groq free-plan paced at 12 RPM", tone: "cyan" },
  { label: "Default Method", value: "KG-RAG", hint: "Best full-run metric profile", tone: "green" },
  { label: "Question Bank", value: "50", hint: "Verified multi-hop cinema set", tone: "amber" },
  { label: "Saved Traces", value: "50", hint: "Evidence rail can replay each answer", tone: "pink" },
];

export const chatMessages = [
  {
    role: "user",
    text: "Where did the director of Ember study?",
  },
  {
    role: "assistant",
    text: "The director of Ember studied at Istanbul University.",
  },
  {
    role: "assistant",
    text: "I used the film -> director -> educated at chain from the Türkiye cinema subgraph and matched it with the saved support path.",
  },
];

export const evidenceRail = {
  entities: ["Ember", "Zeki Demirkubuz", "Istanbul University"],
  triples: [
    "Ember -> director -> Zeki Demirkubuz",
    "Zeki Demirkubuz -> educated at -> Istanbul University",
  ],
  expandedQuery:
    "Director of Ember education background, validated school entity, cinema-domain evidence from Wikidata5M subset.",
  passages: [
    "Support path artifact confirms Zeki Demirkubuz -> Istanbul University.",
    "Entity profile mentions Turkish director and education metadata.",
  ],
};
