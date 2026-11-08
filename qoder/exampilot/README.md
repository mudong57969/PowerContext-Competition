# ExamPilot 智能备考教练

AI 个性化考试教练平台：上传课程资料 → 自动三级分类（课程/章节/知识点）→ 知识检索 → AI 讲解 → 练习与判分 → 错题本 → 掌握度追踪 → 复习计划 → 跨会话长期记忆。

本项目为 2026 OceanBase × Qoder 比赛参赛作品，主要由 Qoder 开发。核心亮点是**真实使用 OceanBase seekdb**（嵌入式数据库：全文检索 trigram 方案 + 向量检索 + 混合 RRF 融合）与 **PowerContext**（跨会话长期记忆）。

## 功能总览

| 模块 | 能力 | 核心技术 |
| --- | --- | --- |
| 资料管理 | PDF/PPTX/MD/TXT 批量上传、解析、去重 | pypdf / python-pptx |
| 自动分类 | 课程 → 章节 → 知识点 三级分类，置信度分级（自动/建议/待人工） | 词典 + 检索信号加权 |
| 知识检索 | 中文全文检索（trigram 分词方案）+ 语义向量检索，RRF 融合，来源可溯源 | seekdb FULLTEXT + VECTOR(l2_distance) + HNSW 索引 |
| AI 讲解 | 基于资料片段的检索增强讲解，附引用来源 | 检索增强模板 / 可接 OpenAI 兼容 LLM |
| 练习判分 | 单选/多选/简答/判断，逐题判分依据，自动更新掌握度 | 关键词覆盖率 + 字母提取判分 |
| 错题本 | 错题自动收录（错次/历史答案/解析），一键错题重练 | seekdb 持久化 |
| 掌握度 | 正确率 + 连续答对加权，跨轮累计 | 0.75×准确率 + 0.25×streak |
| 复习计划 | 间隔重复排期（1/2/4/7/15/30 天），答错立即强化 | 复习任务调度 |
| 长期记忆 | 掌握度/错题/学习目标自动沉淀，跨会话可检索、可显式写入 | PowerContext（seekdb 后端） |

## 快速开始（本地开发）

> 注意：seekdb 为 Linux/macOS 嵌入式引擎，Windows 下请使用 WSL2（Ubuntu 24.04）。

### 1. 启动 PowerContext 服务（WSL）

```bash
export POWERCONTEXT_HOME=/home/$USER/exampilot-data/powercontext
export POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1
export POWERCONTEXT_SERVER_HTTP_PORT=8000
export POWERCONTEXT_SERVER_DATABASE_KIND=seekdb
export POWERCONTEXT_SERVER_DATABASE_PATH=$POWERCONTEXT_HOME/seekdb
export POWERCONTEXT_SERVER_ACCESS_MODE=disabled
powercontext server run
```

### 2. 启动后端（WSL）

```bash
export EXAMPILOT_SEEKDB_PATH=/home/$USER/exampilot-data/seekdb-exampilot
export EXAMPILOT_EMBEDDING_PROVIDER=local
export EXAMPILOT_POWERCONTEXT_BASE_URL=http://127.0.0.1:8000
export HF_ENDPOINT=https://hf-mirror.com        # 国内下载 bge-small-zh-v1.5 需要
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

（本机另有一键常驻脚本 `start_exampilot.sh`（setsid 后台运行，日志 `/tmp/exampilot_backend.log`），属于开发机本地配置，不在仓库内；如需可参照部署文档自行编写。）

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173 ，/api 自动代理到 8001
```

### 4. 验收样例

1. 打开「资料管理」，上传 `samples/cmos_notes.md`（或 `samples/cmos_notes.pdf`）→ 自动解析并分类（置信度 ≥ 80% 自动通过，识别 12 个知识点）。
2. 「知识检索」搜「动态功耗由哪两部分组成？」→ 混合检索命中（全文 + 向量双来源）。
3. 「练习」开始一组 5 题练习 → 交卷 → 逐题判分依据 + 掌握度变化。
4. 「错题本」查看自动收录的错题 → 错题重练。
5. 「复习计划」查看按间隔重复排期的复习任务 → 标记完成。
6. 「长期记忆」查看 PowerContext 事件流（含真实 entry_id），搜索「哪些知识点最薄弱」验证跨会话召回。
7. 新建会话（清空浏览器 localStorage 后刷新），再次搜索记忆 —— 上一个会话的薄弱点仍然可召回（跨会话记忆）。

## 测试

```bash
# WSL 中（seekdb 为 Linux/macOS 引擎）
cd backend
pytest -q          # 145 项：单元测试 + 真实 seekdb 引擎集成测试（含安全与分类回归）
```

Windows 下集成测试自动跳过（drvfs 不支持 Unix socket），其余测试照常运行。

## 目录结构

```
exampilot/
├── backend/            # FastAPI 后端
│   ├── app/
│   │   ├── api/        # 11 个路由模块（会话/文档/检索/讲解/练习/错题/复习/记忆/偏好…）
│   │   ├── core/       # 配置、seekdb 引擎封装
│   │   ├── models/     # 表结构（含 FULLTEXT / VECTOR 索引）
│   │   ├── retrieval/  # 混合检索（RRF）、trigram 分词
│   │   ├── services/   # 解析、分类、索引、判分、掌握度、复习、题库
│   │   └── memory/     # PowerContext 客户端封装
│   └── tests/          # 145 项测试（单元 + 真实 seekdb 集成 + 安全/分类回归）
├── frontend/           # React 18 + TS + Vite + Tailwind v4（八大页面）
├── samples/            # 样例讲义（md + 生成的中文 pdf，12 知识点）
├── docs/               # 架构、部署、开发记录
├── evidence/           # 全部实测证据（seekdb / PowerContext / 浏览器 / UAT2 回归）
└── scripts/            # 辅助脚本
```

## 文档

- [架构与数据模型](docs/architecture.md)
- [部署说明](docs/deployment.md)（本地 + Qoder Sites 方案）
- [开发记录](docs/development-log.md)（Qoder 真实开发过程）
- 证据目录 `evidence/`：seekdb 端到端、pytest、PowerContext 记忆读写、前端浏览器实测。
- 待补项：比赛交付所需的 Qoder UID 尚未提供（见开发记录 5.6），补齐后可关联 Qoder 开发记录。

## 技术栈

- 后端：Python 3.12 / FastAPI / pymysql（seekdb Unix socket）
- 数据库：OceanBase **seekdb**（FULLTEXT trigram 中文检索 + VECTOR l2_distance + HNSW）
- 向量：fastembed + BAAI/bge-small-zh-v1.5（512 维，本地推理）
- 长期记忆：**PowerContext** 1.2.0（服务端 seekdb 存储，跨会话 scope）
- 前端：React 18 / TypeScript / Vite 6 / Tailwind CSS v4 / react-router（HashRouter）
