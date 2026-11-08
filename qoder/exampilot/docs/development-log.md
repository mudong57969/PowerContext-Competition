# ExamPilot 开发记录（Qoder Development Log）

> 本文件记录 ExamPilot 项目由 Qoder 执行的每个开发阶段：任务、代码变更、测试与真实结果。
> 禁止虚构记录；所有命令与输出均可复现。

## 2026-11-06 阶段 1：环境与架构核查

### 1.1 工作区与 Git 基线

- 任务：核查工作区、建立独立开发分支。
- 执行内容（Qoder）：
  - 确认工作目录 `D:\oceanbase_comp\qoder-project`（新独立工作区，未触碰 `D:\oceanbase_comp\powercontext` 旧赛题工作区）。
  - `git status`：HEAD = `d647275c`（官方基线 `upstream/2026-competition-ecosystem`，提交 "chore: initialize 2026 competition ecosystem directories"）。
  - `git ls-remote --heads origin`：团队远程 `mudong57969/PowerContext-Competition` **不存在** ecosystem 分支 → 按总指令从官方基线建立独立开发分支。
- 关键变更：
  - `git checkout -b feature/qoder-exampilot upstream/2026-competition-ecosystem`
  - 新分支 `feature/qoder-exampilot` 基于官方基线 `d647275c`，跟踪 `upstream/2026-competition-ecosystem`。
- 结果：通过。分支建立成功，工作树干净。

### 1.2 环境能力核查

- 本机：Windows 10 (win32)，无 Docker。
- WSL2：Ubuntu-24.04（停止状态 → 已启动），内核 6.18.54.1-microsoft-standard-WSL2，x86_64，24 核 / 15GB。
- WSL 内 Python 3.12.3（符合比赛要求 Python 3.12 / Linux x86_64）。
- WSL 内网络连通 PyPI（HTTP 200）。
- 决策：seekdb 嵌入式引擎（pylibseekdb）仅支持 Linux/macOS，因此 **后端在 WSL2 中运行**，代码位于 Windows 仓库目录（`qoder/exampilot/backend`），通过 `/mnt/d` 挂载执行；seekdb 数据目录置于 WSL 原生文件系统。

### 1.3 seekdb 最小连接验证（真实证据）

- 安装：WSL venv `~/.venvs/exampilot`，`pip install "powercontext[client,server,seekdb]==1.2.0"`（含 pylibseekdb 1.4.0.post1）。
- 测试脚本：`backend/tests/`（复现命令见 README）。
- 结果：
  - `pylibseekdb.open(path)` 启动嵌入式引擎成功，`connection_options()` 返回 `{'user': 'root', 'unix_socket': '/tmp/pylibseekdb-*/run/all.sock'}`。
  - 通过 pymysql 建表、插入 2 行、SELECT 返回 2 行、`MATCH ... AGAINST` 全文检索返回 1 行（"CMOS inverter dynamic power" 命中 CMOS 行）。
  - **MIN_SEEKDB_TEST=PASS**
- 遇到的问题与修复：
  - `seekdb_open failed: code=-1`：根因是调用方未创建数据目录父目录（PowerContext 的 `SeekDBProfile.open` 会显式 `mkdir`，pylibseekdb 本身不会）。修复：打开前创建父目录。
- 证据：`evidence/seekdb/`（待补充运行截图）。

### 1.4 PowerContext 最小记忆验证（真实证据）

- 安装：同上 venv，另补 `powercontext[cli]==1.2.0`（CLI 入口）。
- 配置：`POWERCONTEXT_SERVER_DATABASE_KIND=seekdb`、`POWERCONTEXT_SERVER_DATABASE_PATH=~/exampilot-data/powercontext/seekdb`、端口 8000、`ACCESS_MODE=disabled`（仅本机演示）。
- 服务器启动：`powercontext server run`，`GET /health/ready` → `status: ready, database: ready`。
- 客户端测试（`powercontext.client.PowerContextClient`）：
  - `create_scope(title, summary, idempotency_key)` → 返回 scope_id。
  - `remember_memory(scope_id, kind="weakness", text=...)` → 写入成功。
  - `search_memory(scope_id, query="short-circuit power mistakes")` → 返回 1 条命中，正文完整召回。
  - **MIN_PC_TEST=PASS**
- 遇到的问题与修复：
  1. `CreateScopeRequest` 必填字段为 `title`、`summary`、`idempotency_key`（通过读取安装包 `powercontext/http/generated/models.py` 确认）。
  2. `remember_memory` 返回 HTTP 500（`TypeError: 'str' object is not callable`，位于内置 aiosqlalchemy + aiomysql 层）：根因是驱动版本过新。按比赛锁定版本回退：`aiomysql==0.3.2`、`pyobvector==0.2.28`、`sqlalchemy==2.0.54`、`pymysql==1.2.0` 后修复。
  3. `SearchMemoryResponse` 的命中字段为 `hits`（`SearchMemoryHit` 列表），非 `entries`。
- 证据：`evidence/powercontext/`（待补充截图）。

### 1.5 Qoder Sites 部署能力确认

