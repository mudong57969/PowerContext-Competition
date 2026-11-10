# minimax — 最小 Python 业务样例

MiniMax 赛道的最小业务样例：一张固定任务表，按 `status` 筛选记录。业务规格独立在
[`SPEC.md`](SPEC.md)，实现与测试在同一目录下，运行时通过 **PowerContext**（seekdb 后端）
把规格、实现、测试和任务状态组织成一个可复现的上下文闭环。

当前实现对应规格 **v2**：状态入参的首尾空白被忽略，`" open "` 与 `"open"` 返回相同结果；
不传状态时返回全部记录。

一页技术说明见 [`TECH-NOTE.md`](TECH-NOTE.md)（seekdb 查了什么、代码依据什么改的、
PowerContext 恢复了什么、验收条件与证据文件的对应关系）。

## 文件

| 文件 | 说明 |
| --- | --- |
| `SPEC.md` | **业务规格**（版本化，当前 v2） |
| `samples/SPEC.v1.md` | 业务规格**初版**（v1），用于演练规格升级流程 |
| `task_status.py` | 业务实现：`RECORDS` 固定记录 + `list_tasks(status=None)` |
| `test_task_status.py` | pytest 风格的测试（4 个回归 + 1 个目标测试，共 5 项） |
| `run_tests.py` | 零依赖运行器，用标准库执行同样的 `test_*` 函数 |
| `pc_client.py` | 零依赖 HTTP 客户端，封装 PowerContext Server 接口 |
| `ingest.py` | **初始化**：建 Scope、导入规格/实现/测试、生成 `state/scope.json` |
| `remember_state.py` | 写入任务状态，并把此前的状态置为「已被取代」 |
| `context.py` / `context` | `context` 命令：查询真实路径、识别目标/回归测试、组装上下文 |
| `change/` | 本次修改的输入上下文、diff、修改记录 |
| `snapshot/pre-fix/` | 修复前的代码快照（用于复现修复前的失败） |
| `logs/` | 安装、启动、导入、写入、查询、读取、测试、复跑的全部运行记录 |
| `evidence/` | **开发证据**：模型实际修改代码的原始会话记录（已脱敏） |
| `TECH-NOTE.md` | 一页技术说明 + 验收条件对照表 |

---

## 开发证据（模型实际修改的原始记录）

`evidence/` 是从本机会话记录**只读导出**的原始证据，已按 `evidence/SHA256SUMS` 中的规则做路径与凭据脱敏：

| 文件 | 提供什么证据 |
| --- | --- |
| `evidence/minimax-edit-session.md` | **可读会话实录**：MiniMax-M3.1-Flash 实际代码修改的可读会话实录。28 条事件（15 次工具调用 + 13 条结果），按原始顺序保留 `message_id`、`turn_id`、时间戳、模型标识与工具输出全文 |
| `evidence/minimax-edit-excerpt.json` | **机器可核验事件**：包含模型标识、工具调用、修改结果及交叉验证记录。附保真校验（28/28 PASS：逐条回查原件重新脱敏后逐字节比对）与 7 项一致性核对（7/7 PASS） |
| `evidence/SHA256SUMS` | **校验与规则**：原始与导出文件哈希、筛选和脱敏规则 |

### 原始模型编辑记录 ↔ 仓库内证据

| 原始会话记录（`evidence/`） | 对应仓库证据 |
| --- | --- |
| seq 15 / seq 17：两次 `edit` 工具调用（含完整 `old_string` / `new_string`） | [`change/task_status.diff`](change/task_status.diff) 的对应 hunk |
| seq 11–12：`context --emit-context` 生成实际开发上下文 | [`change/input-context.md`](change/input-context.md)（本次修改的输入） |
| seq 1–3：修改前运行测试失败（`4 passed, 1 failed`，退出码 1） | [`logs/test-before-fix.log`](logs/test-before-fix.log) |
| seq 21–22：修改后运行测试全过（`5 passed, 0 failed`，退出码 0） | [`logs/test-after-fix.log`](logs/test-after-fix.log) |
| seq 27–28：通过 PowerContext 写入「已修复」状态 | [`logs/remember-state-after-fix.log`](logs/remember-state-after-fix.log) |

