import { useState } from "react";
import type { GradedAnswer, PracticeStart, PracticeSubmit } from "../api";
import MasteryBar from "./MasteryBar";
import { Badge, Button, Card } from "./ui";

function QuestionView({
  q,
  index,
  total,
  answer,
  setAnswer,
}: {
  q: PracticeStart["questions"][number];
  index: number;
  total: number;
  answer: string | undefined;
  setAnswer: (updater: string | ((prev: string | undefined) => string)) => void;
}) {
  const isChoice = q.type === "single_choice" || q.type === "multi_choice";
  const isMulti = q.type === "multi_choice";
  return (
    <Card title={`第 ${index + 1} / ${total} 题`}>
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <Badge tone={q.type === "single_choice" ? "indigo" : q.type === "multi_choice" ? "amber" : "green"}>
          {q.type === "single_choice" ? "单选题" : q.type === "multi_choice" ? "多选题" : "简答题"}
        </Badge>
        <Badge tone="slate">难度 {q.difficulty}</Badge>
        {q.knowledge_points.map((kp) => (
          <Badge key={kp}>{kp}</Badge>
        ))}
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-800">{q.stem}</p>
      {isChoice ? (
        <div className="mt-4 space-y-2">
          {q.options.map((opt) => {
            const selected = (answer ?? "").includes(opt.letter);
            return (
              <label
                key={opt.letter}
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm transition-colors ${
                  selected ? "border-indigo-400 bg-indigo-50" : "border-slate-200 hover:bg-slate-50"
                }`}
              >
                <input
                  type={isMulti ? "checkbox" : "radio"}
                  name={`q${q.id}`}
                  checked={selected}
                  onChange={() => {
                    if (isMulti) {
                      setAnswer((prev) => {
                        const cur = new Set(prev ?? "");
                        if (cur.has(opt.letter)) cur.delete(opt.letter);
                        else cur.add(opt.letter);
                        return [...cur].sort().join("");
                      });
                    } else {
                      setAnswer(opt.letter);
                    }
                  }}
                  className="mt-0.5 accent-indigo-600"
                />
                <span className="text-slate-700">
                  <span className="mr-1.5 font-semibold text-slate-500">{opt.letter}.</span>
                  {opt.text}
                </span>
              </label>
            );
          })}
        </div>
      ) : (
        <textarea
          value={answer ?? ""}
          onChange={(e) => setAnswer(e.target.value)}
          rows={3}
          placeholder="输入你的答案（判空 / 简答，按关键词评分）"
          className="mt-4 w-full rounded-lg border border-slate-300 px-4 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
        />
      )}
    </Card>
  );
}

export function AnsweringView({
  data,
  modeLabel,
  onRestart,
  onSubmit,
}: {
  data: PracticeStart;
  modeLabel: string;
  onRestart: () => void;
  onSubmit: (answers: { question_id: number; answer: string }[]) => void;
}) {
  const [answers, setAnswers] = useState<Map<number, string>>(new Map());
  const setAnswer = (qid: number) => (updater: string | ((prev: string | undefined) => string)) =>
    setAnswers((prevMap) => {
      const prev = prevMap.get(qid);
      const next = typeof updater === "string" ? updater : updater(prev);
      return new Map(prevMap).set(qid, next);
    });

  const handleSubmit = () => {
    const unanswered = data.questions.filter((q) => !answers.has(q.id));
    if (unanswered.length > 0) {
      const ok = window.confirm(`还有 ${unanswered.length} 题未作答，确认交卷？`);
      if (!ok) return;
    }
    onSubmit(
      data.questions.map((q) => ({ question_id: q.id, answer: answers.get(q.id) ?? "" })),
    );
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-slate-800">
          练习中 <Badge tone="indigo">{modeLabel}</Badge>
        </h1>
        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-500">
            已作答 {answers.size} / {data.total}
          </span>
          <Button variant="ghost" onClick={onRestart}>
            放弃
          </Button>
        </div>
      </header>
      {data.questions.map((q, i) => (
        <QuestionView key={q.id} q={q} index={i} total={data.total} answer={answers.get(q.id)} setAnswer={setAnswer(q.id)} />
      ))}
      <div className="flex justify-end pb-6">
        <Button onClick={handleSubmit}>交卷</Button>
      </div>
    </div>
  );
}

export function ResultView({
  data,
  onRestart,
}: {
  data: PracticeSubmit;
  onRestart: () => void;
}) {
  const pct = Math.round(data.score);
  const tone = pct >= 80 ? "text-emerald-600" : pct >= 60 ? "text-amber-600" : "text-red-600";
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header>
        <h1 className="text-xl font-bold text-slate-800">练习结果</h1>
      </header>
      <Card>
        <div className="flex items-center gap-6">
          <div className={`text-5xl font-bold ${tone}`}>{pct}</div>
          <div className="text-sm text-slate-500">
            <p>
              答对 {data.correct_count} / {data.total} 题
            </p>
            <p className="mt-1">生成了 {data.review_tasks_created} 个复习任务</p>
          </div>
          <div className="ml-auto">
            <Button onClick={onRestart}>再来一组</Button>
          </div>
        </div>
      </Card>

      {data.memory && data.memory.warning && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-700">
          记忆写入提示：{data.memory.warning}
        </div>
      )}

      {data.mastery.length > 0 && (
        <Card title="掌握度变化">
          <div className="space-y-3">
            {data.mastery.map((m) => (
              <MasteryBar key={m.knowledge_point_id} label={m.name} value={m.mastery_score} practiceCount={m.practice_count} />
            ))}
          </div>
        </Card>
      )}

      <Card title="逐题解析">
        <div className="space-y-4">
          {data.results.map((r: GradedAnswer, i) => (
            <div key={r.question_id} className={`rounded-lg border p-4 ${r.is_correct ? "border-emerald-200 bg-emerald-50/40" : "border-red-200 bg-red-50/40"}`}>
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-slate-400">第 {i + 1} 题</span>
                {r.is_correct ? <Badge tone="green">回答正确</Badge> : <Badge tone="red">回答错误</Badge>}
                <span className="ml-auto text-xs text-slate-400">得分 {r.score}</span>
              </div>
              <p className="mt-2 whitespace-pre-wrap text-sm text-slate-800">{r.stem}</p>
              <div className="mt-2 text-sm">
                <span className="text-slate-500">你的答案：</span>
                <span className={r.is_correct ? "text-emerald-700" : "text-red-700"}>{r.user_answer || "（未作答）"}</span>
                {!r.is_correct && (
                  <>
                    <span className="ml-3 text-slate-500">正确答案：</span>
                    <span className="font-medium text-emerald-700">{r.correct_answer}</span>
                  </>
                )}
              </div>
              {r.evidence && (
                <p className="mt-2 rounded bg-white/70 p-2 text-xs leading-relaxed text-slate-500">
                  判分依据：{r.evidence}
                </p>
              )}
              {r.explanation && (
                <p className="mt-2 text-sm leading-relaxed text-slate-600">解析：{r.explanation}</p>
              )}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
