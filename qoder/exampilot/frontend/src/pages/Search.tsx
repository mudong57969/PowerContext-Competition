import { useEffect, useState } from "react";
import { api, type Course, type SearchResponse, type SessionInfo } from "../api";
import SourceList from "../components/SourceList";
import { Badge, Card, EmptyState, ErrorBox } from "../components/ui";

export default function Search({ session }: { session: SessionInfo }) {
  const [courses, setCourses] = useState<Course[]>([]);
  const [query, setQuery] = useState("");
  const [courseId, setCourseId] = useState<number | null>(null);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .courses(session.id)
      .then(setCourses)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [session.id]);

  const run = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await api.search(session.id, query.trim(), courseId ?? undefined, 10));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <header>
        <h1 className="text-xl font-bold text-slate-800">知识检索</h1>
        <p className="mt-1 text-sm text-slate-500">
          seekdb 混合检索：中文全文检索（trigram）+ 语义向量检索（bge-small-zh），RRF 融合排序，命中来源可溯源
        </p>
      </header>

      <Card>
        <div className="flex flex-col gap-3">
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void run();
              }}
              placeholder="输入问题或关键词，例如：动态功耗由哪两部分组成？"
              className="flex-1 rounded-lg border border-slate-300 px-4 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            />
            <button
              onClick={() => void run()}
              disabled={loading || !query.trim()}
              className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:bg-indigo-300"
            >
              {loading ? "检索中…" : "检索"}
            </button>
          </div>
          <select
            value={courseId ?? ""}
            onChange={(e) => setCourseId(e.target.value === "" ? null : Number(e.target.value))}
            className="w-64 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
          >
            <option value="">全部课程</option>
            {courses.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
      </Card>

      {error && <ErrorBox message={error} />}

      {result && (
        <Card
          title={`检索结果（${result.hits.length} 条）`}
          actions={
            <div className="flex gap-2">
              <Badge tone={result.mode === "hybrid" ? "indigo" : "amber"}>模式：{result.mode}</Badge>
              <Badge tone="amber">全文 {result.fts_hits}</Badge>
              <Badge tone="indigo">向量 {result.vector_hits}</Badge>
            </div>
          }
        >
          {result.warning && (
            <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700">
              {result.warning}
            </div>
          )}
          {result.hits.length === 0 ? (
            <EmptyState text="没有检索到相关内容。试试更换关键词，或先上传课程资料。" />
          ) : (
            <SourceList sources={result.hits} />
          )}

          {result.memory.available && result.memory.hits.length > 0 && (
            <div className="mt-5">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-600">
                🧠 PowerContext 长期记忆匹配
                <Badge tone="slate">{result.memory.mode}</Badge>
              </h3>
              <ul className="space-y-2">
                {result.memory.hits.map((h, i) => (
                  <li key={i} className="rounded-lg border border-indigo-100 bg-indigo-50/50 p-3 text-sm text-slate-700">
                    {h.text}
                    <div className="mt-1 text-xs text-slate-400">
                      score {(h.score * 100).toFixed(1)}% · {h.matched_by.join(", ")}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