> Git 提交的作者是提交者本人；**模型归属由 `evidence/` 的会话记录证明**（每条助手消息都带 `MiniMax-M3.1-Flash` 模型标识与工具调用原文）。

---

## 从零复跑（评审用自己的目录 + 空数据目录）

前置条件：Python 3.11+、Git，以及 [`uv`](https://docs.astral.sh/uv/)（或用 `pip` 等价安装）。
macOS / Linux 支持；Windows 下嵌入式 seekDB 不可用。

### 1. 准备代码目录

```bash
git clone <本仓库> ~/work/minimax-sample
cd ~/work/minimax-sample
```

### 2. 建独立虚拟环境并安装

```bash
VENV="$HOME/.venvs/powercontext-minimax"
python3.12 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install 'powercontext[cli,server,seekdb]'
```

本机（macOS 27.2 / arm64 / Python 3.12.16）实测可安装版本：`powercontext==1.5.0`、
`pylibseekdb==1.4.0.post2`（`cp312-abi3-macosx_15_0_arm64` wheel）。

后面所有命令都用 `"$VENV/bin/python"`，保证用的是刚装好的环境。

### 3. 用**一个端口变量**配置 Server、脚本和 doctor

> **关键**：Server 端口、`POWERCONTEXT_URL`、`doctor --server-url` 必须来自同一个变量。
> 少设一处，脚本就可能写到另一个实例（例如别的检查者已经在跑的 8000）上。

```bash
PORT=8000                                    # 换端口只改这一处
export POWERCONTEXT_URL="http://127.0.0.1:${PORT}"   # 脚本（ingest / context / remember_state）连这里
export POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1
export POWERCONTEXT_SERVER_HTTP_PORT="$PORT"         # Server 监听这里
```

> `powercontext doctor` 的 `--server-url` 必须写在 **子命令后面**（`powercontext doctor --server-url …`）；
> 写在前面（`powercontext --server-url … doctor`）对 `doctor` 不生效，它会去检查默认的 8000。

### 4. 用**空数据目录**启动 Server（seekdb 后端）

```bash
export POWERCONTEXT_HOME="$HOME/.powercontext-minimax"   # 空目录即可
export POWERCONTEXT_SERVER_DATABASE_KIND=seekdb
export POWERCONTEXT_SERVER_DATABASE_PATH="$POWERCONTEXT_HOME/seekdb"
export POWERCONTEXT_SERVER_ACCESS_MODE=disabled
unset POWERCONTEXT_SERVER_DATABASE_URL    # seekdb 不接受 SQLAlchemy URL
"$VENV/bin/powercontext" server run       # 前台进程；停止用 Ctrl-C
```

seekdb 首次初始化约 1 分钟。另开一个终端检查（**用第 3 步的同一个变量**）：

```bash
"$VENV/bin/powercontext" doctor --server-url "$POWERCONTEXT_URL"
```

期望看到 `server liveness: ok - http://127.0.0.1:<PORT> status=ok` 与
`database: ready`；如果这里显示的是别的端口，说明第 3 步的变量没有生效。

### 5. 初始化：导入资料并生成 `state/scope.json`

```bash
"$VENV/bin/python" minimax/ingest.py
```

这一步会创建（或复用）一个 Scope，把 `SPEC.md`、`task_status.py`、
`test_task_status.py` 作为 Content Source 导入 seekdb，并生成运行时状态文件
`minimax/state/scope.json`（记录 scope_id 与 Server 地址）。**该文件由初始化生成，不入库**
（见 `.gitignore`）。

### 6. 写入任务状态

```bash
"$VENV/bin/python" minimax/remember_state.py "你的状态描述" "写入原因（可选）"
```

同一条状态重复写入会复用现有条目；写入新状态时，此前的状态被置为 `forgotten`
（内容与 revision 保留为历史），因此「当前状态」始终唯一。

### 7. 查询上下文

```bash
"$VENV/bin/python" minimax/context.py
# 解释器选择见下面「解释器选择」一节
# 需要把上下文存成文件时：
"$VENV/bin/python" minimax/context.py --emit-context minimax/change/input-context.md
```

`context` 命令的全部输出都来自实时查询，没有任何硬编码：

1. `POST /v1/scopes/{scope_id}/sources` → 规格（**当前版本**）、实现、测试及其真实路径；
   同一份规格存在多个 source ID 时按版本号优先选用当前版本，旧版本列为「已归档」；
2. `POST /v1/atomic-memory/list` → 任务状态（当前状态与已被取代的历史状态）；
3. `POST /v1/context/prepare` → Server 组装好的、真正交给模型请求的有界上下文。

目标测试与回归测试是**从存储下来的测试源码里判定**的：body 中出现带空白的状态字面量
（`" open "`）且同时出现去空白形式（`"open"`）的测试即为目标测试，其余为回归测试。

### 8. 运行测试：修复前 vs 修复后

**修复后**（当前交付实现）——五项全过，退出码 **0**：

```bash
cd ~/work/minimax-sample
python3 minimax/run_tests.py ; echo "exit=$?"
```

期望输出 `5 passed, 0 failed, 5 total` 与 `exit=0`。

**修复前**（同一套测试 + `snapshot/pre-fix/` 里的旧实现）——目标测试失败，退出码 **1**：

```bash
cd ~/work/minimax-sample
TMP="$(mktemp -d)"
cp minimax/snapshot/pre-fix/task_status.py "$TMP/task_status.py"   # 修复前的实现
cp minimax/test_task_status.py    "$TMP/test_task_status.py"      # 同一套（当前）测试
cp minimax/run_tests.py           "$TMP/run_tests.py"
( cd "$TMP" && python3 run_tests.py ) ; echo "exit=$?"
rm -rf "$TMP"
```

期望输出 `4 passed, 1 failed, 5 total` 与 `exit=1`，失败项是
`test_status_with_surrounding_whitespace_matches_trimmed_status`，
原因是 `assert list_tasks(" open ") == list_tasks("open")` 失败。

> 交付的 `minimax/test_task_status.py` 与 `minimax/snapshot/pre-fix/test_task_status.py`
> 的 sha256 相同（`6f735a5a…`），即两次跑的是同一套测试，只有实现不同。

### 9. 规格升级演练：v1 → v2

`context` 的规格选择逻辑依赖「同一份规格存在多个版本」，这一条用交付的 v1 样例即可完整复现：

```bash
cd ~/work/minimax-sample

# 从空库导入初版 v1（--spec 只影响这一次导入，不修改 minimax/SPEC.md）
"$VENV/bin/python" minimax/ingest.py --spec minimax/samples/SPEC.v1.md
"$VENV/bin/python" minimax/context.py        # 应选中 v1：spec minimax-spec-v1 version=v1

# 切换到 v2（当前规格）并重新导入
"$VENV/bin/python" minimax/ingest.py
"$VENV/bin/python" minimax/context.py        # 应选中 v2，正文含 R5/A4，v1 变为「已归档」
```

判断依据（`context` 输出里）：

```
## 1. 业务规格（当前版本）
source_id: minimax-spec-v2
version:   v2
来源:      <你的目录>/minimax/SPEC.md
...
已归档的旧版本规格：
  - minimax-spec-v1 version=v1 来源=<你的目录>/minimax/SPEC.md
```

v2 正文里应能看到空白条款：

```
- **R5** **状态入参的首尾空白必须被忽略**：`status=" open "` 与 `status="open"`
- **A4** `status=" open "` → 与 `status="open"` 结果完全相同（3 条记录）。
```

### 10. 重置样例

三种粒度，任选其一：

```bash
# (a) 换一个全新的 Scope（同一数据目录，保留其他数据）
rm -f minimax/state/scope.json
"$VENV/bin/python" minimax/ingest.py --scope-key reset-$(date +%s)

# (b) 换一个全新的 Scope 并立即导入当前规格
"$VENV/bin/python" minimax/ingest.py --scope-key reset-$(date +%s)

# (c) 彻底重来：停掉 Server，删掉数据目录与状态文件，再从第 4 步开始
#     rm -rf "$POWERCONTEXT_HOME" minimax/state
```

`--scope-key` 决定 Scope 的幂等键：同一个键会复用同一个 Scope，换一个键就是一份全新的样例。

---

## 解释器选择

`minimax/context` 这个包装命令按以下顺序挑解释器，**全部是相对路径或显式覆盖，不含任何本机绝对路径**：

1. `$MINIMAX_PYTHON`（显式覆盖，最优先）
2. `<仓库>/minimax/.venv/bin/python`
3. `<仓库>/.venv/bin/python`
4. `python3`（PATH 上的任意 Python 3.9+）

要用第 2 步刚建好的虚拟环境，二选一：

```bash
export MINIMAX_PYTHON="$VENV/bin/python"     # 方式一：显式覆盖
./minimax/context
```

```bash
python3.12 -m venv .venv                     # 方式二：建在仓库根目录，包装命令自动识别
./minimax/context
```

其余脚本（`ingest.py` / `context.py` / `remember_state.py` / `run_tests.py`）都是纯标准库，
用 `"$VENV/bin/python"` 或 `python3` 都可以。

---

## 配置项

| 变量 | 作用 |
| --- | --- |
| `POWERCONTEXT_URL` | Server 地址，默认 `http://127.0.0.1:8000`。**改了端口就必须改它** |
| `POWERCONTEXT_SCOPE_ID` | 直接指定 Scope id，跳过 `state/scope.json` |
| `POWERCONTEXT_TOKEN` | Server 鉴权 token（开启鉴权时由 secret store 提供，**不要**写入仓库或日志） |
| `MINIMAX_PYTHON` | `context` 包装命令使用的解释器 |
| `MINIMAX_SCOPE_KEY` | `ingest.py` 使用的 Scope 幂等键（换值 = 重置样例） |

---

## 安全与仓库卫生

- 仓库内**不含任何真实凭据**：日志与文档只有 scope_id、路径、artifact_id、版本号；
  启用鉴权时 token 由调用方通过环境变量注入，本仓库不记录。
- `minimax/state/` 与 `__pycache__/` 已列入 `.gitignore`：`scope.json` 属于运行时产物，
  每次初始化时重新生成。
- 本样例只使用标准库（`urllib` / `ast` / `json`），不引入第三方依赖。

## 运行记录

| 文件 | 内容 |
| --- | --- |
| `logs/install.log` | 独立虚拟环境安装（命令与退出码） |
| `logs/server.log` | Server 启动日志（seekdb 后端就绪） |
| `logs/ingest-spec-v1.log` | 导入规格初版 v1 |
| `logs/context-spec-v1.log` | v1 下的 `context` 输出 |
| `logs/ingest-spec-v2.log` | 更新规格后重新导入 v2 |
| `logs/context-spec-v2.log` | v2 下的 `context` 输出（本次修改的输入来源） |
| `logs/test-before-fix.log` | 修复前测试：4 通过 / 1 失败，退出码 1 |
| `logs/ingest-after-fix.log` | 修复后重新导入代码 |
| `logs/test-after-fix.log` | 修复后测试：5 通过 / 0 失败，退出码 0 |
| `logs/remember-state-after-fix.log` | 状态写入 + 旧状态置为已被取代 |
| `logs/context-after-fix.log` | 新进程复跑 `context`：读回并使用「已修复」状态 |
| `logs/review/` | 评委口径复跑（空数据目录、独立端口）的完整日志 |

## 当前测试预期

| 测试 | 预期 |
| --- | --- |
| `test_list_tasks_without_status_returns_every_record` | 通过 |
| `test_list_tasks_with_open_status_returns_only_open_records` | 通过 |
| `test_list_tasks_with_closed_status_returns_only_closed_records` | 通过 |
| `test_list_tasks_returns_a_new_list_each_call` | 通过 |
| `test_status_with_surrounding_whitespace_matches_trimmed_status` | 通过（目标测试，修复前失败） |