- 通过 Qoder Sites 官方 skill（sites-building）与 MCP `get_context` 确认：
  - 环境：Qoder Desktop（qoder-cn / cn / prod），Sites OpenAPI `https://openapi.qoder.com.cn`。
  - Sites 可托管静态前端 + Edge Functions（JS/TS）+ 托管数据库/存储/密钥。
  - **Sites 不能直接运行 Python FastAPI 或嵌入式 seekdb 引擎**。
- 部署方案（采用前后端分离）：
  - 前端（Vite 构建产物）发布到 Qoder Sites，公开访问。
  - 后端 FastAPI + seekdb + PowerContext 运行于 Linux 环境（本地验证用 WSL2；公开演示后端需另行部署，见"待授权事项"）。
- 结论：已验证限制；公开后端部署方案待用户授权后确定。

### 阶段 1 待授权/待办事项

- 公开可访问的 HTTPS 后端服务器（云主机或等价资源）需用户提供或授权创建。
- Qoder 账号 UID：需通过用户或 Qoder 应用界面取得（本机设置文件含凭据，Qoder 未读取）。
- GitHub 提交/推送：按总指令未经授权不执行。

### 阶段 1 结论

- seekdb 最小连接读写：**通过（真实执行）**
- PowerContext 最小记忆读写：**通过（真实执行）**
- Git 基线：官方 `2026-competition-ecosystem` @ `d647275c`，独立分支 `feature/qoder-exampilot`
- 下一步：阶段 2（数据模型、上传解析、自动分类、混合检索）

## 2026-11-06 阶段 2：后端骨架、数据模型、上传分类与混合检索（真实运行）

### 2.1 后端工程骨架

- `backend/`：FastAPI + pydantic-settings + pymysql/aiomysql 直连 seekdb（嵌入式引擎，Unix socket）。
- 模块：`app/core`（config、seekdb 连接、日志）、`app/models/schema.py`（DDL）、`app/services`（parsing/indexing/classification/documents/question_bank/practice/scoring/mastery/review/llm）、`app/retrieval`（embeddings/hybrid/vector_format/fts_text）、`app/memory/powercontext.py`（PowerContext 封装）、`app/api`（health/sessions/documents/knowledge/search/ai/practice/mistakes/review/memories/preferences）。
- 数据模型共 15 张表：demo_sessions、courses、chapters、knowledge_points、documents、document_chunks（TEXT + VECTOR(512) + FULLTEXT）、document_knowledge_links、questions、question_knowledge_links、practice_sessions、attempts、knowledge_mastery、review_tasks、classification_feedback、memory_events（记忆写入审计）、user_preferences。

### 2.2 上传解析与自动分类（真实证据）

- 样例材料 `cmos_notes.md`（数字集成电路 4 章讲义，Markdown）上传 → 解析 13 个分块、全部写入 seekdb。
- 分类：课程置信度公式 `0.55*课程 + 0.30*章节 + 0.15*检索信号`，阈值 high=0.65 / mid=0.45（配置项）。
- 实测结果：`doc: cmos_notes.md auto 0.683 数字集成电路 MOS 器件`，自动归档并识别 7 个知识点（MOS 阈值电压、MOS 工作区、CMOS VTC、传播延迟、短路功耗、泄漏功耗、互连延迟）。

### 2.3 seekdb 混合检索：全文 + 向量 RRF（真实证据）

- 实现 `app/retrieval/hybrid.py`：`MATCH ... AGAINST` 全文分支 + `l2_distance` 向量分支，各取 max(limit*4, 32) 候选，RRF（K=60）融合，命中携带 `matched_by` 来源标记。
- **关键问题与修复（FTS 中文分词）**：实测发现 seekdb FULLTEXT 按空白/标点切词，**连续中文串为单个 token，且长度 < 3 的 token 被丢弃**（探针证据：`evidence/seekdb/fts_tokenizer_probe_20261106.txt`——2 字 token 查询全部落空，3 字 trigram 可命中）。
- 修复：新增 `fts_text` 列与共享函数 `fts_tokenize()`（`app/retrieval/fts_text.py`）：索引与查询时均将中文串展开为「全串 + 重叠 trigram」，英文词原样保留。全文索引迁移至 `fts_text`。
- 修复后端到端实测：`SEARCH 200 hybrid fts: 1 vec: 13 hits: 5`，查询「动态功耗公式」顶部命中 `cmos_notes.md ['fts', 'vector']`（修复前 fts: 0）。
- 降级策略：嵌入不可用时明确标记 fts-only；错误信息如实返回 warning 字段。

### 2.4 练习、判分、错题本与掌握度（真实证据）

- 题库：24 道自编题（单选 10 / 多选 4 / 判断 5 / 简答 5，覆盖 12 个知识点），`is_generated=0` 区分 AI 生成题。
- 判分 `app/services/scoring.py`：单选全对/多选子集 0.5 分/判断多写法归一/简答 token 覆盖率 ≥ 0.6；判分证据写入 attempts。
- 掌握度 `app/services/mastery.py`：`0.75*正确率 + 0.25*min(连对,5)/5`，ON DUPLICATE KEY 幂等更新。
- 实测：练习 5 题 → 得分 40.0（2/5），错题本 3 条，掌握度快照如 `('MOS 工作区', 0.0), ('泄漏功耗', 0.0), ('CMOS VTC 与噪声容限', 0.8)`。
- 复习计划 `app/services/review.py`：间隔 [1,3,7,14,30] 天，阈值 0.6；实测 upcoming 4 条。

