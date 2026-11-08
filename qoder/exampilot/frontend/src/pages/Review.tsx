import { useCallback, useEffect, useState } from "react";
import { api, type ReviewPlan, type SessionInfo } from "../api";
import MasteryBar from "../components/MasteryBar";
import { Badge, Button, Card, EmptyState, ErrorBox, Spinner } from "../components/ui";

export default function Review({ session }: { session: SessionInfo }) {
  const [plan, setPlan] = useState<ReviewPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [completing, setCompleting] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPlan(await api.reviewPlan(session.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [session.id]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const complete = async (taskId: number, correct: boolean) => {
    setCompleting(taskId);
    setError(null);
    setNotice(null);
    try {
      const outcome = await api.completeReview(taskId, correct);
      setNotice(
        correct
          ? `已完成复习，掌握度提升${outcome.follow_up_task_id ? `，并生成了后续复习任务 #${outcome.follow_up_task_id}` : ""}。`
          : "已记录本次复习未通过，将安排巩固练习。",
      );
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCompleting(null);
    }
  };

  if (loading || !plan) {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="加载复习计划…" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <header>
        <h1 className="text-xl font-bold text-slate-800">复习计划</h1>
        <p className="mt-1 text-sm text-slate-500">
          基于间隔重复算法（复习间隔 1/2/4/7/15/30 天）自动生成，答对进入下一间隔，答错立即强化
        </p>
      </header>

      {error && <ErrorBox message={error} />}
      {notice && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {notice}
        </div>
      )}

      <Card title={`今日待复习（${plan.due.length}）`}>
        {plan.due.length === 0 ? (
          <EmptyState text="今天没有到期的复习任务。" />
        ) : (
          <div className="space-y-3">
            {plan.due.map((t) => (
              <div key={t.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 p-4">
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-slate-800">{t.knowledge_point_name}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                    {t.course_name && <span>{t.course_name}</span>}
                    {t.due_date && <span>到期日 {t.due_date}</span>}
                    <Badge tone="amber">{t.reason}</Badge>
                    {t.mastery_score !== null && <span>掌握度 {(t.mastery_score * 100).toFixed(0)}%</span>}
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    className="px-3 py-1.5 text-xs"
                    disabled={completing === t.id}
                    onClick={() => void complete(t.id, false)}
                  >
                    没掌握
                  </Button>
                  <Button
                    className="px-3 py-1.5 text-xs"
                    disabled={completing === t.id}
                    onClick={() => void complete(t.id, true)}
                  >
                    已掌握
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title={`即将到期（${plan.upcoming.length}）`}>
        {plan.upcoming.length === 0 ? (
          <EmptyState text="暂无即将到期的复习任务。" />
        ) : (
          <ul className="space-y-2">
            {plan.upcoming.map((t) => (
              <li key={t.id} className="flex items-center gap-3 text-sm">
                <span className="flex-1 text-slate-700">{t.knowledge_point_name}</span>
                <span className="text-xs text-slate-400">{t.due_date}</span>
                <Badge tone="slate">{t.reason}</Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={`知识点掌握度（${plan.mastery.length}）`}>
        {plan.mastery.length === 0 ? (
          <EmptyState text="还没有练习记录，去「练习」页开始第一组练习吧。" />
        ) : (
          <div className="space-y-3">
            {[...plan.mastery]
              .sort((a, b) => a.mastery_score - b.mastery_score)
              .map((m) => (
                <MasteryBar
                  key={m.knowledge_point_id}
                  label={m.name}
                  value={m.mastery_score}
                  practiceCount={m.practice_count}
                />
              ))}
          </div>
        )}
      </Card>
    </div>
  );
}
