import { useCallback, useEffect, useState } from "react";
import { HashRouter, Route, Routes } from "react-router-dom";
import {
  api,
  ApiError,
  clearIdentity,
  getToken,
  SESSION_KEY,
  TOKEN_KEY,
  type Health,
  type SessionInfo,
} from "./api";
import Layout from "./components/Layout";
import { Button, Spinner } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Documents from "./pages/Documents";
import Search from "./pages/Search";
import Explain from "./pages/Explain";
import Practice from "./pages/Practice";
import Mistakes from "./pages/Mistakes";
import Review from "./pages/Review";
import Memory from "./pages/Memory";

function BackendDown({ message }: { message: string }) {
  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="w-full max-w-lg rounded-xl border border-red-200 bg-white p-6 shadow-sm">
        <h1 className="mb-2 text-lg font-bold text-red-700">无法连接 ExamPilot 后端</h1>
        <p className="mb-4 text-sm leading-relaxed text-slate-600">{message}</p>
        <div className="rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-slate-500">
          本地开发时，请在 WSL 中启动后端（见 README「快速开始」）：
          <code className="mx-1 rounded bg-slate-200 px-1 py-0.5">
            &lt;venv&gt;/bin/uvicorn app.main:app --port 8001
          </code>
          （后端目录 backend/，需先激活 PowerContext 服务）。启动后刷新本页。
        </div>
        <div className="mt-4">
          <Button onClick={() => window.location.reload()}>重试连接</Button>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [booting, setBooting] = useState(true);

  const ensureSession = useCallback(async () => {
    const token = getToken();
    if (token) {
      try {
        const info = await api.me();
        return info;
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          // Token was invalidated or lost server-side: the old anonymous
          // identity is unrecoverable without a backup, so start a fresh one.
          clearIdentity();
        } else {
          throw err;
        }
      }
    }
    const created = await api.createIdentity("我的备考会话");
    localStorage.setItem(TOKEN_KEY, created.token);
    localStorage.setItem(SESSION_KEY, created.session.id);
    return created.session;
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const h = await api.health();
        if (cancelled) return;
        setHealth(h);
        const s = await ensureSession();
        if (cancelled) return;
        setSession(s);
        setBootError(null);
      } catch (err) {
        if (!cancelled) {
          setBootError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setBooting(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ensureSession]);

  const handleResetIdentity = () => {
    const confirmed = window.confirm(
      "确定要重置匿名身份吗？当前身份的学习数据只有通过其 Token 才能访问，" +
        "若未备份 Token，重置后旧数据将无法恢复。",
    );
    if (!confirmed) return;
    clearIdentity();
    window.location.reload();
  };

  if (booting) {
    return (
      <div className="flex min-h-full items-center justify-center">
        <Spinner label="正在连接 ExamPilot 服务…" />
      </div>
    );
  }
  if (bootError || !session) {
    return <BackendDown message={bootError ?? "会话初始化失败"} />;
  }
  return (
    <HashRouter>
      <Layout health={health} sessionName={session.name} onResetIdentity={handleResetIdentity}>
        <Routes>
          <Route path="/" element={<Dashboard session={session} />} />
          <Route path="/documents" element={<Documents session={session} />} />
          <Route path="/search" element={<Search session={session} />} />
          <Route path="/explain" element={<Explain session={session} />} />
          <Route path="/practice" element={<Practice session={session} />} />
          <Route path="/mistakes" element={<Mistakes session={session} />} />
          <Route path="/review" element={<Review session={session} />} />
          <Route path="/memory" element={<Memory session={session} />} />
        </Routes>
      </Layout>
    </HashRouter>
  );
}
