# ExamPilot 部署说明

> 本地一键运行 + Qoder Sites 发布方案。发布涉及公网暴露与费用，正式发布前需取得用户授权（见文末「授权清单」）。

## 1. 环境要求

| 组件 | 要求 |
| --- | --- |
| 操作系统 | Windows 10/11 + WSL2（Ubuntu 24.04）；或原生 Linux/macOS |
| Python | 3.12（WSL 内） |
| Node.js | ≥ 20（Windows 宿主） |
| 依赖 | WSL venv：`powercontext[client,server,seekdb]==1.2.0` + 项目依赖；前端 `npm install` |

> 为什么用 WSL2：seekdb 嵌入式引擎（pylibseekdb）仅支持 Linux/macOS。后端在 WSL 内运行，代码位于 Windows 仓库目录（`qoder/exampilot/backend`，经 `/mnt/d` 挂载执行），数据目录必须在 WSL 原生文件系统。

## 2. 本地运行（三步）

### 2.1 启动 PowerContext 服务（WSL）

```bash
export POWERCONTEXT_HOME=/home/$USER/exampilot-data/powercontext
export POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1
export POWERCONTEXT_SERVER_HTTP_PORT=8000
export POWERCONTEXT_SERVER_DATABASE_KIND=seekdb
export POWERCONTEXT_SERVER_DATABASE_PATH=$POWERCONTEXT_HOME/seekdb
export POWERCONTEXT_SERVER_ACCESS_MODE=disabled   # 本机无需鉴权；公网部署必须启用鉴权
powercontext server run
```

### 2.2 启动后端（WSL）

```bash
export EXAMPILOT_SEEKDB_PATH=/home/$USER/exampilot-data/seekdb-exampilot
export EXAMPILOT_EMBEDDING_PROVIDER=local
export EXAMPILOT_POWERCONTEXT_BASE_URL=http://127.0.0.1:8000
export HF_ENDPOINT=https://hf-mirror.com   # 国内首次下载 bge-small-zh-v1.5 需要
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

本机已配置一键常驻脚本 `start_exampilot.sh`（setsid 后台运行，日志 `/tmp/exampilot_backend.log`；属开发机本地配置，不在仓库内）。

健康检查：`GET http://127.0.0.1:8001/api/health` 应返回 seekdb ok、memory reachable、embedding enabled。

### 2.3 启动前端（Windows）

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173 ，/api 自动代理到 8001
```

验收样例：见 [README 第 4 节](../README.md#4-验收样例)。

## 3. Qoder Sites 发布方案

Qoder Sites 支持**静态站点 + Edge Function**，不能运行 Python 进程或 seekdb。因此采用前后端分离：

### 3.1 前端：静态托管（Qoder Sites）

- `frontend` 构建产物为纯静态 SPA（HashRouter），可直接发布到 Qoder Sites。
- 构建：`cd frontend && npm run build` → 产物 `frontend/dist/`。
- 配置：`.env.production` 中设置 `VITE_API_BASE_URL=<后端公网地址>`（API 地址属于公开信息，可安全内置于前端）。
- 前端本身**不含任何密钥**、不含真实课程资料内容（资料全部在后端 seekdb 中）。

### 3.2 后端：需用户授权的公网部署（三选一）

后端是完整 FastAPI 服务，含 seekdb 引擎与本地向量模型，Qoder Sites 无法承载，需要一台 Linux 服务器或等效环境：

| 方案 | 说明 | 成本 | 备注 |
| --- | --- | --- | --- |
| A. 云服务器 | 阿里云/腾讯云等 2C2G 以上 Linux 实例，部署同一套 PowerContext + 后端 | 约 ¥50–100/月 | 需用户账号与实名认证 |
| B. 现有 Linux 主机 | 用户自有的可公网访问 Linux 机器 | 0 | 需用户提供 |
| C. 仅本地演示 | 不公网部署，比赛验收以本机演示 + 证据目录为准 | 0 | 无需授权，但站点不可公网访问 |

> **当前决定（2026-11-06，经用户确认）**：采用方案 C「仅本地演示」，Qoder Sites 暂不发布。后续如需公网部署，按第 5 节授权清单重新确认后执行。

### 3.3 安全要求（公网部署时强制执行）

- **API 密钥仅存服务端**：`EXAMPILOT_OPENAI_API_KEY` 等一律放服务器环境变量，绝不进前端代码或仓库。
- **PowerContext 必须启用鉴权**：`POWERCONTEXT_SERVER_ACCESS_MODE` 不得为 `disabled`；同时后端与 PowerContext 仅允许内网互访（如 127.0.0.1 绑定 + 反向代理只暴露 8001）。
- **不公开真实课程资料**：比赛验收使用 `samples/` 样例讲义（CMOS 数字电路公开教材内容），不上传任何真实课程/教材资料。
- **CORS 白名单**：`EXAMPILOT_CORS_ORIGINS` 仅放 Qoder Sites 站点域名。
- **会话隔离**：演示模式下 session 以浏览器 localStorage 为准，公网多用户访问各自隔离，不会互相读取资料。

## 4. 发布操作流程（待授权后执行）

1. 前端构建 → 通过 Qoder Sites 上传 `frontend/dist/` → 预览确认。
2. 后端按选定方案（3.2 的 A/B/C）部署并健康检查。
3. 前端 `.env.production` 指向公网后端 → 重新构建发布。
4. 公网验收样例跑通（README 7 步）→ 记录为发布证据。

## 5. 授权清单（发布前需用户确认）

按比赛要求，正式发布前需用户逐项确认：

1. **站点可见范围**：Qoder Sites 发布后站点对公网可见（或按用户要求设置访问限制）。
2. **费用**：Qoder Sites 静态托管是否产生费用以平台计费为准；后端云服务器约 ¥50–100/月（若选方案 A）。
3. **安全影响**：站点将暴露 FastAPI 接口；将按 3.3 执行密钥与 PowerContext 鉴权加固；样例数据为公开教材内容，不含隐私。
4. **授权**：请明确选择后端方案 A / B / C，并确认是否执行发布。