### 2.5 PowerContext 长期记忆集成（真实证据）

- `app/memory/powercontext.py`：同步门面（每次调用新建客户端并关闭，线程池安全）；`ensure_scope` 幂等键 `exampilot:{session_id}`。
- 记忆事件：练习提交后写入「薄弱知识点」与「练习结果」两条长期记忆；`memory_events` 表审计每次写入（scope_id、状态、记忆引用）。
- 实测：`MEM_EVENTS 200 count: 2 [('weak_knowledge_points','ok'), ('practice_result','ok')]`；跨请求 `MEM_SEARCH` 以 fts 模式召回薄弱知识点原文（entry_id 引用完整）。
- AI 讲解 `app/services/llm.py`：未配置 LLM 时使用「资料片段 + 模板」并明确标注，实测返回 5 个来源引用（`provider: template sources: 5`）。

### 2.6 修复记录（本轮）

1. `generated` 是 OceanBase 保留字 → 建表 1064 语法错误 → questions 表列改名为 `is_generated`。
2. 样例文档分类置信度 0.545 < 0.55 → 课程词典扩充 + 阈值下调至 0.65/0.45 → auto 0.683。
3. HuggingFace 被墙 → `HF_ENDPOINT=https://hf-mirror.com` 下载 BAAI/bge-small-zh-v1.5（512 维）成功。
4. seekdb FTS 中文不命中 → trigram 展开方案（见 2.3），实测修复。

### 阶段 2 证据

- `evidence/seekdb/smoke_e2e_20261106.txt`（端到端 18 行真实输出：健康检查/会话/上传/分类/检索/练习/记忆/讲解）
- `evidence/seekdb/fts_probe_chunks_20261106.txt`（真实数据上的 FTS 行为探针）
- `evidence/seekdb/fts_tokenizer_probe_20261106.txt`（token 最小长度与 trigram 行为探针）

### 阶段 2 结论

- 后端核心链路（上传 → 分类 → 检索 → 练习 → 判分 → 掌握度 → 复习计划 → 长期记忆 → 讲解）已在 WSL2 真实 seekdb + 真实 PowerContext 上端到端跑通。
- 下一步：pytest 单测/接口测试、样例材料与验收样例、前端八页面、Qoder Sites 发布（待授权）。

## 2026-11-06 阶段 2 补充：pytest 测试套件、样例资料与 PDF 解析

### 2.7 pytest 测试套件（85 项全部通过）

- 新增 `backend/tests/`：单元测试（fts_text 分词、判分、解析、分块、向量字面量、分类、掌握度公式、复习规则）+ seekdb 集成测试（Windows 自动跳过，WSL2 真实引擎执行）。
- 集成测试覆盖：建表、FTS trigram 中文命中、hybrid 检索 fts-only 模式、掌握度更新→复习计划→复习完成（错误答案生成次日跟进）、题库幂等安装。
- 实测：`85 passed in 4.08s`（证据 `evidence/seekdb/pytest_20261106.txt`）。
- 测试暴露并修复的真实缺陷：多选答案 `A、C` 分隔符混入字母集合（判分错误）→ `_extract_letters` 改为正则提取字母；同时支持「答案：B」等前缀写法。

### 2.8 样例资料（≥10 知识点，已达成）

- `samples/cmos_notes.md`：自编《数字集成电路 讲义》，5 章 12 个知识点，与题库 12 个知识点一一对应。
- `samples/cmos_notes.pdf`：由同一讲义用 fpdf2 + Noto Sans SC 生成的中文 PDF（53 KB，2 页），用于验证 PDF 解析链路：pypdf 提取 1241 字符、`ocr_required=False`（证据 `evidence/seekdb/pdf_parse_check_20261106.txt`）。
- 分类词典同步扩充（体效应、沟道长度调制、扇出与扇入、尺寸缩放与功耗密度、工艺与缩放章节）。
- 端到端实测（md + pdf 批量上传）：
  - `cmos_notes.md` → auto 0.82，识别 12/12 知识点；
  - `cmos_notes.pdf` → auto 0.927，识别 11/12 知识点（PDF 提取文本中「p = α」间距变化导致动态功耗未命中，属提取层差异，已如实记录）；
  - 混合检索 `fts: 4 vec: 22`，练习 60.0（3/5），错题 2 条，复习计划 4 条，PowerContext 记忆写入与召回正常。
- 证据：`evidence/seekdb/smoke_e2e_20261106.txt`（当前版本，含双文件批量上传）。

### 阶段 2 结论（更新）

- 后端功能全部真实跑通并有 85 项自动化测试 + 端到端证据。
- 下一步：前端八页面、README/架构文档、Qoder Sites 发布（待授权）。

## 2026-11-06 阶段 3：前端八大页面（React 18 + TS + Vite 6 + Tailwind v4）

### 3.1 技术选型与工程搭建

