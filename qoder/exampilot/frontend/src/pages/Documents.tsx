import { useCallback, useEffect, useRef, useState } from "react";
import { api, type DocumentResult, type SessionInfo } from "../api";
import { Badge, Button, Card, EmptyState, ErrorBox, Spinner } from "../components/ui";

const CLASSIFY_TONE: Record<string, "green" | "amber" | "red" | "slate"> = {
  auto: "green",
  suggested: "amber",
  pending: "red",
  failed: "red",
};

function classifyLabel(status: string): string {
  if (status === "auto") return "自动分类";
  if (status === "suggested") return "建议分类（待确认）";
  if (status === "pending") return "待人工分类";
  if (status === "failed") return "分类失败";
  return status;
}

const REASON_LABEL: Record<string, string> = {
  insufficient_text: "文字过少，无法分类",
  no_signal: "无匹配信号，无法分类",
  new_course: "疑似新课程，建议确认",
  ambiguous: "候选信号接近，存在歧义",
  filename_conflict: "文件名与内容不一致，以内容为准",
  ok: "",
};

const REASON_TONE: Record<string, "amber" | "slate" | "red"> = {
  insufficient_text: "red",
  no_signal: "red",
  new_course: "amber",
  ambiguous: "amber",
  filename_conflict: "amber",
};

const SOURCE_LABEL: Record<string, string> = {
  lexicon: "词典",
  heading: "标题",
  filename: "文件名",
  existing: "已有课程",
  retrieval: "检索相似",
  pattern: "标题模式",
  stored_result: "历史结果",
};

function candidateLabel(c: { name: string; score: number; source: string }): string {
  const src = SOURCE_LABEL[c.source] ?? c.source;
  return `${c.name}（${Math.round(c.score * 100)}% · ${src}）`;
}

function usableCandidateName(doc: DocumentResult): string | null {
  return (
    doc.evidence_course ??
    doc.course_candidates?.find((c) => !c.name.startsWith("["))?.name ??
    null
  );
}

