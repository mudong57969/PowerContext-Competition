# seekdb 混合候选检索

配置 seekdb 和 embedding 模型后，Memory 的 hybrid 候选查询使用一条参数化的 `UNION ALL` statement。FTS 和 vector 子查询分别在数据库内应用 scope、Memory artifact、可选 tag 过滤及候选上限。两路保留 channel、身份、正文及距离，再交给既有候选准入和 RRF 融合。FTS-only、vector-only 和 OceanBase 配置仍使用原策略。

Memory 服务的候选上限仍为 `max(coarse_limit * 4, 32)`。没有 reranker、返回 10 条时，每路最多 40 条；没有缩减候选预算。外围 ORDER BY 恢复 FTS 分数与向量距离顺序，并以身份消除返回集合内的同分歧义；原向量子查询的近似候选边界仍需实机验证。

投影行的 `head_revision` 可能落后于当前 Memory head。它用于观察投影，而非直接排除未修改的活跃条目。原 backend 在候选检索前后校验请求 head；channel 解码使用请求中已经校验的 Memory 引用，保留精确 `entry_id` 和 `entry_version_id`，不伪造历史正文。

## 验证边界

离线单元测试能够验证一次候选 execute、绑定参数、过滤 SQL 的结构、通道解码及单通道委托，不能证明 seekdb 支持该 SQL 或使用了两个索引。

带 tag 时，vector 分支先在数据库内按 artifact 和 entry 聚合符合标签条件的身份，再连接向量表并执行 `APPROXIMATE` 检索；不把标签条件放在已截断的 ANN 候选之后过滤。`all` 使用标签数量门槛，`any` 使用至少一个标签的门槛，均在候选上限之前生效。FTS-only、vector-only 和融合算法保持原行为。

验收应在官方固定 `pylibseekdb==1.3.0.post4` 环境执行公开 acceptance、SQLAlchemy 事件计数和真实 EXPLAIN。可使用完整的 `EXPLAIN FORMAT=JSON` 检查实际 statement，尤其需要检查少量标签命中和多标签过滤后的候选完整性；仅出现 `VECTOR INDEX` 并不能证明过滤和候选预算正确。公开代理指标不能替代官方隐藏 qrels，也不能把开发主机延迟视为正式资源配额验收。

## Windows 实验环境建议

嵌入式 seekdb profile 要求 Linux/macOS；竞赛公开自测固定为 Linux x86_64、Python 3.12。Windows 原生 `.venv` 不适合作为此题实机验收环境。

建议另行准备 WSL2 + Ubuntu 24.04，并在 Linux 中新建 Python 3.12 环境，不复用 Windows `.venv`。微软安装入口为 [Install WSL](https://learn.microsoft.com/en-us/windows/wsl/install)。WSL 安装涉及系统功能、下载和可能的重启，应由用户批准后单独进行。

环境准备好后，遵循仓库 `competition/README.md` 与 `competition/requirements.txt` 创建官方自测环境；不要用最新 seekdb 包替代固定 wheel。先在原稳定提交的独立副本运行双查询基线，再在同库、同 scope/head/embedding 上比较候选方案。真实数据库和临时文件放在 Linux 文件系统中；最终性能结论还须在官方 1 CPU、2 GiB 配额环境复核。