- `frontend/`：React 18.3 + TypeScript 5.6 + Vite 6 + Tailwind CSS v4（@tailwindcss/vite），react-router-dom 6（HashRouter，静态托管安全）。
- 开发环境 `/api` 由 Vite 代理到 `127.0.0.1:8001`；生产环境用 `VITE_API_BASE_URL` 指向已发布后端。
- `src/api.ts`：全量类型化 API 客户端（健康检查、会话、上传、课程/知识点、检索、讲解、练习、错题、复习、记忆、偏好），错误统一抛 `ApiError`。

### 3.2 八个页面全部实现并通过真实浏览器实测

- 仪表盘：统计卡片 + 平均掌握度 + 今日复习（进入页面时重新拉取会话统计，避免启动快照过期）。
- 资料管理：真实文件上传（PDF/PPTX/MD/TXT）→ 解析 → 自动分类结果表格（置信度、课程/章节/知识点徽章、建议分类确认 / 人工更正）。
- 知识检索：seekdb 混合检索（FTS trigram + 向量 + RRF），命中来源标注 fts/vector 徽章，同步展示 PowerContext 记忆召回。
- AI 讲解：知识点下拉 + 自由提问，讲解正文 Markdown 渲染（自写迷你渲染器），引用来源列表；LLM 未配置时如实显示「template」模式。
- 练习：综合/薄弱点专练，单选/多选/简答三种题型，交卷后逐题解析 + 判分依据 + 掌握度变化 + 复习任务生成提示。
- 错题本：错题列表（错次、历史答案、解析）+ 一键错题重练（复用练习作答/结果流程组件）。
- 复习计划：今日待复习 / 即将到期 / 掌握度排行，可标记「已掌握/没掌握」驱动间隔重复。
- 长期记忆：PowerContext 记忆检索、显式写入、记忆事件流（含真实 entry_id 引用）。

### 3.3 浏览器实测发现并修复的缺陷

1. 健康检查响应结构与我方类型不一致（`memory.enabled/reachable`）→ 修正 Health 类型与侧边栏芯片。
2. 后端题型值为 `single_choice` / `multi_choice` / `short_answer`，前端误用 `choice` / `multiple_choice` → 选择题一度渲染成文本框，修正后正常。
3. 多选题快速勾选丢失选项（stale closure，实测仅记录到 "C" 而非 "ABC"）→ 改为函数式状态更新。
4. 仪表盘统计停留在启动时快照（上传/练习后仍显示 0）→ 页面挂载时重新拉取会话。
5. 记忆检索原始分数误标百分比 → 改为原始 score 展示。
6. （过程性）HMR 中途热更新导致运行态短暂不一致报错，全量刷新后消失，最终版本稳定。

### 3.4 实测结果（证据 `evidence/frontend_browser_test_20261106.txt`）

- 上传 md → 自动分类 82% 置信度、12 知识点；检索「动态功耗」hybrid fts:2 vec:19 双来源命中。
- 两轮练习（60 分 / 80 分），掌握度跨轮累计（传播延迟 0→43%，MOS 工作区 80→85%），复习任务正确排期（1d/3d）。
- 错题自动入库；PowerContext 事件流含真实 entry_id/entry_version_id；记忆检索「最薄弱」召回正确。
- `tsc --noEmit && vite build` 通过（46 modules，213 KB / gzip 66.9 KB）。

### 阶段 3 结论

- 前后端完整链路（上传 → 分类 → 混合检索 → AI 讲解 → 练习判分 → 错题 → 复习 → 长期记忆）全部在真实浏览器中走通。
- 后端启动脚本化：`start_exampilot.sh`（setsid 常驻 WSL，供本地开发与演示；位于开发机用户主目录，不在仓库内）。
- 下一步（阶段 4）：README 与架构/部署文档、Qoder UID 补充、Qoder Sites 发布（需用户授权站点可见范围与费用说明）。

## 2026-11-06 阶段 4：交付文档与发布准备

### 4.1 交付文档

- `README.md`：功能总览、三步快速开始（PowerContext / 后端 / 前端）、7 步验收样例（含跨会话记忆验证）、测试命令、目录结构。
- `docs/architecture.md`：三层架构图（前端 SPA / WSL FastAPI / 双 seekdb 实例）、14 张表数据模型、六项关键算法（FTS trigram、向量 HNSW、RRF 融合、三级分类、判分与掌握度、PowerContext 集成）、工程决策表。
- `docs/deployment.md`：本地三步运行、Qoder Sites 前后端分离方案（前端静态托管 + 后端三选一）、公网安全要求（密钥仅服务端、PowerContext 强制鉴权、不公开真实资料）、发布授权清单。
- 证据：`evidence/frontend_browser_test_20261106.txt`（八大页面浏览器实测 + 缺陷修复记录）、`evidence/seekdb/`（FTS 分词探针、端到端、pytest）、PowerContext 读写证据。

### 4.2 发布准备（暂停于授权边界）

