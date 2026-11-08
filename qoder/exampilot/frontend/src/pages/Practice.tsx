import { useEffect, useState } from "react";
import { api, type Course, type PracticeStart, type PracticeSubmit, type SessionInfo } from "../api";
import { AnsweringView, ResultView } from "../components/PracticeFlow";
import { Button, Card, ErrorBox, Spinner } from "../components/ui";

type Stage =
  | { kind: "setup" }
  | { kind: "answering"; data: PracticeStart }
  | { kind: "submitting" }
  | { kind: "result"; data: PracticeSubmit };

export default function Practice({ session }: { session: SessionInfo }) {
  const [stage, setStage] = useState<Stage>({ kind: "setup" });
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState<number | null>(null);
  const [mode, setMode] = useState<"mixed" | "weak">("mixed");
  const [count, setCount] = useState(5);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .courses(session.id)
      .then(setCourses)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [session.id]);

  const start = async () => {
    setError(null);
    setStage({ kind: "submitting" });
    try {
      const data = await api.startPractice(session.id, {
        course_id: courseId,
        knowledge_point_ids: [],
        count,
        mode,
      });
      setStage({ kind: "answering", data });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStage({ kind: "setup" });
    }
  };

  const submit = async (answers: { question_id: number; answer: string }[]) => {
    const cur = stage;
    if (cur.kind !== "answering") return;
    setStage({ kind: "submitting" });
    try {
      const result = await api.submitPractice(cur.data.practice_session_id, answers);
      setStage({ kind: "result", data: result });
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
          modeLabel={stage.data.mode === "weak" ? "薄弱点专练" : "综合练习"}
          onRestart={() => setStage({ kind: "setup" })}
          onSubmit={(answers) => void submit(answers)}
        />
      </>
    );
  }
  if (stage.kind === "result") {
    return <ResultView data={stage.data} onRestart={() => setStage({ kind: "setup" })} />;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header>
        <h1 className="text-xl font-bold text-slate-800">练习</h1>
        <p className="mt-1 text-sm text-slate-500">
          从题库抽题练习，自动判分并更新知识点掌握度，错题自动进入错题本
        </p>
      </header>
      {error && <ErrorBox message={error} />}
      <Card title="开始一组新练习">
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">练习模式</label>
            <div className="flex gap-2">
              <label className={`flex-1 cursor-pointer rounded-lg border p-3 text-sm ${mode === "mixed" ? "border-indigo-400 bg-indigo-50" : "border-slate-200"}`}>
                <input type="radio" className="hidden" checked={mode === "mixed"} onChange={() => setMode("mixed")} />
                <span className="font-medium text-slate-700">综合练习</span>
                <span className="mt-0.5 block text-xs text-slate-400">从题库随机抽题</span>
              </label>
              <label className={`flex-1 cursor-pointer rounded-lg border p-3 text-sm ${mode === "weak" ? "border-indigo-400 bg-indigo-50" : "border-slate-200"}`}>
                <input type="radio" className="hidden" checked={mode === "weak"} onChange={() => setMode("weak")} />
                <span className="font-medium text-slate-700">薄弱点专练</span>
                <span className="mt-0.5 block text-xs text-slate-400">优先练习掌握度最低的知识点</span>
              </label>
            </div>
          </div>
          <div className="flex gap-4">
            <div className="flex-1">
              <label className="mb-1 block text-xs font-medium text-slate-500">课程</label>
              <select
                value={courseId ?? ""}
                onChange={(e) => setCourseId(e.target.value === "" ? null : Number(e.target.value))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              >
                <option value="">默认课程</option>
                {courses.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}（{c.question_count} 题）
                  </option>
                ))}
              </select>
            </div>
            <div className="w-40">
              <label className="mb-1 block text-xs font-medium text-slate-500">题数</label>
              <select
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              >
                {[3, 5, 10, 20].map((n) => (
                  <option key={n} value={n}>
                    {n} 题
                  </option>
                ))}
              </select>
            </div>
          </div>
          <Button onClick={() => void start()} disabled={courses.length === 0}>
            开始练习
          </Button>
          {courses.length === 0 && (
            <p className="text-xs text-slate-400">尚未上传任何课程资料，请先到「资料管理」上传。</p>
          )}
        </div>
      </Card>
    </div>
  );
}
