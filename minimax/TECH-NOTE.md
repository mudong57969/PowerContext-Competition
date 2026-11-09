# 技术说明（MiniMax 样例）

一页讲清三件事：**seekdb 查了什么**、**MiniMax 根据什么改了代码**、**PowerContext 恢复了什么**，
以及六项交付验收条件分别由哪条复跑命令、哪个证据文件证明。

---

## 1. seekdb 查了什么

**后端**：嵌入式 OceanBase seekDB（`pylibseekdb`），跑在 PowerContext Server 进程内：

```bash
export POWERCONTEXT_SERVER_DATABASE_KIND=seekdb
export POWERCONTEXT_SERVER_DATABASE_PATH="$POWERCONTEXT_HOME/seekdb"
unset POWERCONTEXT_SERVER_DATABASE_URL      # seekdb 不接受 SQLAlchemy URL
```

**存了两类东西，职责不同**：

| 类型 | 内容 | 可变性 | 用途 |
| --- | --- | --- | --- |
| Content Source | 业务规格 / 实现 / 测试模块的正文 | 不可变，每次导入产生新的 `source_id` | 证据：真实路径、版本、代码与测试原文 |
| Atomic Memory | 任务状态（kind=`task-state`） | 可写、可停用（`forgotten`） | 当前状态：跨进程、跨会话恢复 |

Source 的正文首行带 `# source_path: <绝对路径>`，metadata 里再存一份 `path`，因此查询结果里的
路径是**文件真身**，不是脚本里写死的字符串。

**实际发出的查询**：

| 接口 | 用途 | 在样例中的调用方 |
| --- | --- | --- |
| `POST /v1/scopes` | 创建/复用 Scope（幂等键） | `ingest.py` |
| `POST /v1/sources/content` | 写入 Content Source | `ingest.py` |
| `POST /v1/scopes/{scope_id}/sources` | 取全部 Source → 真实路径、版本、代码与测试正文 | `context.py` |
| `POST /v1/atomic-memory/list` | 取任务状态（`active` + `forgotten`） | `context.py` |
| `POST /v1/atomic-memory/search` | 文本检索状态条目 | `pc_client.py` |
| `POST /v1/memory/remember` | 写入任务状态 | `remember_state.py` |
| `POST /v1/atomic-memory/lifecycle` | 把被取代的状态置为 `forgotten` | `remember_state.py` |
| `POST /v1/context/prepare` | Server 组装交给模型请求的有界上下文 | `context.py` |

**版本优先选用**：`context` 把所有 Source 读回来后，按角色分组；规格组按**版本号**取最大
（`v2` > `v1` > 无版本），代码与测试组按导入位置取最新。因此重新导入 v2 不会遮蔽 v1，
v1 降级为「已归档」，可追溯。

---

## 2. MiniMax 根据什么改了代码

**输入**：`change/input-context.md` —— 由 `context` 命令从 seekdb **实际生成**，包含

1. 业务规格当前版本正文（v2，含 R5/A4/A5）；
2. 相关代码（`task_status.py` 全文 + 真实路径）；
3. 目标测试（`test_status_with_surrounding_whitespace_matches_trimmed_status`），
   由源码中「带空白字面量 + 去空白字面量」自动识别，不是硬编码测试名；
4. 回归测试（其余 4 项）；
5. 当时的任务状态。

**依据**：规格 v2 的 **R5**（状态入参首尾空白必须被忽略）、**A4/A5**
（`" open "` 与 `"open"`、`" closed "` 与 `"closed"` 结果相同），同时保留 v1 的
**R3**（不传状态返回全部记录）。

**改动**（`change/task_status.diff`，仅 `task_status.py` 的筛选逻辑）：

```python
    if status is None:
        return list(RECORDS)
-   return [record for record in RECORDS if record.status == status]
+   normalized = status.strip()
+   return [record for record in RECORDS if record.status == normalized]
```

归一化只作用于**入参**：不修改记录自身的 `status` 字段，不改变大小写语义，
`status=None` 的分支原样保留。

**没改**：五项测试（`test_task_status.py` 的 sha256 与修复前快照一致）、修复前快照。

---

## 3. PowerContext 恢复了什么

**跨进程的任务状态**：状态写入 seekdb 后，退出 `context` 命令再启动（新 PID），
新进程仍能读到并把它放进 Server 组装的上下文里——恢复来源是数据库，不是本地文件或日志。