- 按比赛要求「发布或公开暴露服务前，须先说明可见范围、费用与安全影响并取得授权」，Qoder Sites 发布与后端公网部署已形成方案（deployment.md 第 3–5 节），等待用户选择后端方案（云服务器 / 自有主机 / 仅本地演示）并逐项确认后执行。
- 待补充：Qoder UID（比赛交付要求，需用户提供）。
- 说明：截至本阶段，仓库未提交任何 commit / push / PR（用户明确要求未经授权不得提交、推送、合并）。

### 4.3 发布授权结果（真实记录）

- 向用户说明可见范围（公网可见/可限制）、费用（Sites 静态托管按平台计费；云服务器约 ¥50–100/月）与安全影响（密钥仅服务端、PowerContext 强制鉴权、CORS 白名单、不公开真实资料）后，用户选择：
  - 后端方案：**C 仅本地演示**（零成本零风险，验收以本机演示 + evidence/ 为准）。
  - Qoder Sites：**暂不发布**。
- 该决定已同步写入 `docs/deployment.md`。后续如需公网部署，须重新说明影响并取得授权。
- 仍待用户提供：Qoder UID（比赛交付要求）。
- 仓库状态：仍无 commit/push/PR（未经授权不提交）。

## 2026-11-06 阶段 5：真实 UAT 失败修复 — PPTX 自动分类（14% → 68%）

### 5.1 用户验收发现的问题（真实记录）

- 测试文件 `03-chapter2-device02-MOS-dynamic_T.pptx`（50 页、24.7MB）前端显示：parsed、待人工分类、置信度 14%、课程/章节/知识点全空。

### 5.2 只读定位结论（证据：`scripts/diagnose_document.py`、`evidence/seekdb/` 探针输出）

- 文件仍在库中（doc 1000002 / session 9e7fc0f065134af5），实际提取文字 10,230 字符、49 个非空幻灯片、50 个知识块（chunks），向量索引 50/50 已建立（VECTOR(512) + HNSW）。
- parsed 仅代表文件读取成功，不代表分类完成。
- 14% = 0.55×0.25 + 0（章节）+ 0（检索）：旧词典 12 个课程关键词全是中文术语（阈值电压/功耗…），英文课件只命中 3 个（cmos/vlsi/mos）。
- 与「未预先创建课程」无关（分类器本就会在 auto 时创建课程）。

### 5.3 修复（最小必要，通用化，无文件名特判）

- `backend/app/services/classification.py`：
  - 词典扩充：数字集成电路 22 词（补充 transistor/threshold voltage/propagation delay 等英文术语）；「MOS 器件」章节补 velocity saturation/short-channel/body effect 等；新增「速度饱和」「短沟道效应」知识点；「MOS 工作区」关键词改为截止区/线性区/饱和区/cutoff region/saturation region/triode/pinch off（消除 velocity saturation 中 saturation 子串误命中）。
  - 加权信号：0.55×关键词覆盖率 + 0.45×出现密度；标题命中 +0.8；标题/章节标题自动提取（跳过页码与 outline/目录 等噪声）；`=` 归一化使「p = α」匹配「p=α」；ASCII 词边界匹配、CJK 子串匹配。
  - 文件名仅作弱先验（+0.06），不决定分类；结构化标题可提出「新课程」候选（reason=new_course）。
  - 输出课程/章节候选列表 + 失败原因：insufficient_text / no_signal / new_course / ambiguous / ok；零分候选过滤。
- `backend/app/services/parsing.py`：PPTX 补全组合形状与表格提取、`\x0b` 换行处理、标题提取、MIN_TEXT_CHARS=50。
- 多知识点：每页按知识点关键词打分（强 ≥0.4，或 ≥0.25 且 ≥2 页），保存幻灯片编号证据到 `document_knowledge_links.slide_numbers`。
- 重新分类：新增 `POST /api/documents/{id}/reclassify`，从 chunks 重建解析结果重新分类；原始分类证据快照进 `classification_feedback.original_json`，保留原始上传记录（created_at 不变）。
- 前端：`Documents.tsx` 显示提取字数、分类原因徽章、候选课程/章节、知识点「(N页)」来源提示、重新分类按钮。

### 5.4 回归测试（`backend/tests/test_classification.py`，共 95 项全通过）

- 8 类场景：① 真实 MOS 课件提取文本（fixture 由 `scripts/export_doc_fixture.py` 从 seekdb 导出，10,230 字）→ 自动分类；② 从未出现过的新课程；③ 英文资料；④ 中英混合；⑤ 文件名与正文冲突（正文胜出）；⑥ 无法解析正文的 PPTX + 可解析但无信号；⑦ 多章节多知识点（含幻灯片证据）；⑧ 低置信度（pending + 候选而非空白）；另补歧义分支。
- 测试只断言材料内容支持的分类，无文件名特判。

### 5.5 重新分类实测（真实数据）

- 修复前：pending / 置信度 0.138 / 课程 数字集成电路@0.25 / 章节空 / 1 知识点。
- 修复后：auto / 0.682 / 数字集成电路 / MOS 器件 / 7 知识点（MOS 阈值电压、体效应、沟道长度调制、速度饱和、短沟道效应、泄漏功耗、尺寸缩放与功耗密度），全部带幻灯片编号证据。
- 前端实测：自动分类 68%、课程/章节/知识点全部显示（evidence 浏览器截图）。
- 其他 3 份文档未改动；`classification_feedback` 保留修复前证据；后端已重启加载新代码（uvicorn PID 69002）。

