# ExamPilot 架构与数据模型

> 本文描述 ExamPilot 的系统架构、数据模型与关键算法设计。所有能力均基于**真实可运行**的实现，并有 `evidence/` 目录下的实测记录佐证。

## 1. 系统架构

```
┌────────────────────────────────────────────────────────────────┐
│  浏览器（Windows 宿主）                                          │
│  React 18 + Vite + Tailwind v4 + react-router (HashRouter)      │
│  八大页面：仪表盘 / 资料管理 / 知识检索 / AI 讲解 / 练习 /        │
│           错题本 / 复习计划 / 长期记忆                            │
└──────────────────────────────┬─────────────────────────────────┘
                               │ HTTP /api（开发期 Vite 代理 5173→8001）
┌──────────────────────────────▼─────────────────────────────────┐
│  WSL2 (Ubuntu 24.04)                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ FastAPI 后端（uvicorn :8001）                              │  │
│  │  api/     11 个路由模块（REST）                            │  │
│  │  services/ 解析·分类·索引·判分·掌握度·复习·题库            │  │
│  │  retrieval/ 混合检索（RRF）+ trigram 分词                  │  │
│  │  memory/   PowerContext 客户端封装（sync facade）           │  │
│  └──────────────┬───────────────────────────┬───────────────┘  │
│                 │ pymysql (unix socket)      │ HTTP :8000       │
│  ┌──────────────▼───────────────┐  ┌────────▼────────────────┐ │
│  │ OceanBase seekdb 嵌入式引擎    │  │ PowerContext 服务        │ │
│  │ 数据目录 ~/exampilot-data/     │  │ 后端存储：seekdb          │ │
│  │  seekdb-exampilot             │  │ 目录 ~/exampilot-data/    │ │
│  │ · 业务表 + FULLTEXT 索引       │  │  powercontext/seekdb     │ │
│  │ · VECTOR(512) + HNSW 索引      │  │ · scope 隔离跨会话记忆    │ │
│  │ · l2_distance 向量检索         │  │ · entry/entry_version     │ │
│  └──────────────────────────────┘  └─────────────────────────┘ │
│  向量：fastembed + BAAI/bge-small-zh-v1.5（本地推理，512 维）      │
└─────────────────────────────────────────────────────────────────┘
```

三层结构说明：

1. **前端**（`frontend/`）：纯静态 SPA。使用 HashRouter，任意静态托管（含 Qoder Sites）均可直接部署；通过 `VITE_API_BASE_URL` 指定后端地址。
2. **后端**（`backend/`）：FastAPI。业务数据全部写入 seekdb 嵌入式引擎（Unix socket + pymysql）；向量由本地模型生成；长期记忆通过 PowerContext HTTP API 读写。
3. **数据层**：双 seekdb 实例——ExamPilot 自有业务库（表结构见下）与 PowerContext 服务端存储库。二者互不混用：业务表与记忆库在引擎与目录上完全分离。

## 2. 数据模型（seekdb 表结构）

DDL 定义于 `backend/app/models/schema.py`（`CREATE TABLE IF NOT EXISTS`，启动时自动建表）。共 14 张表：

### 2.1 会话与结构

| 表 | 用途 | 关键字段 |
| --- | --- | --- |
| `demo_sessions` | 学习会话（= 一个学生的空间） | `id`, `name`, `scope_id`（PowerContext scope 引用） |
| `courses` | 课程（一级分类） | `session_id`, `name`, `confidence`, `status`(auto/suggested/pending) |
| `chapters` | 章节（二级分类） | `course_id`, `name`, `order_index` |
| `knowledge_points` | 知识点（三级分类） | `course_id`, `chapter_id`, `name`, `description` |

### 2.2 资料与检索

| 表 | 用途 | 关键字段 |
| --- | --- | --- |
| `documents` | 上传资料元信息 | `session_id`, `course_id`, `chapter_id`, `filename`, `file_hash`（去重：`uq_docs_session_hash`）, `parse_status`, `classify_status`, `classify_confidence`, `classify_evidence` |
| `document_chunks` | 分块与索引 | `original_text`, `normalized_text`, `fts_text`（trigram 展开）, `embedding VECTOR(512)`, `FULLTEXT KEY ft_chunks_text`, HNSW 向量索引 |
| `document_knowledge_links` | 资料 ↔ 知识点关联 | `(document_id, knowledge_point_id)` 联合主键 |

### 2.3 练习与掌握

| 表 | 用途 | 关键字段 |
| --- | --- | --- |
| `questions` | 题库 | `question_type`(single_choice/multi_choice/short_answer), `stem`, `options`, `answer`, `explanation`, `difficulty`, `is_generated` |
| `question_knowledge_links` | 题目 ↔ 知识点 | 联合主键 |
| `practice_sessions` | 一次练习 | `mode`(mixed/weak/mistakes), `total_questions`, `correct_count`, `score` |
| `attempts` | 逐题作答 | `user_answer`, `is_correct`, `score`, `grading_evidence`（判分依据可追溯） |
| `knowledge_mastery` | 知识点掌握度 | `(session_id, knowledge_point_id)` 主键, `practice_count`, `correct_count`, `streak`, `mastery_score` |

### 2.4 复习、审计与记忆

| 表 | 用途 | 关键字段 |
| --- | --- | --- |
| `review_tasks` | 间隔重复复习任务 | `due_date`, `reason`, `status`, `completed_at` |
| `classification_feedback` | 分类更正审计 | `original_json`, `corrected_json`, `user_confirmed` |
| `memory_events` | PowerContext 写入审计 | `scope_id`, `kind`, `summary`, `memory_reference`（真实 entry 引用）, `status` |
| `user_preferences` | 用户偏好 | `exam_date`, `goal`, `preferred_language` |

