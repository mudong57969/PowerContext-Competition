import { ProgressBar } from "./ui";

export default function MasteryBar({
  label,
  value,
  practiceCount,
}: {
  label: string;
  value: number;
  practiceCount?: number;
}) {
  const pct = Math.round(value * 100);
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-sm">
        <span className="font-medium text-slate-700">{label}</span>
        <span className="text-xs text-slate-400">
          {practiceCount !== undefined && practiceCount > 0
            ? `练习 ${practiceCount} 次`
            : "尚未练习"}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <ProgressBar value={pct} />
        <span className="w-10 text-right text-xs font-semibold text-indigo-600">{pct}%</span>
      </div>
    </div>
  );
}
