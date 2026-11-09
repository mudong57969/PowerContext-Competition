# samples —— 交付的样例材料

| 文件 | 说明 |
| --- | --- |
| `SPEC.v1.md` | 业务规格**初版**（v1）。用于演练「从空库导入 v1 → 切换到 v2 → 重新导入」的升级流程。 |

## 为什么需要它

当前生效的规格在 `minimax/SPEC.md`（v2）。规格升级是样例的核心流程之一：重新导入会产生新的
source ID，`context` 按版本号优先选用当前版本。评审要完整演练这条流程，需要一份可导入的旧版规格；
本目录提供的就是它。

## 怎么用

```bash
# 从空库导入初版 v1
python3 minimax/ingest.py --spec minimax/samples/SPEC.v1.md

# 查询：应选中 v1
python3 minimax/context.py

# 切换到 v2（当前规格）并重新导入
python3 minimax/ingest.py

# 查询：应选中 v2，旧版本降级为「已归档」
python3 minimax/context.py
```

`--spec` 只影响这一次导入，`minimax/SPEC.md` 本身不会被修改。
