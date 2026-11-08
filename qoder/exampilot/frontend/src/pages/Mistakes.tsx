import { useEffect, useState } from "react";
import { api, type Mistake, type PracticeStart, type PracticeSubmit, type SessionInfo } from "../api";
import { AnsweringView, ResultView } from "../components/PracticeFlow";
import { Badge, Button, Card, EmptyState, ErrorBox, Spinner } from "../components/ui";

type Stage =
  | { kind: "list" }
  | { kind: "answering"; data: PracticeStart }
  | { kind: "submitting" }
  | { kind: "result"; data: PracticeSubmit };

export default function Mistakes({ session }: { session: SessionInfo }) {
  const [stage, setStage] = useState<Stage>({ kind: "list" });
  const [mistakes, setMistakes] = useState<Mistake[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    setLoading(true);
    setError(null);
    try {
      setMistakes(await api.mistakes(session.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload();
  }, [session.id]);

  const startPractice = async () => {
    setError(null);
    setStage({ kind: "submitting" });
    try {
      const data = await api.mistakesPractice(session.id, 5);
      setStage({ kind: "answering", data });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStage({ kind: "list" });
    }
  };

  const submit = async (answers: { question_id: number; answer: string }[]) => {
    const cur = stage;
    if (cur.kind !== "answering") return;
    setStage({ kind: "submitting" });
    try {
      const result = await api.submitPractice(cur.data.practice_session_id, answers);
      setStage({ kind: "result", data: result });
      void reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStage(cur);
    }
  };

  if (stage.kind === "submitting") {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="处理中…" />
      </div>
    );
  }
  if (stage.kind === "answering") {
    return (
      <>
        {error && <ErrorBox message={error} />}
        <AnsweringView
          data={stage.data}
          modeLabel="错题重练"
          onRestart={() => setStage({ kind: "list" })}
          onSubmit={(answers) => void submit(answers)}
        />
      </>
    );
  }
  if (stage.kind === "result") {
    return <ResultView data={stage.data} onRestart={() => setStage({ kind: "list" })} />;
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">错题本</h1>
          <p className="mt-1 text-sm text-slate-500">
            练习中答错的题目自动收录，按错误次数排序，可一键重练
          </p>
        </div>
        <Button onClick={() => void startPractice()} disabled={mistakes.length === 0 || loading}>
          错题重练（5 题）
        </Button>
      </header>

      {error && <ErrorBox message={error} />}

      <Card title={`错题（${mistakes.length}）`}>
        {loading ? (
          <div className="flex justify-center py-8">
            <Spinner label="加载中…" />
          </div>
        ) : mistakes.length === 0 ? (
          <EmptyState text="还没有错题。去「练习」页做一组题吧，答错的题会自动收录到这里。" />
        ) : (
          <div className="space-y-4">
            {mistakes.map((m) => (
              <div key={m.question_id} className="rounded-lg border border-slate-200 p-4">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <Badge tone={m.type === "multi_choice" ? "amber" : "indigo"}>
                    {m.type === "single_choice" ? "单选" : m.type === "multi_choice" ? "多选" : "简答"}
                  </Badge>
                  {m.knowledge_points.map((kp) => (
                    <Badge key={kp}>{kp}</Badge>
                  ))}
                  <Badge tone="red">错 {m.wrong_count} 次</Badge>
                  {m.last_wrong_at && (
                    <span className="text-xs text-slate-400">最近答错：{m.last_wrong_at}</span>
                  )}
                </div>
                <p className="whitespace-pre-wrap text-sm text-slate-800">{m.stem}</p>
                <p className="mt-2 text-sm">
                  <span className="text-slate-500">正确答案：</span>
                  <span className="font-medium text-emerald-700">{m.correct_answer}</span>
                  <span className="ml-3 text-slate-500">你的历史答案：</span>
                  <span className="text-red-600">{m.user_answers.join(" / ") || "（未作答）"}</span>
                </p>
                {m.explanation && (
                  <p className="mt-2 text-sm leading-relaxed text-slate-600">解析：{m.explanation}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