function CorrectDialog({
  doc,
  onClose,
  onSaved,
}: {
  doc: DocumentResult;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [course, setCourse] = useState(doc.course ?? doc.evidence_course ?? "");
  const [chapter, setChapter] = useState(doc.chapter ?? doc.evidence_chapter ?? "");
  const [kps, setKps] = useState(
    (doc.knowledge_points.length > 0
      ? doc.knowledge_points
      : (doc.evidence_knowledge_points ?? [])
    ).join("，"),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!course.trim()) {
      setError("请填写课程名称");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.correctDocument(doc.id!, {
        course: course.trim(),
        chapter: chapter.trim() === "" ? null : chapter.trim(),
        knowledge_points: kps
          .split(/[，,、;；]/)
          .map((s) => s.trim())
          .filter(Boolean),
      });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl bg-white p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-1 text-base font-bold text-slate-800">人工更正分类</h2>
        <p className="mb-4 text-xs text-slate-500">{doc.filename}</p>
        <div className="space-y-3">
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">课程（必填）</span>
            <input
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              value={course}
              onChange={(e) => setCourse(e.target.value)}
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">章节（可留空）</span>
            <input
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              value={chapter}
              onChange={(e) => setChapter(e.target.value)}
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">知识点（用逗号分隔，可留空）</span>
            <textarea
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              rows={3}
              value={kps}
              onChange={(e) => setKps(e.target.value)}
            />
          </label>
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button onClick={() => void submit()} disabled={saving}>
            {saving ? "保存中…" : "保存更正"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function Documents({ session }: { session: SessionInfo }) {
  const [docs, setDocs] = useState<DocumentResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<DocumentResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDocs(await api.listDocuments(session.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [session.id]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const outcome = await api.uploadDocuments(session.id, Array.from(files));
      const okCount = outcome.results.filter((r) => r.ok).length;
      const failCount = outcome.results.length - okCount;
      setNotice(
        `上传完成：成功 ${okCount} 个${failCount > 0 ? `，失败 ${failCount} 个` : ""}，正在解析与自动分类…`,
      );
      await new Promise((r) => setTimeout(r, 4000));
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const confirmDoc = async (doc: DocumentResult) => {
    if (!doc.id) return;
    // suggested documents have no course_id yet: fall back to the classifier's
    // stored evidence, then to the top usable candidate
    const course = doc.course ?? usableCandidateName(doc);
    if (!course) {
      setError("无法确认：该资料没有可用的课程候选，请使用「更正」手动填写");
      return;
    }
    const chapter = doc.chapter ?? doc.evidence_chapter ?? null;
    const kps =
      doc.knowledge_points.length > 0
        ? doc.knowledge_points
        : (doc.evidence_knowledge_points ?? []);
    setError(null);
    setNotice(null);
    try {
      await api.confirmDocument(doc.id, {
        course,
        chapter,
        knowledge_points: kps,
      });
      setNotice(`已确认「${doc.filename}」的分类结果`);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const reclassifyDoc = async (doc: DocumentResult) => {
    if (!doc.id) return;
    setError(null);
    setNotice(null);
    try {
      await api.reclassifyDocument(doc.id);
      setNotice(`已重新分类「${doc.filename}」`);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">资料管理</h1>
          <p className="mt-1 text-sm text-slate-500">
            支持 PDF / PPTX / MD / TXT，上传后自动解析并分类到「课程 → 章节 → 知识点」
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.pptx,.md,.txt,.markdown"
          className="hidden"
          onChange={(e) => void onFiles(e.target.files)}
        />
        <Button onClick={() => inputRef.current?.click()} disabled={uploading}>
          {uploading ? "上传中…" : "上传资料"}
        </Button>
      </header>

      {error && <ErrorBox message={error} />}
      {notice && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {notice}
        </div>
      )}

      <Card title={`已上传资料（${docs.length}）`}>
        {loading ? (
          <div className="flex justify-center py-8">
            <Spinner label="加载中…" />
          </div>
        ) : docs.length === 0 ? (
          <EmptyState text="还没有上传任何资料。点击右上角「上传资料」开始。" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-400">
                  <th className="py-2 pr-3 font-medium">文件名</th>
                  <th className="py-2 pr-3 font-medium">类型</th>
                  <th className="py-2 pr-3 font-medium">解析</th>
                  <th className="py-2 pr-3 font-medium">分类状态</th>
                  <th className="py-2 pr-3 font-medium">课程</th>
                  <th className="py-2 pr-3 font-medium">章节</th>
                  <th className="py-2 pr-3 font-medium">知识点</th>
                  <th className="py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.filename} className="border-b border-slate-50 align-top">
                    <td className="max-w-[180px] py-2.5 pr-3 font-medium text-slate-700">
                      {d.filename}
                      {d.duplicate && <Badge tone="slate">重复</Badge>}
                    </td>
                    <td className="py-2.5 pr-3 text-slate-500">
                      {d.file_type.toUpperCase()}
                      {d.page_count > 0 && ` (${d.page_count}页)`}
                    </td>
                    <td className="py-2.5 pr-3">
                      {d.parse_status === "ok" ? (
                        <Badge tone="green">已解析</Badge>
                      ) : (
                        <Badge tone="red">{d.parse_status}</Badge>
                      )}
                      {d.ocr_required && <Badge tone="amber">需OCR</Badge>}
                      {typeof d.extracted_chars === "number" && (
                        <div className="mt-1 text-xs text-slate-400">提取 {d.extracted_chars} 字</div>
                      )}
                    </td>
                    <td className="py-2.5 pr-3">
                      <Badge tone={CLASSIFY_TONE[d.classify_status] ?? "slate"}>
                        {classifyLabel(d.classify_status)}
                      </Badge>
                      {d.classify_confidence > 0 && (
                        <div className="mt-1 text-xs text-slate-400">
                          置信度 {(d.classify_confidence * 100).toFixed(0)}%
                        </div>
                      )}
                      {d.classify_reason && REASON_LABEL[d.classify_reason] && (
                        <div className="mt-1">
                          <Badge tone={REASON_TONE[d.classify_reason] ?? "slate"}>
                            {REASON_LABEL[d.classify_reason]}
                          </Badge>
                        </div>
                      )}
                      {(d.classify_status === "pending" || d.classify_status === "suggested") &&
                        (d.course_candidates?.length ?? 0) > 0 && (
                          <div className="mt-1 space-y-0.5 text-xs text-slate-500">
                            <div className="text-slate-400">课程候选：</div>
                            {d.course_candidates!.slice(0, 3).map((c) => (
                              <div key={c.name}>{candidateLabel(c)}</div>
                            ))}
                          </div>
                        )}
                    </td>
                    <td className="py-2.5 pr-3 text-slate-600">{d.course ?? "—"}</td>
                    <td className="py-2.5 pr-3 text-slate-600">{d.chapter ?? "—"}</td>
                    <td className="max-w-[220px] py-2.5 pr-3">
                      <div className="flex flex-wrap gap-1">
                        {(d.knowledge_points.length > 0
                          ? d.knowledge_points
                          : (d.evidence_knowledge_points ?? [])
                        ).length === 0
                          ? "—"
                          : (d.knowledge_points.length > 0
                              ? d.knowledge_points
                              : d.evidence_knowledge_points!
                            ).map((kp) => {
                              const slides = d.kp_evidence?.[kp];
                              return (
                                <span key={kp} title={slides?.length ? `来源幻灯片：${slides.join(", ")}` : undefined}>
                                  <Badge>
                                    {kp}
                                    {slides?.length ? ` (${slides.length}页)` : ""}
                                  </Badge>
                                </span>
                              );
                            })}
                      </div>
                    </td>
                    <td className="py-2.5">
                      <div className="flex flex-wrap gap-2">
                        {d.classify_status === "suggested" && d.id && (
                          <Button variant="secondary" className="px-2.5 py-1 text-xs" onClick={() => void confirmDoc(d)}>
                            确认
                          </Button>
                        )}
                        {d.classify_status === "pending" && d.id && usableCandidateName(d) && (
                          <Button variant="secondary" className="px-2.5 py-1 text-xs" onClick={() => void confirmDoc(d)}>
                            确认候选
                          </Button>
                        )}
                        {d.id && (
                          <Button variant="ghost" className="px-2.5 py-1 text-xs" onClick={() => setCorrecting(d)}>
                            更正
                          </Button>
                        )}
                        {d.id && (
                          <Button variant="ghost" className="px-2.5 py-1 text-xs" onClick={() => void reclassifyDoc(d)}>
                            重新分类
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {correcting && (
        <CorrectDialog
          doc={correcting}
          onClose={() => setCorrecting(null)}
          onSaved={() => {
            setCorrecting(null);
            setNotice(`已人工更正「${correcting.filename}」`);
            void reload();
          }}
        />
      )}
    </div>
  );
}