### 5.6 状态

- 无 commit/push/PR/Qoder Sites 发布（用户约束）；Qoder UID 仍待用户提供。

## 2026-11-06 阶段 6：第二轮真实用户验收（UAT2）— 异领域分类、证据、新课程、隔离核查

本轮只验收、不改代码（用户要求：先输出复现证据与最小修复方案，未经审查不公网发布；停止新功能开发）。证据目录 `evidence/uat2/`。

### 6.1 验收 8 项结果

| # | 项目 | 结果 |
|---|------|------|
| 1 | 异领域资料自动分类（概率论） | 部分通过：课程/章节正确（auto 0.82），知识点为空 |
| 2 | 知识点页码与正文证据 | 通过：7 KP 全部 66 处引用逐页核对，OVERALL PASS |
| 3 | 未见过的新课程识别/创建 | 失败（自动路径）；人工确认/更正创建课程通过 |
| 4 | 候选分类、原因说明、人工修正 | 部分通过：API 层通过；发现 2 个真实 UI 缺陷 |
| 5 | 重分类后检索索引与来源引用 | 通过 |
| 6 | 匿名 session / PowerContext scope 跨用户隔离 | 失败：确认 5 类越权漏洞（含跨用户写入） |
| 7 | 漏洞先出复现证据+最小修复方案 | 完成（本报告 6.5；修复待审查后实施） |
| 8 | 保留全部现有数据 | 通过（仅对 UAT2 自建测试资料做确认/更正，其余未动） |

### 6.2 明细

- 第 1 项：`probability_notes_uat2.md`（12 页概率论资料，Qoder 自撰测试材料）→ auto / 0.82 / 概率论 / 随机事件与概率。知识点为空：KP 词典只有数字集成电路领域，跨领域 KP 提取是真实限制。
- 第 2 项：`scripts/verify_kp_evidence.py` 逐页核对 MOS 课件 7 个知识点引用的 66 个幻灯片编号，每个引用页正文均含对应知识点关键词 → OVERALL PASS（证据 `uat2_kp_evidence.txt`）。
- 第 3 项：`data_structures_notes_uat2.md` 被检索信号（0.2 弱相似）强制归入「概率论」，未识别为新课程。根因：`classification.py` 中 `_retrieval_signal` 赋值先于标题结构的新课程分支。人工路径正常：确认后创建「数据结构与算法」课程，更正后创建「概率论与数理统计」课程与「随机变量」知识点（证据 `uat2_confirm.txt`）。
- 第 4 项缺陷：
  - 缺陷 A（候选不持久化）：`classify_evidence` 不存 `course_candidates`，列表接口 `_parse_evidence` 回退合成 `{source:"result", score:course_confidence}` → 页面显示「概率论（95% · result）」而非上传响应中的「概率论（89% · 词典）」；pending 文档（course 为空）刷新后候选全部丢失。DB 证据 `uat2_evidence_check.txt`。
  - 缺陷 B（确认按钮无效）：`Documents.tsx` `confirmDoc` 要求 `doc.course` 非空，但 suggested 文档未落库课程（course_id NULL）→ 点击「确认」静默无操作（浏览器实测复现）。
  - `window.prompt` 更正对话框在自动化浏览器中被抑制，端到端 UI 更正流程标记为未验证（API 更正已验证）。
- 第 5 项：重分类后 hybrid 检索命中均引用 doc 1000002 真实页码且正文含检索词；课程过滤无越界命中；讲解来源引用重分类后的文档（证据 `uat2_retrieval.txt`）。
- 第 6 项（隔离漏洞，证据 `uat2_isolation.txt`）：
  1. `GET /api/sessions` 无鉴权枚举全部 5 个会话（含 scope_id）；
  2. 任意会话 id 可读他人资料列表与本地记忆事件（SB 读到 SA 记忆文本「会话A的私有学习记忆内容-圆周率π≈3.14159」）；
  3. 跨会话 PowerContext 记忆搜索命中他人私有记忆；
  4. explain 接口 IDOR：用他人知识点 id 2000001 返回「MOS 阈值电压」讲解并写入他人记忆 scope；
  5. 跨会话记忆写入成功（SA scope revision 2）。
  - 正向确认：PowerContext 按 scope 隔离本身有效（新匿名会话 SB 自己的数据为空）；漏洞在应用层：无鉴权 + 会话枚举 + 任意会话 id 直通。

### 6.3 最小修复方案（待用户审查，本轮未实施）

1. `GET /api/sessions`：删除公开枚举；前端只持有自己的 session id（localStorage），后端不再提供全量列表。
2. 所有 `/api/sessions/{id}/*`：创建会话时签发随机 capability token（仅返回一次，前端存 localStorage），每次请求校验 token 与会话匹配；scope_id 永不下发客户端。
3. explain/练习等按知识点 id 的接口：先校验知识点所属课程的 `session_id` 属于当前会话，否则 404/403。
4. 持久化 `course_candidates/chapter_candidates` 到 `classify_evidence`；`confirmDoc` 在 `doc.course` 为空时回退使用证据中的 course 或首个候选。

