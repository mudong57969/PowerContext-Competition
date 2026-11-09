# 修改记录：按规格 v2 修复 `status` 空格处理

时间: 2026-11-09
分支: `2026-competition-ecosystem`
提交: 未提交（按要求暂不 commit / push）

## 1. 输入

本次修改的输入是 **PowerContext 实际生成的新版上下文**：

- 文件: `minimax/change/input-context.md`
- 生成方式: `python3 minimax/context.py --emit-context minimax/change/input-context.md`
- 内容来源: 全部来自 seekdb 支撑的实时查询
  - `POST /v1/scopes/{scope_id}/sources` → 业务规格当前版本（v2）、实现、测试
  - `POST /v1/atomic-memory/list` → 任务状态
  - `POST /v1/context/prepare` → Server 组装的上下文
- 运行记录: `minimax/logs/context-spec-v2.log`

规格依据: `minimax/SPEC.md` v2 的 **R5**（状态入参首尾空白必须被忽略）与
**A4/A5**（`" open "` 与 `"open"` 结果相同）。v2 保留了 v1 的 R3（不传状态返回全部记录）。

## 2. 改动

只改了 `minimax/task_status.py` 的筛选逻辑：

```python
    if status is None:
        return list(RECORDS)
-   return [record for record in RECORDS if record.status == status]
+   normalized = status.strip()
+   return [record for record in RECORDS if record.status == normalized]
```

同时更新了同一文件里已经过时的两处说明（模块 docstring 与 `list_tasks` docstring），
使其描述新的归一化行为。除此之外没有改动任何逻辑。

完整 diff: `minimax/change/task_status.diff`

## 3. 未改动

| 文件 | 说明 |
| --- | --- |
| `minimax/test_task_status.py` | **未修改**，仍是原有五项测试；sha256 与 `snapshot/pre-fix/` 中的一致 |
| `minimax/snapshot/pre-fix/` | 修复前快照完整保留 |
| `minimax/run_tests.py` | 未修改 |

## 4. 验证

```bash
/opt/homebrew/bin/python3.12 minimax/run_tests.py
```

结果：**5 passed, 0 failed**，退出码 **0**。

完整日志（含代码 sha256、命令、退出码、逐项结果）: `minimax/logs/test-after-fix.log`

## 5. 状态回写

修复完成后把结果写回 PowerContext，并把此前的「目标测试失败，待修复」置为
`forgotten`（内容与 revision 保留为历史）：

- `minimax/logs/remember-state-after-fix.log`
- 当前状态: `art_5ac5818d49084b32a64f85d055ec8193` rev=1 state=active
- 历史状态: `art_551d73f5bd0b4280bc780f1987422ea8` rev=1 state=forgotten

新进程复跑 `context` 验证读回: `minimax/logs/context-after-fix.log`
（`含当前状态=True`，且 prepared context 里只有「已修复」这一条）。
