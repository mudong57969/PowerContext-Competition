---
title: 原文证据片段选择
description: 内置 Runtime 的查询相关原文选择、引用身份和完整 UTF-8 预算。
---

# 原文证据片段选择

内置 `PrepareContextRequest(evidence_selection=True)` 开启离线 Memory 原文片段选择，默认值为严格布尔值 `False`。关闭时保留既有普通 prepare 和增量 Context Pack 行为。

此模式仅选择 Memory，优先于 `assembly` 与 `include_code`，不拼入其他证据家族。`Runtime.context.prepare` 和 `prepare_incremental` 共用同一最终正文；`PreparedContextBuilder.build_scopes_result` 另外返回 `fragments`，与 `origins` 逐项对应。HTTP/MCP/SDK 的生成请求契约未扩展该开关；这里描述的是内置 Python Runtime/Builder 入口。

每个片段含原始 `MemoryEntryAddress`、半开 Python 字符区间 `start/end` 和精确切片 `text`。片段不做摘要、翻译或改写。同一条目可有多个不连续片段；不同 scope 的同文本保留各自身份。非空输出沿用 trust policy 与 V1 envelope，JSON 包含 `trust="untrusted_history"`、完整 scoped citation、原文和坐标。

每次候选加入、相交或相邻区间合并后，都重新序列化完整输出并按 UTF-8 实际字节数判断。结构、引用、坐标、转义、正文、trust policy 和 envelope 全部计费；装不下时返回合法空 Context，不省略必需字段。

预算探针报告实际交付数量、剩余字节与因预算未能装入的 Memory 条目数；详细遗漏分类保存在 Builder 结果和既有 recall trace 中。主动选择原文片段不等同于旧模式的正文前缀截断。

## 离线算法与来源

选择器使用词形归一化、查询词 IDF 覆盖、BM25 风格相关性、位置、标题、长度、比较/结果线索、数字及相邻句特征。一个固定的 13 特征线性句子排序器产生分数；相邻完整句形成候选窗口，长段落另生成查询锚定的原文窗口。随后以新增收益及实际字节开销选择、合并窗口。

固定权重离线拟合于 SciFact 原始训练分区中的 404 个开发请求、12,690 个句子行（792 个正例），L2 系数 0.001，无类别平衡。94 个请求留出，训练与留出使用的全部候选文档不相交；排除了比赛公开 query 和八篇公开文档。权重不含 claim ID、文档 ID、答案文本或字典式特判。运行时仅使用标准库，不加载数据集、标注、模型文件或网络服务。

数据与署名：David Wadden、Shanchuan Lin、Kyle Lo、Lucy Lu Wang、Madeleine van Zuylen、Arman Cohan、Hannaneh Hajishirzi，*Fact or Fiction: Verifying Scientific Claims*，EMNLP 2020；摘要源自 Kyle Lo 等的 Semantic Scholar S2ORC（ACL 2020）。[SciFact 官方来源](https://github.com/allenai/scifact)与[许可证](https://github.com/allenai/scifact/blob/master/LICENSE.md)：claims/evidence 为 CC BY 4.0，S2ORC 语料为 ODC-By 1.0。

实验归档 URL、SHA-256、分区、配置、特征次序、拟合脚本、比较结果及报告位于本地 `.artifacts/context-01-evidence-selection/`。归档未作为产品运行依赖。选定策略为最多四句窗口、相邻支持 0.15、窗口内附加句权重 0.45、字节代价指数 0.2。

## 验证边界

公开 SciFact workload 没有 gold evidence，公开功能测试通过不能证明官方隐藏的 token recall 或完整覆盖门槛。训练/调参结果、文档隔离留出结果与比赛隐藏结果必须分开解释。代理请求保证正例文档在候选中，摘要排列、引用长度和 gold 可装入预算的比例会影响指标；训练分区也不代表其他科学领域或任意同义改写。

片段选择只处理已召回原文，不能找回检索阶段遗漏的文档。它不是通用语义理解或事实核验模型，也不将所选历史内容提升为可信指令。
