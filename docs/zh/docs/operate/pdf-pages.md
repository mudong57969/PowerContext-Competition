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
