import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Preferences, type ReviewPlan, type SessionInfo } from "../api";
import { Badge, Card, ErrorBox, Spinner, WarningBox } from "../components/ui";

export default function Dashboard({ session }: { session: SessionInfo }) {
  const [info, setInfo] = useState<SessionInfo>(session);
  const [review, setReview] = useState<ReviewPlan | null>(null);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [s, r, p] = await Promise.all([
          api.me(),
          api.reviewPlan(session.id),
          api.getPreferences(session.id),
        ]);
        setInfo(s);
        setReview(r);
        setPrefs(p);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    })();
  }, [session.id]);

  const stats = info.stats;
  const cards = [
    { label: "已上传资料", value: stats.documents, to: "/documents" },
    { label: "课程", value: stats.courses, to: "/search" },
    { label: "题库题目", value: stats.questions, to: "/practice" },
    { label: "已练习次数", value: stats.attempts, to: "/practice" },
    { label: "已掌握知识点", value: stats.mastered_knowledge_points, to: "/review" },
  ];

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="加载仪表盘…" />
      </div>
    );
  }

  const dueCount = review?.due.length ?? 0;

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <header>
        <h1 className="text-xl font-bold text-slate-800">学习仪表盘</h1>
        <p className="mt-1 text-sm text-slate-500">
          会话 <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{session.id}</code>
        </p>
      </header>

      {error && <ErrorBox message={error} />}
      {info.memory_warning && <WarningBox message={info.memory_warning} />}

      {prefs && (prefs.goal || prefs.exam_date) && (
        <Card title="备考目标">
          <div className="flex flex-wrap gap-3 text-sm text-slate-600">
            {prefs.goal && (
              <span>
                <Badge tone="indigo">目标</Badge> {prefs.goal}
              </span>
            )}
            {prefs.exam_date && (
              <span>
                <Badge tone="amber">考试日期</Badge> {prefs.exam_date}
              </span>
            )}
          </div>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        {cards.map((c) => (
          <Link key={c.label} to={c.to}>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md">
              <div className="text-2xl font-bold text-indigo-600">{c.value}</div>
              <div className="mt-1 text-xs text-slate-500">{c.label}</div>
            </div>
          </Link>
        ))}
      </div>

      <Card
        title="平均掌握度"
        actions={
          <span className="text-sm font-semibold text-indigo-600">
            {Math.round(stats.average_mastery * 100)}%
          </span>
        }
      >
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
          <div
            className="h-full rounded-full bg-indigo-500"
            style={{ width: `${Math.round(stats.average_mastery * 100)}%` }}
          />
        </div>
      </Card>

      <Card
        title="今日复习"
        actions={<Link to="/review" className="text-sm text-indigo-600 hover:underline">查看计划</Link>}
      >
        {dueCount === 0 ? (
          <p className="text-sm text-slate-400">今天没有到期的复习任务，继续保持！</p>
        ) : (
          <ul className="space-y-2">
            {review!.due.slice(0, 5).map((t) => (
              <li key={t.id} className="flex items-center justify-between text-sm">
                <span className="text-slate-700">{t.knowledge_point_name}</span>
                <Badge tone="amber">{t.reason}</Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
