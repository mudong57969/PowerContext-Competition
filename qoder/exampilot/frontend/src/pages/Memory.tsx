import { useCallback, useEffect, useState } from "react";
import { api, type MemoryEvent, type MemorySearchResponse, type SessionInfo } from "../api";
import { Badge, Button, Card, EmptyState, ErrorBox, Spinner, WarningBox } from "../components/ui";

const KIND_LABEL: Record<string, string> = {
  mastery: "掌握度",
  mistake: "错题",
  study_goal: "学习目标",
  exam_date: "考试日期",
  chat: "对话",
  note: "笔记",
};

export default function Memory({ session }: { session: SessionInfo }) {
  const [events, setEvents] = useState<MemoryEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [searchResult, setSearchResult] = useState<MemorySearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [note, setNote] = useState("");
  const [writing, setWriting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setEvents(await api.memoryEvents(session.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [session.id]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const search = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    try {
      setSearchResult(await api.memorySearch(session.id, query.trim(), 10));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  };

  const writeNote = async () => {
    if (!note.trim()) return;
    setWriting(true);
    setError(null);
    setNotice(null);
    try {
      const outcome = await api.writeMemory(session.id, "note", note.trim());
      setNotice(outcome.ok ? "已写入长期记忆（PowerContext）。" : `写入提示：${outcome.warning ?? "未确认写入"}`);
      setNote("");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setWriting(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <header>
        <h1 className="text-xl font-bold text-slate-800">长期记忆</h1>
        <p className="mt-1 text-sm text-slate-500">
          跨会话记忆由 PowerContext 驱动：掌握度、错题、学习目标自动沉淀，可检索、可显式写入
        </p>
      </header>

      {session.memory_warning && <WarningBox message={session.memory_warning} />}
      {error && <ErrorBox message={error} />}
      {notice && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {notice}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="记忆检索">
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void search();
              }}
              placeholder="例如：我哪些知识点最薄弱？"
              className="flex-1 rounded-lg border border-slate-300 px-4 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            />
            <button
              onClick={() => void search()}
              disabled={searching || !query.trim()}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:bg-indigo-300"
            >
              搜索
            </button>
          </div>
          <div className="mt-3">
            {searching ? (
              <Spinner label="检索中…" />
            ) : searchResult ? (
              searchResult.available ? (
                <ul className="space-y-2">
                  {searchResult.hits.length === 0 ? (
                    <EmptyState text="没有匹配的记忆。" />
                  ) : (
                    searchResult.hits.map((h, i) => (
                      <li key={i} className="rounded-lg border border-indigo-100 bg-indigo-50/50 p-3 text-sm text-slate-700">
                        {h.text}
                        <div className="mt-1 flex items-center gap-2 text-xs text-slate-400">
                          <span>score {h.score.toFixed(2)}</span>
                          {h.matched_by.map((m) => (
                            <Badge key={m} tone="slate">{m}</Badge>
                          ))}
                        </div>
                      </li>
                    ))
                  )}
                </ul>
              ) : (
                <WarningBox message={searchResult.warning ?? "PowerContext 记忆服务不可用"} />
              )
            ) : (
              <p className="text-xs text-slate-400">输入问题搜索你的长期学习记忆。</p>
            )}
          </div>
        </Card>

        <Card title="显式写入一条记忆">
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            placeholder="例如：我在做时序分析题时总是忘记 setup time 和 hold time 的定义，需要重点复习。"
            className="w-full resize-none rounded-lg border border-slate-300 px-4 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
          />
          <div className="mt-3">
            <Button onClick={() => void writeNote()} disabled={writing || !note.trim()}>
              {writing ? "写入中…" : "写入记忆"}
            </Button>
          </div>
          <p className="mt-2 text-xs text-slate-400">
            写入后会被写入 PowerContext 记忆库，下次会话中检索「薄弱点」等问题时可以召回。
          </p>
        </Card>
      </div>

      <Card title={`记忆事件流（最近 ${events.length} 条）`}>
        {loading ? (
          <div className="flex justify-center py-8">
            <Spinner label="加载中…" />
          </div>
        ) : events.length === 0 ? (
          <EmptyState text="还没有记忆事件。练习、设定目标后会自动写入。" />
        ) : (
          <div className="space-y-2">
            {events.map((e) => (
              <div key={e.id} className="flex items-start gap-3 rounded-lg border border-slate-100 p-3">
                <Badge tone={e.status === "stored" ? "green" : "amber"}>
                  {KIND_LABEL[e.kind] ?? e.kind}
                </Badge>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-slate-700">{e.summary}</p>
                  <p className="mt-0.5 text-xs text-slate-400">
                    {e.memory_reference ? `PowerContext 引用：${e.memory_reference}` : e.status}
                    {e.created_at ? ` · ${e.created_at}` : ""}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
