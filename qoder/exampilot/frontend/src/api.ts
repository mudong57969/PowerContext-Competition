const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

export const TOKEN_KEY = "exampilot.token";
export const SESSION_KEY = "exampilot.session_id";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function clearIdentity(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(SESSION_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

// ---------- types ----------

export interface Health {
  status: string;
  version: string;
  seekdb: { configured: boolean; ok: boolean; database: string | null };
  memory: { enabled: boolean; reachable: boolean };
  embedding: { provider: string; enabled: boolean; model: string | null };
  llm: { provider: string; enabled: boolean; model: string | null };
}

export interface SessionInfo {
  id: string;
  name: string;
  memory_warning: string | null;
  stats: {
    documents: number;
    questions: number;
    courses: number;
    attempts: number;
    mastered_knowledge_points: number;
    average_mastery: number;
  };
}

export interface IdentityCreated {
  session: SessionInfo;
  token: string;
}

export interface DocumentResult {
  id: number | null;
  filename: string;
  ok: boolean;
  error: string | null;
  duplicate: boolean;
  file_type: string;
  page_count: number;
  parse_status: string;
  classify_status: string;
  classify_confidence: number;
  classify_reason?: string;
  course: string | null;
  chapter: string | null;
  knowledge_points: string[];
  course_candidates?: { name: string; score: number; source: string }[];
  chapter_candidates?: { name: string; score: number; source: string }[];
  kp_evidence?: Record<string, number[]>;
  evidence_course?: string | null;
  evidence_chapter?: string | null;
  evidence_knowledge_points?: string[];
  extracted_chars?: number;
  ocr_required: boolean;
  warnings: string[];
}

export interface Course {
  id: number;
  name: string;
  status: string;
  confidence: number;
  chapter_count: number;
  knowledge_point_count: number;
  document_count: number;
  question_count: number;
}

export interface KnowledgePoint {
  id: number;
  name: string;
  course_id: number;
  course_name: string | null;
  chapter_name: string | null;
  description: string | null;
  mastery: {
    practice_count: number;
    correct_count: number;
    streak: number;
    mastery_score: number;
  } | null;
}

export interface SearchHit {
  chunk_id: number;
  document_id: number;
  filename: string;
  course: string | null;
  chapter: string | null;
  page_number: number;
  text: string;
  score: number;
  matched_by: string[];
}

export interface MemoryRecall {
  available: boolean;
  mode: string | null;
  hits: { text: string; score: number; matched_by: string[]; entry_id: string }[];
  warning: string | null;
}

export interface SearchResponse {
  query: string;
  hits: SearchHit[];
  mode: string;
  fts_hits: number;
  vector_hits: number;
  warning: string | null;
  memory: MemoryRecall;
}

export interface ExplainResponse {
  knowledge_point: string;
  explanation: string;
  provider: string;
  sources: SearchHit[];
  memory: { ok?: boolean; warning?: string; reference?: unknown };
}

export interface PracticeQuestion {
  id: number;
  type: string;
  stem: string;
  options: { letter: string; text: string }[];
  difficulty: number;
  knowledge_points: string[];
}

export interface PracticeStart {
  practice_session_id: number;
  course_id: number | null;
  course_name: string | null;
  mode: string;
  total: number;
  questions: PracticeQuestion[];
}

export interface GradedAnswer {
  question_id: number;
  type: string;
  stem: string;
  options: { letter: string; text: string }[];
  user_answer: string;
  is_correct: boolean;
  score: number;
  evidence: string;
  correct_answer: string;
  explanation: string;
  knowledge_points: string[];
}

export interface PracticeSubmit {
  practice_session_id: number;
  total: number;
  correct_count: number;
  score: number;
  results: GradedAnswer[];
  mastery: { knowledge_point_id: number; name: string; mastery_score: number; practice_count: number }[];
  review_tasks_created: number;
  memory: { ok?: boolean; warning?: string; reference?: unknown };
}

export interface Mistake {
  question_id: number;
  type: string;
  stem: string;
  options: { letter: string; text: string }[];
  correct_answer: string;
  explanation: string;
  knowledge_points: string[];
  wrong_count: number;
  last_wrong_at: string | null;
  user_answers: string[];
}

export interface ReviewTask {
  id: number;
  knowledge_point_id: number;
  knowledge_point_name: string;
  course_name: string | null;
  due_date: string | null;
  reason: string;
  status: string;
  mastery_score: number | null;
}

export interface ReviewPlan {
  due: ReviewTask[];
  upcoming: ReviewTask[];
  mastery: { knowledge_point_id: number; name: string; mastery_score: number; practice_count: number; streak: number }[];
}

export interface MemoryEvent {
  id: number;
  session_id: string;
  kind: string;
  summary: string;
  memory_reference: string | null;
  status: string;
  created_at: string | null;
}

export interface MemorySearchResponse {
  available: boolean;
  mode: string | null;
  warning?: string;
  hits: {
    text: string;
    score: number;
    matched_by: string[];
    entry_id: string;
    entry_version_id?: string;
  }[];
}

export interface Preferences {
  session_id: string;
  exam_date: string | null;
  goal: string | null;
  preferred_language: string;
}

// ---------- endpoints ----------

export const api = {
  health: () => request<Health>("/api/health"),

  createIdentity: (name: string) => request<IdentityCreated>("/api/sessions", json("POST", { name })),
  me: () => request<SessionInfo>("/api/sessions/me"),

  uploadDocuments: (sessionId: string, files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    return request<{ session_id: string; results: DocumentResult[] }>(
      `/api/sessions/${sessionId}/documents`,
      { method: "POST", body: form },
    );
  },
  listDocuments: (sessionId: string) =>
    request<DocumentResult[]>(`/api/sessions/${sessionId}/documents`),
  confirmDocument: (docId: number, body: { course: string; chapter?: string | null; knowledge_points?: string[] }) =>
    request<unknown>(`/api/documents/${docId}/confirm`, json("POST", body)),
  correctDocument: (docId: number, body: { course: string; chapter?: string | null; knowledge_points?: string[] }) =>
    request<unknown>(`/api/documents/${docId}/correct`, json("POST", body)),
  reclassifyDocument: (docId: number) =>
    request<DocumentResult>(`/api/documents/${docId}/reclassify`, json("POST", {})),

  courses: (sessionId: string) => request<Course[]>(`/api/sessions/${sessionId}/courses`),
  knowledgePoints: (sessionId: string, courseId?: number) =>
    request<KnowledgePoint[]>(
      `/api/sessions/${sessionId}/knowledge-points${courseId ? `?course_id=${courseId}` : ""}`,
    ),
  mastery: (sessionId: string) => request<Record<string, unknown>[]>(`/api/sessions/${sessionId}/mastery`),

  search: (sessionId: string, query: string, courseId?: number, limit = 10) =>
    request<SearchResponse>(`/api/sessions/${sessionId}/search`, json("POST", { query, course_id: courseId ?? null, limit })),

  explain: (sessionId: string, knowledgePointId: number | null, query?: string) =>
    request<ExplainResponse>(`/api/sessions/${sessionId}/explain`, json("POST", { knowledge_point_id: knowledgePointId, query: query ?? null })),

  startPractice: (
    sessionId: string,
    body: { course_id?: number | null; knowledge_point_ids?: number[]; count: number; mode: string },
  ) => request<PracticeStart>(`/api/sessions/${sessionId}/practice/start`, json("POST", body)),
  submitPractice: (practiceSessionId: number, answers: { question_id: number; answer: string }[]) =>
    request<PracticeSubmit>(`/api/practice/${practiceSessionId}/submit`, json("POST", { answers })),

  mistakes: (sessionId: string) => request<Mistake[]>(`/api/sessions/${sessionId}/mistakes`),
  mistakesPractice: (sessionId: string, count = 5) =>
    request<PracticeStart>(`/api/sessions/${sessionId}/mistakes/practice`, json("POST", { count })),

  reviewPlan: (sessionId: string) => request<ReviewPlan>(`/api/sessions/${sessionId}/review/plan`),
  completeReview: (taskId: number, correct: boolean) =>
    request<{ task_id: number; status: string; follow_up_task_id: number | null }>(
      `/api/review-tasks/${taskId}/complete`,
      json("POST", { correct }),
    ),

  memoryEvents: (sessionId: string) => request<MemoryEvent[]>(`/api/sessions/${sessionId}/memories`),
  memorySearch: (sessionId: string, query: string, limit = 10) =>
    request<MemorySearchResponse>(`/api/sessions/${sessionId}/memories/search?query=${encodeURIComponent(query)}&limit=${limit}`),
  writeMemory: (sessionId: string, kind: string, text: string) =>
    request<{ ok?: boolean; warning?: string; reference?: unknown }>(
      `/api/sessions/${sessionId}/memories`,
      json("POST", { kind, text }),
    ),

  getPreferences: (sessionId: string) => request<Preferences>(`/api/sessions/${sessionId}/preferences`),
  putPreferences: (sessionId: string, body: { exam_date?: string | null; goal?: string | null; preferred_language?: string }) =>
    request<Preferences>(`/api/sessions/${sessionId}/preferences`, json("PUT", body)),
};
