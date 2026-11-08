import { NavLink } from "react-router-dom";
import type { Health } from "../api";

const NAV = [
  { to: "/", label: "仪表盘", icon: "📊", end: true },
  { to: "/documents", label: "资料管理", icon: "📚" },
  { to: "/search", label: "知识检索", icon: "🔍" },
  { to: "/explain", label: "AI 讲解", icon: "💡" },
  { to: "/practice", label: "练习", icon: "✏️" },
  { to: "/mistakes", label: "错题本", icon: "📕" },
  { to: "/review", label: "复习计划", icon: "📅" },
  { to: "/memory", label: "长期记忆", icon: "🧠" },
];

function HealthChips({ health }: { health: Health | null }) {
  if (!health) return null;
  return (
    <div className="space-y-1.5 text-[11px]">
      <div className="flex items-center gap-1.5 text-slate-500">
        <span className={`h-2 w-2 rounded-full ${health.seekdb.ok ? "bg-emerald-500" : "bg-red-500"}`} />
        seekdb {health.seekdb.ok ? "正常" : "异常"}
        {health.seekdb.database ? ` · ${health.seekdb.database}` : ""}
      </div>
      <div className="flex items-center gap-1.5 text-slate-500">
        <span className={`h-2 w-2 rounded-full ${health.memory.reachable ? "bg-emerald-500" : "bg-amber-500"}`} />
        PowerContext {health.memory.enabled && health.memory.reachable ? "已连接" : "未连接"}
      </div>
      <div className="flex items-center gap-1.5 text-slate-500">
        <span className={`h-2 w-2 rounded-full ${health.embedding.enabled ? "bg-emerald-500" : "bg-red-500"}`} />
        {health.embedding.provider} {health.embedding.enabled ? `· ${health.embedding.model}` : "未启用"}
      </div>
    </div>
  );
}

export default function Layout({
  health,
  sessionName,
  onResetIdentity,
  children,
}: {
  health: Health | null;
  sessionName?: string;
  onResetIdentity?: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-full">
      <aside className="fixed inset-y-0 left-0 z-10 flex w-56 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-5 py-4">
          <div className="text-lg font-bold text-indigo-700">ExamPilot</div>
          <div className="text-xs text-slate-400">智能备考教练</div>
          {sessionName && (
            <div className="mt-1 truncate text-[11px] text-slate-500" title={`当前身份：${sessionName}`}>
              身份：{sessionName}
            </div>
          )}
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-indigo-50 font-medium text-indigo-700"
                    : "text-slate-600 hover:bg-slate-50"
                }`
              }
            >
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-100 px-5 py-3">
          <HealthChips health={health} />
          {onResetIdentity && (
            <button
              onClick={onResetIdentity}
              className="mt-2 w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[11px] text-slate-500 hover:bg-slate-50"
              title="清除本机保存的匿名身份 Token 并创建新身份。旧身份若未备份 Token 将无法再恢复。"
            >
              重置匿名身份
            </button>
          )}
        </div>
      </aside>
      <main className="ml-56 flex-1 p-6">{children}</main>
    </div>
  );
}