### 6.4 状态

- 本轮零代码修改（仅新增只读探针脚本与证据文件）；无 commit/push/PR/Sites 发布；PowerContext 旧工作区未动；MOS 课件与全部既有课程/文档/记忆完好。

## 2026-11-07~08 阶段 7：UAT2 修复实施 — 身份权限系统、分类修复、全量回归与浏览器验收

用户已审查 UAT2 报告并批准实施。开工前完成数据保护：DB 备份与 5 个旧会话状态快照（提交前审查时已迁至仓库外 `D:\oceanbase_comp\backups\exampilot\backup_20261107\`，校验和一致；仓库内不再保留备份）、PowerContext 记忆未动；测试身份与旧会话数据分离。

### 7.1 身份与权限系统（后端统一认证）

- 新增 `identities` 表：session_id 主键、token_digest（sha256，不存明文）、created_at/last_used_at。
- `POST /api/sessions` 服务端创建匿名身份：签发 256-bit `secrets.token_urlsafe(32)`（43 字符），**仅创建时返回一次**，后端只存摘要。
- 所有数据接口要求 `Authorization: Bearer`：`require_session()` 校验摘要匹配、身份存在；缺失/无效/过期/不匹配一律 401（带 `WWW-Authenticate: Bearer`）；身份有效但资源不属于该身份 → 403。
- session_id 不再是凭据：URL 路径中的 session_id 仅作资源定位，权限完全由 token 决定；scope_id 永不下发客户端，PowerContext scope 服务端按身份映射。
- 全局权限评审覆盖全部资源（courses/documents/chunks/chapters/KPs/questions/practice_sessions/attempts/mistakes/mastery/review_tasks/classification_feedback/记忆/explain/search/upload/reclassify）× 全部动词；不限于 UAT2 发现的 5 个入口。
- 修复的 5 个确认漏洞：① GET /api/sessions 公开枚举 → 删除公开枚举，仅保留 /me；② 任意会话 id 读他人文档/记忆 → 401/403；③ 跨会话 PowerContext 记忆搜索命中他人私有记忆 → scope 服务端绑定身份；④ explain IDOR（他人知识点 id）→ 归属校验 404/403；⑤ 跨会话记忆写入 → 写入接口鉴权 + scope 校验。
- 旧会话受控迁移：`scripts/migrate_legacy_session.py` 本地管理步骤为旧 session 补建 identity（生成 token 一次打印、只存摘要）；不自动把旧 session_id 当凭据；无面向未认证浏览器的 claim 端点；迁移前后快照对比无数据损失。
- 前端：api.ts 全量请求自动附带 Bearer；App.tsx 启动时 /me 校验，401 → 清本地身份 → 重新创建；「重置匿名身份」入口（确认后清 localStorage，服务端数据保留，凭原 token 可恢复）；Token 永不进 URL、不进日志。

### 7.2 自动分类修复（v3.1）

- 新课程优先级：标题结构证据（如 `# 数据结构与算法`）优先于弱检索相似度（lex_score<0.25 时既有课程不再无条件覆盖）；新课程自动创建或建议确认；文件名-正文冲突给明确 reason。
- 候选持久化：`classify_evidence` 存 course/chapter 候选（name/score/source）、分类依据、状态、分类器版本；刷新后候选一致；列表接口只读证据、不再合成分数。
- 确认按钮：doc.course 为空（新课程未落库）时回退使用证据课程/首个候选；确认后正确创建/链接课程、更新状态与文档-KP 链接、检索过滤字段。
- 应用内更正对话框（CorrectDialog）替代 window.prompt（浏览器自动化会抑制 prompt）。
- 跨课程知识点通用提取：术语式小节标题（2–24 字符、无停用标点）+ 正文证据 ≥2 页且标题页独立成节；保留真实文本与页码证据；证据弱时人工确认；从不伪造知识点。
- 回归：分类单测 26/26；分类回归（真实 API）17/17，含 MOS PPTX、概率论 MD、数据结构新课程、英文、混合、跨课程 KP、文件名冲突、低置信 pending、候选持久化、suggested 确认、人工更正、重分类后检索+引用、旧演示数据完好。

### 7.3 安全回归测试

- 独立身份 A/B 16 场景（枚举、跨读文档/记忆/scope、explain IDOR、跨写记忆、无 token、错误 token、他人 practice/review/mistakes 等）：全部按预期拒绝（401/403）。
- 每项同时断言：拒绝响应 + 无 DB 状态变化 + 无 PowerContext 跨写 + 合法操作仍正常（不只看 HTTP 403）。
- `test_auth.py` 28/28 通过；全后端套件 145/145（2026-11-08 复跑确认，13.80s）。

### 7.4 真实浏览器端到端验收（A-J）

证据：`evidence/uat2/browser_e2e_20261108.txt`（browser-use MCP 驱动真实 Chromium）。

