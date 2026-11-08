import { useEffect, useState } from "react";
import { api, type ExplainResponse, type KnowledgePoint, type SessionInfo } from "../api";
import Markdown from "../components/Markdown";
import SourceList from "../components/SourceList";
import { Badge, Card, ErrorBox, Spinner } from "../components/ui";

export default function Explain({ session }: { session: SessionInfo }) {
  const [kps, setKps] = useState<KnowledgePoint[]>([]);
  const [selectedKp, setSelectedKp] = useState<number | null>(null);
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<ExplainResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .knowledgePoints(session.id)
      .then(setKps)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [session.id]);

  const run = async () => {
    if (selectedKp === null && !question.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await api.explain(session.id, selectedKp, question.trim() || undefined));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <header>
        <h1 className="text-xl font-bold text-slate-800">AI 讲解</h1>
        <p className="mt-1 text-sm text-slate-500">
          基于你上传的课程资料（检索增强）生成讲解，附引用来源；也可直接提问自由学习
        </p>
      </header>

      <Card>
        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">选择知识点（可选）</label>
            <select
              value={selectedKp ?? ""}
              onChange={(e) => setSelectedKp(e.target.value === "" ? null : Number(e.target.value))}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            >
              <option value="">— 不指定，仅按问题讲解 —</option>
              {kps.map((kp) => (
                <option key={kp.id} value={kp.id}>
                  {kp.course_name ? `${kp.course_name} / ` : ""}
                  {kp.chapter_name ? `${kp.chapter_name} / ` : ""}
                  {kp.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">你的问题（可选）</label>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={2}
              placeholder="例如：请用通俗的方式解释什么是亚阈值漏电，并举一个例子"
              className="w-full resize-none rounded-lg border border-slate-300 px-4 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            />
          </div>
          <button
            onClick={() => void run()}
            disabled={loading || (selectedKp === null && !question.trim())}
            className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:bg-indigo-300"
          >
            {loading ? "生成讲解中…" : "生成讲解"}
          </button>
        </div>
      </Card>

      {error && <ErrorBox message={error} />}

      {loading && (
        <div className="flex justify-center py-10">
          <Spinner label="AI 正在结合你的资料生成讲解…" />
        </div>
      )}

      {result && !loading && (
        <>
          <Card
            title={`讲解：${result.knowledge_point}`}
            actions={<Badge tone="indigo">{result.provider}</Badge>}
          >
            <Markdown text={result.explanation} />
          </Card>
          <Card title={`引用来源（${result.sources.length} 条）`}>
            <SourceList sources={result.sources} />
          </Card>
        </>
      )}
    </div>
  );
}