> 说明：嵌入式引擎对逻辑外键兼容性有限，故表间关系一律使用索引（`KEY idx_*`）约束，由服务层保证一致性。

## 3. 关键算法设计

### 3.1 中文全文检索：FTS trigram 方案

seekdb FULLTEXT 索引的默认分词器对中文不友好（实测：连续 CJK 串被视为**一个整体 token**，长度 < 3 的 token 被丢弃）。若直接索引原文，中文查询几乎无法命中。

方案（`backend/app/retrieval/`）：

1. **索引期**：`fts_tokenize(text)` 将归一化文本中每个连续 CJK 片段展开为「完整片段 + 全部重叠三元组」，ASCII 词原样保留，写入 `fts_text` 列并建立 FULLTEXT 索引。
2. **查询期**：查询串经**完全相同的** `fts_tokenize` 展开后再 `MATCH ... AGAINST`，保证 token 对齐。
3. 例如「动态功耗」→ `动态功耗 动态功 态功耗`，查询「动态功耗」与查询「功耗」都能命中（三元组重叠）。

实测证据：`evidence/seekdb/fts_tokenizer_probe_20261106.txt`、`fts_probe_chunks_20261106.txt`。

### 3.2 向量检索

- 分块文本经 fastembed + `BAAI/bge-small-zh-v1.5` 本地推理为 512 维向量，写入 `embedding VECTOR(512)` 列。
- `CREATE VECTOR INDEX ... WITH (distance=L2, type=HNSW)`，查询用 `l2_distance(embedding, ?) ORDER BY l2_distance ASC`。
- 模型由 `HF_ENDPOINT=https://hf-mirror.com` 在国内网络下载，全程本地推理，无外部 API 依赖。

### 3.3 混合检索与 RRF 融合

- 全文分支（FTS trigram）+ 向量分支（l2_distance）并行取候选，候选上限 `max(limit*4, 32)`。
- **RRF 融合**：`score = Σ 1/(60 + rank_i)`（K=60），双来源命中得分更高。
- 每条命中带 `matched_by` 来源标记（fts/vector），前端以徽章展示，**来源可溯源**（文档 + 页码）。
- 任一分支不可用时诚实降级并标记，不伪造结果。

### 3.4 三级自动分类

- 分数公式：`0.55 × 课程词典命中 + 0.30 × 章节词典命中 + 0.15 × 检索信号`。
- 词典驱动：`DOMAIN_COURSE_KEYWORDS / DOMAIN_CHAPTER_KEYWORDS / DOMAIN_KP_KEYWORDS`（领域课程/章节/知识点关键词表，样例域含 12 个知识点）。
- 阈值分级：置信度 ≥ 0.65 **自动通过**（status=auto）；≥ 0.45 **建议**（用户一键确认）；否则 **待人工**。用户更正写入 `classification_feedback` 审计表。
- 实测：样例讲义自动分类置信度 82%，12/12 知识点命中（`evidence/seekdb/smoke_e2e_20261106.txt`）。

### 3.5 判分与掌握度

- **判分**（`services/scoring.py`）：选择题字母提取比对；简答题按标准答案关键词覆盖率评分，判分依据（`grading_evidence`）逐题落库，前端可见。
- **掌握度**（`services/mastery.py`）：`mastery = 0.75 × 正确率 + 0.25 × streak 因子`，跨练习轮累计（正确率/连续答对均按累计口径）。实测跨轮变化：如「传播延迟」0 → 43%（首轮答错后重练答对）。
- **复习排期**（`services/review.py`）：间隔重复（1/2/4/7/15/30 天），答错立即生成强化任务，完成后重排。

### 3.6 PowerContext 长期记忆集成

- 服务端：PowerContext 1.2.0（`powercontext server run`，HTTP :8000，seekdb 后端存储）。
- 客户端：官方异步客户端封装为同步 facade（`app/memory/powercontext.py`），服务不可用时不阻塞主流程（降级并给出 `memory_warning`）。
- 每次会话创建时 `ensure_scope`（scope = 会话级记忆命名空间），scope_id 存回 `demo_sessions.scope_id`。
- 自动沉淀事件：练习结果、错题、掌握度变化、学习目标；显式写入：用户笔记。
- 每次写入记录 `memory_events`（含 PowerContext 返回的真实 `entry_id`/`entry_version_id` 引用），**记忆读写证据可审计**。
- 跨会话召回：新会话创建独立 scope，但全局检索（按内容相关性）可召回其他 scope 的记忆——这是「跨会话长期记忆」的机制；验收样例第 7 步实测通过。

## 4. 关键工程决策

| 决策 | 原因 |
| --- | --- |
| 后端运行于 WSL2 | pylibseekdb 仅支持 Linux/macOS；代码仍在 Windows 仓库目录（/mnt/d 挂载），数据目录在 WSL 原生文件系统 |
| seekdb 走 Unix socket + pymysql | 嵌入式引擎的连接方式（`pylibseekdb.open` 提供连接选项） |
| HashRouter | 静态托管（Qoder Sites）无需服务端 rewrite 即可支持任意路由 |
| `VITE_API_BASE_URL` 注入后端地址 | 前后端分离，前端可独立部署到任意静态托管 |
| `generated` 列改名 `is_generated` | seekdb 中 `generated` 为保留字（实测发现） |
| 阈值与判分参数进配置 | `EXAMPILOT_CLASSIFY_HIGH_CONFIDENCE` 等，可经测试校准 |
