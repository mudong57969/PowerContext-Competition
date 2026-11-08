import type { SearchHit } from "../api";
import { Badge } from "./ui";

export default function SourceList({ sources }: { sources: SearchHit[] }) {
  if (sources.length === 0) {
    return <p className="text-sm text-slate-400">无来源片段</p>;
  }
  return (
    <ul className="space-y-3">
      {sources.map((s) => (
        <li key={s.chunk_id} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="mb-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
            <span className="font-medium text-slate-700">{s.filename}</span>
            {s.page_number > 0 && <span>第 {s.page_number} 页</span>}
            <span>score {(s.score * 100).toFixed(1)}%</span>
            {s.matched_by.map((m) => (
              <Badge key={m} tone={m === "fts" ? "amber" : "indigo"}>
                {m === "fts" ? "全文匹配" : "向量匹配"}
              </Badge>
            ))}
          </div>
          <p className="text-sm leading-relaxed text-slate-700">{s.text}</p>
        </li>
      ))}
    </ul>
  );
}