```
[当前状态] art_…  rev=1 state=active:   目标测试已修复：…5 项测试全部通过（退出码 0）
[已被取代] art_…  rev=1 state=forgotten: 目标测试失败，待修复
prepared context: status=ready 含当前状态=True
```

**状态历史**：`待修复`（forgotten，内容与 revision 保留）与 `已修复`（active）并存，
`artifact_id` + `revision` + `state` 三者一起构成可核对的当前/历史区分。

**规格历史**：v1 与 v2 各自一条 Source，按版本号优先选用当前版本。

**边界**：PreparedContext 是**临时只读**的历史数据，当前用户指令与仓库规则始终优先；
`scope_id` 由可信应用决定，不交给模型输出。

---

## 4. 六项交付验收条件 → 复跑命令 / 证据文件

复跑前提：空数据目录、独立端口，命令见 [`README.md`](README.md) 第 3–10 步。
所有命令都在**仓库根目录**执行。

| # | 验收条件 | 复跑命令 | 预期 | 证据文件 |
| --- | --- | --- | --- | --- |
| 1 | 空库可导入 v1 并被选中 | `python3 minimax/ingest.py --spec minimax/samples/SPEC.v1.md` → `python3 minimax/context.py` | 选中 `minimax-spec-v1`，`version=v1` | `logs/review/03-import-v1.log`、`logs/review/04-context-v1.log` |
| 2 | 切换到 v2 并重新导入后输出 v2 正文与真实来源，旧版归档 | `python3 minimax/ingest.py` → `python3 minimax/context.py` | 选中 `minimax-spec-v2`，正文含 R5/A4，v1 列为「已归档」 | `logs/review/05-import-v2.log`、`logs/review/06-context-v2.log` |
| 3 | 同一套测试在修复前因空格行为失败 | 见 README 第 8 步「修复前」命令 | `4 passed, 1 failed`，**退出码 1** | `logs/review/07-test-prefix.log` |
| 4 | 同一套测试在修复后五项全过 | `python3 minimax/run_tests.py` | `5 passed, 0 failed`，**退出码 0** | `logs/review/08-test-fixed.log` |
| 5 | 写入「已修复」后新进程读回并使用该状态，能区分「待修复」 | `python3 minimax/remember_state.py "目标测试已修复：…"` → `python3 minimax/context.py`（再跑一次） | 新 PID 输出 `[当前状态] … 已修复`、`含当前状态=True`，旧状态为 `forgotten` | `logs/review/09-remember-state.log`、`logs/review/10-context-state.log` |
| 6 | 实例隔离且零凭据 | `doctor --server-url "$POWERCONTEXT_URL"` 检查同一端口；`grep -riE 'token\|password\|secret\|bearer' minimax/logs minimax/README.md` | doctor 指向同一端口；扫描无真实凭据 | `logs/review/02-doctor.log`、`logs/review/11-isolation-and-credentials.log` |

### 规格自身的验收标准（A1–A5）→ 对应测试

| 规格条目 | 内容 | 对应测试 |
| --- | --- | --- |
| A1 | 不传状态 → 5 条记录 | `test_list_tasks_without_status_returns_every_record` |
| A2 | `status="open"` → 3 条（T-001/T-002/T-004） | `test_list_tasks_with_open_status_returns_only_open_records` |
| A3 | `status="closed"` → 2 条（T-003/T-005） | `test_list_tasks_with_closed_status_returns_only_closed_records` |
| A4 | `status=" open "` 与 `"open"` 结果相同 | `test_status_with_surrounding_whitespace_matches_trimmed_status`（目标测试） |
| A5 | `status=" closed "` 与 `"closed"` 结果相同 | 同上（目标测试覆盖空白归一化本身） |

> A5 与 R5 共用同一个目标测试：它断言的是「空白归一化」，闭/开两个状态走同一条归一化路径。

---

## 5. 已知边界

- 未配置 generation / embedding model：显式记忆写入与检索可用，**依赖模型的自动抽取与语义检索**
  未启用；Server 启动时会打印相应提示。
- 嵌入式 seekDB 不支持 Windows；Windows 下需 WSL2。
- 目标测试与回归测试的判定基于**当前测试源码的字面量形状**，若将来测试改写结构，需同步调整
  `context.py` 的 `_split_tests`。
