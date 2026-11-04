---
title: PDF 物理页采集与检索
description: 完整 PDF 的逐页捕获、修订身份及原生 Memory 精确引用。
---

# PDF 物理页采集与检索

`powercontext.sources.pdf_pages` 提供 `PDFDocumentInput`、`PDFPageInput`、`parse_pdf_document`、`PDF_PAGE_SOURCE_DEFINITION` 和 `search_pdf_pages`。需要 pypdf；比赛固定环境提供 6.19.0，不需要 OCR、模型文件或在线推理服务。

`parse_pdf_document(PDFDocumentInput(document_id=..., content=raw_pdf_bytes))` 原子地返回全部物理页元组。文档 ID 不能为纯空白，摘要来自完整原始 bytes。严格解析 PDF 的交叉引用和页面内容，每页独立使用 plain 文本提取，页码从 1 开始，保留空白页；不跨页拼接或按问题裁页。空文件、损坏、密码不能以空串解锁或任何页面解析失败均抛 `ValueError`。空密码权限 PDF 可读取。无需复刻空白布局，不进行扫描件 OCR。严格模式会拒绝只能依靠修复才能读取的文件。

Definition 名为 `pdf-page`，版本字符串为 `1`，输入类型为 `PDFPageInput`。注册后通过现有 SourceDefinitionRegistry resolve/read 和 Source observation 提交接口使用。每页为 captured Source，正文随 observation 持久化。身份由文档 ID、完整摘要及物理页码的规范 JSON 编码后 SHA-256 生成，名称固定 73 字符。正文改变但文件摘要未更新属于调用方输入不一致，不应伪造摘要；解析器会正确生成摘要。

标准文本投影为 `document_id + "\n" + page.text`，metadata 仅含 `document_id`、`document_sha256`、`page_number`。修订改变字节摘要，因此产生新身份；已有 SourceRef 保留旧修订的准确页值。不要把财报印刷页码当作 PDF 物理页码。

调用方沿既有 ingestion、pipeline 与 Memory 持久化流程入库。`await search_pdf_pages(memory, question, limit=20)` 只使用传入 scoped Memory 的公开 `search`、`get`。它规范化 query、扩展通用金融概念并以短查询绕开长问题的词项覆盖门槛；候选采用全文 BM25 风格分数、IDF 覆盖、局部窗口和财务短语重新排序。所有候选来自原生 FTS，逐条 get 后使用实际记录 citation；不创建第二个持久化索引，不读 PDF 文件、训练数据或答案。

只返回 active 且恰好关联一个 `pdf-page` 来源的记录，按 Source 身份去重，避免混合多页的 Memory 被声称为单页精确证据。`limit=0` 或空白问题返回空元组，负数、布尔和非整数 limit 拒绝。返回数量最多为 limit；没有足够相关候选时不会伪造引用填充。

多查询召回会增加本地搜索及 get 开销，词项 IDF 仅基于召回候选，不保证最优排序。通用术语扩展也可能引入噪声，原生检索未召回的页无法被重排找回。默认 FTS 无需向量服务，仍遵守原生索引、scope、生命周期和可见性规则。

公开测试的页覆盖和引用正确性不代表 FinanceBench 隐藏质量门槛。公开样例没有 gold，不能据此计算官方 Recall@20。独立代理必须按每问题不同 `(document_id, physical_page_number)` 累计命中数与标注数之比计算，并与官方结果分开陈述。

## 离线查询覆盖与排序

检索保留原始问题，并在 Memory 搜索之前生成规则化单复数、D&A / PP&E / EPS / CapEx 等双向金融缩写、财务短语和长问题后部关键词查询。最多执行 16 次搜索；每次候选上限仍为 `max(60, min(200, limit * 4))`，`limit=20` 时为 80。company 等通用词只在没有具体财务术语时获得词形召回探针，不作为额外财务权重。

匹配概念后会依次考虑全部别名，而非只取前两个；概念别名先于普通单词探针获得剩余预算，查询按空白与大小写归一化去重。长问题中，已选关键词若位于前 16 个有效词之后、属于财务词且尚未被别名覆盖，会优先为其中一个词保留探针，避免别名挤掉尾部术语。若同一问题匹配大量概念，仍受 16 次总预算约束，不保证所有扩展都能执行。该策略改善别名覆盖，并不保证代理问题的 Top20 分数提高。

重排去除问题中的通用指令词，沿用正文相关性分数；文档 ID 与问题中明确出现的非通用词的交集、账目短语后六个词内的非年份数值作为优先信号。文档 ID 不拼入正文，不改变正文长度归一化。该启发式可能偏好有数字的提及，无法纠正任意命名的文档 ID、候选截断或错误标注，也不保证每个问题的 Top5/Top10 都改善。

代理分数不是官方隐藏成绩。财报可解析不意味着能把整页写入一个 Memory 条目：原生 Memory 单条正文上限为 8192 UTF-8 字节，超长页面应由调用方提取流程按其引用契约处理，不能截断后声称保存了整页。本模块的解析、标准文本投影和引用契约未改变。