- A 自动创建身份 / B 上传-解析-分类-候选 / B2 新课程场景确认按钮（DB 核对 course 5000007 创建+feedback user_confirmed=1） / B3 应用内更正对话框（DB 核对章节改写+feedback user_confirmed=0）。
- C 检索“链表”“二叉树的遍历”命中带页码；D 练习 3 题判分 67%、掌握度/复习任务落库（题目按 SQL 夹具方式为新身份播种，证据中已如实说明）；E 错题本/复习计划；F PowerContext 记忆真实写入与召回；G 刷新恢复身份与数据；H 新身份全空 + 旧身份数据完好 + 无 token 401；I 控制台无 Token、请求 URL 无 Token（仅 Bearer 头）；J 重置匿名身份后本地凭据清除、服务端数据保留。
- 工具性限制（已在证据中披露）：browser-use click 工具在本页面不触发 React 事件，交互改用 evaluate_script 执行真实 DOM `element.click()`（真实点击→真实请求→DB 落库核对）；题库播种为 SQL 夹具。

### 7.5 质量门

- 后端 pytest：145/145（13.80s）；ruff check + format --check：All checks passed / 70 files already formatted；前端 tsc --noEmit + vite build：46 modules / 218.41 kB，全部通过。
- 结论：本轮只证明“修复项在本环境验证通过”，不声称生产级安全性；遗留边界（token 明文存 localStorage 属匿名学习应用的既定取舍、浏览器自动化工具限制）已在证据中如实披露。

### 7.6 状态

- 无 commit/push/PR/Qoder Sites 发布（用户约束）；PowerContext 旧工作区未动；DB 备份已迁至仓库外 `D:\oceanbase_comp\backups\exampilot\backup_20261107\`（校验和一致）；测试身份 token 全部脱敏，未写入仓库文件。

## 2026-11-08 阶段 8：GitHub 提交前安全、数据保护与比赛交付审查

### 8.1 敏感资料审查

- 全仓库扫描（token、scope id、PowerContext entry/version id、个人路径、备份 SQL）：发现并处理的真实敏感项——`evidence/uat2/uat2_isolation.txt` 含 scope_id 值、`evidence/seekdb/smoke_e2e_20261106.txt` 含 mem_ent_/mem_ver_ 值、若干文件含测试身份 token 与开发机个人路径（WSL 用户主目录绝对路径）；全部已脱敏（`<redacted>` / `<venv>`）或泛化（`~/exampilot-data/...`、`start_exampilot.sh`），复扫零命中。
- 数据库备份（`evidence/backup_*`，含 scope id 与私有测试记忆文本）已迁至仓库外 `D:\oceanbase_comp\backups\exampilot\backup_20261107\`，迁移前校验 sha256 一致，迁移后仓库内无 `*.sql`/`*.db` 残留；公开证据仅保留脱敏测试结果与可合法公开的样例。

### 8.2 Git 忽略规则与历史

- `.gitignore` 加固：`*.sql`、`*.db`、`*.sqlite*`、`.seekdb-data/`、`evidence/backup_*`、`*.token`、`local_identity*.json`、`tmp/`、`scratch/`、`*.tmp`、`*.bak`。
- 暂存区为空；历史仅 1 个初始化 commit（`d647275c chore: initialize 2026 competition ecosystem directories`），从未提交过任何敏感内容；工作树唯一未跟踪项为 `qoder/exampilot/`（126 个文件，未使用 `git add .`）。

### 8.3 身份与权限 10 项复核

- 全部通过：真实用户 token 不公开（测试 token 已脱敏）；token 仅存 sha256 摘要；token 不进 URL/日志（仅 Bearer 头）；所有资源端点服务端归属校验（文档/记忆/题目/scope 均 JOIN session 校验，403）；PowerContext scope 仅按合法身份查询；无任何公开 claim 后门（不存在该端点）；重置不暴露他人数据（scope 键含 session_id）；清本地存储后前端明确提示匿名身份可能不可恢复；认证失败统一 401，无回退旧接口；前端公共 JS 不含任何服务端密钥/敏感配置。

### 8.4 比赛交付核对

- 分支祖先正确（基于官方 `2026-competition-ecosystem` 目录初始化 commit）；全部代码在 `qoder/exampilot/`；README 可独立复现（真实 seekdb socket + 145 项测试 + 路径已泛化）；seekdb 与 PowerContext 均为真实接入（有 DB/记忆落库证据）；分类与跨会话记忆可演示（UAT2 A-J 证据）；Qoder 开发记录在 `docs/development-log.md` 可核验；Sites 发布步骤清晰（方案 C 已确认，2026-11-06）；样例资料均可合法公开；待补项：比赛交付所需 Qoder UID 尚未提供（见开发记录 5.6）。

### 8.5 质量门（本轮复跑，2026-11-08）

- 后端 pytest：145/145（12.68s）；ruff check（app/tests/scripts）：All checks passed；ruff format --check：70 files already formatted；前端 `tsc --noEmit && vite build`：46 modules / 218.42 kB；健康检查 `/api/health` 200；旧演示数据 5 身份计数 MATCH（迁移前后一致）；备份 sha256 与迁移时一致。

### 8.6 状态

- 未 commit/push/PR/Qoder Sites 发布（用户约束）。结论：已达到创建研发稳定 Commit 的条件（无敏感内容、质量门全绿、交付项齐备）；是否执行提交由用户决定。
