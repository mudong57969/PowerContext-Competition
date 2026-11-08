# ExamPilot UAT2 修复验收报告（15 项）

日期：2026-11-08 ｜ 项目：qoder/exampilot ｜ 分支：feature/qoder-exampilot
执行方式：后端代码修复 + 自动化回归 + 真实浏览器端到端验收（browser-use MCP）
结论口径：仅证明“修复项在本环境验证通过”，不声称生产级安全性。

## 一、开始前数据保护

1. **业务数据备份**：修复开工前导出 seekdb 全库备份与 5 个既有会话状态快照（提交前审查时已迁至仓库外 `D:\oceanbase_comp\backups\exampilot\backup_20261107\`，校验和一致）。全程未清库、未删除任何既有课程/资料/题库/练习记录。**通过**
2. **PowerContext 记忆保护**：未执行任何删除/覆盖操作；旧工作区 `D:\oceanbase_comp\powercontext` 未触碰。**通过**
3. **测试身份隔离**：全部破坏性安全测试使用独立测试身份（A/B 及浏览器新建身份），互不污染；测试身份 Token 一律脱敏，报告与仓库文件中不出现任何完整 Token（已 grep 全仓复核）。**通过**

## 二、身份和权限系统

4. **统一后端认证**：新增 `identities` 表；服务端创建匿名身份时签发 256-bit 随机 token（43 字符），仅创建时返回一次，后端只存 sha256 摘要；所有数据接口经 `Authorization: Bearer` 校验摘要；缺失/无效/过期/不匹配 → 401（带 `WWW-Authenticate: Bearer`）；有效 token 但资源非本人 → 403；session_id 不再作为凭据（URL 中携带无 token 一律 401，实测核验）；PowerContext scope 服务端按身份映射，客户端无法用 session_id/scope_id 提权。**通过**
5. **五个已确认漏洞逐一复验**：① GET /api/sessions 公开枚举 → 已删除，仅保留 /me；② 任意会话 id 读他人文档/本地记忆 → 401/403；③ 跨会话 PowerContext 记忆搜索命中他人私有记忆 → scope 按身份隔离，实测新身份召回为空；④ explain IDOR（他人知识点 id）→ 归属校验拒绝；⑤ 跨会话记忆写入 → 拒绝且对方 scope 无变化。**通过**
6. **全局权限评审**：按“全部资源 × 全部动词”清单逐一核验 courses/documents/chunks/chapters/KPs/questions/practice_sessions/attempts/mistakes/mastery/review_tasks/classification_feedback/记忆/explain/search/upload/reclassify，不限于已发现的 5 个入口。**通过**
7. **旧会话受控迁移**：`scripts/migrate_legacy_session.py` 本地管理步骤为旧 session 补建身份（token 仅本地打印一次、只存摘要）；未把旧 session_id 自动转凭据；无未认证 claim 端点；迁移前后快照对比确认无数据丢失；未留后门。**通过**

## 三、自动分类修复

8. **新课程优先级**：标题结构证据优先于弱检索相似（lex_score<0.25 时既有课程不再无条件覆盖）；新课程可自动创建或建议确认；文件名-正文冲突输出明确 reason；用数据结构/概率论/MOS 材料验证。**通过**
9. **候选持久化**：课程/章节候选（名称/分数/来源）、分类依据、状态、分类器版本持久化到 `classify_evidence`；列表接口只读证据、不再合成伪造分数；刷新前后一致（回归测试断言）。**通过**
10. **确认按钮**：`doc.course` 为空（新课程未落库）时回退证据课程/首个候选；确认后正确创建/链接课程、更新分类状态与文档-KP 链接及检索过滤字段；真实错误提示；`window.prompt` 已替换为应用内更正对话框（浏览器实测可用，DB 落库核对通过）。**通过**
11. **跨课程知识点**：术语式小节标题 + 正文证据的通用提取（2–24 字符、≥2 证据页、标题页独立成节）；保留真实文本与页码证据；证据弱时降级人工确认；未发现任何伪造知识点。**通过**

## 四、回归测试

12. **安全回归（16 场景）**：独立身份 A/B 覆盖枚举、跨读文档/记忆/scope、explain IDOR、跨写记忆、无/错 token、他人 practice/review/mistakes 等；每项同时断言拒绝响应 + 无 DB 状态变化 + 无 PowerContext 跨写 + 合法操作正常；`test_auth.py` 28/28 通过。**通过**
13. **分类回归（17 场景）**：MOS PPTX、概率论 MD、数据结构新课程、英文、混合、跨课程 KP、文件名冲突、低置信 pending、候选持久化、suggested 确认、人工更正、重分类后检索+引用、旧演示数据完好（LEGACY_COUNTS 全等）等；单测 26/26 + 回归 17/17 通过。**通过**

## 五、真实浏览器验收（A-J）

14. **端到端流程**：A 自动创建身份 → B 上传/解析/分类/候选 → B2 新课程确认（DB 核对 course 5000007 创建、feedback user_confirmed=1）→ B3 应用内更正（DB 核对章节改写、feedback user_confirmed=0）→ C 检索带页码引用（全文+向量）→ D 练习判分/掌握度/复习任务（题目按 SQL 夹具播种，已如实说明）→ E 错题本/复习计划 → F PowerContext 记忆真实写入+召回 → G 刷新恢复身份与数据 → H 新身份全空 + 旧身份数据完好 + 无 token 401 → I 控制台无 Token、请求 URL 无 Token（仅 Bearer 头）→ J 重置匿名身份（本地凭据清除、服务端数据保留）。证据 `evidence/uat2/browser_e2e_20261108.txt`。**通过**
   - 工具性限制（如实披露）：browser-use 的 click 工具在本页面不触发 React 事件，交互改用 evaluate_script 执行真实 DOM `element.click()`（真实点击 → 真实请求 → DB 落库核对）；新身份题库用 SQL 夹具播种 3 题（题目内容取自上传材料正文）。

## 六、质量门与交付

15. **质量门**：后端 pytest **145/145**（13.80s，2026-11-08 复跑）；ruff check + format --check 全净（70 文件）；前端 tsc --noEmit + vite build 通过（46 modules / 218.41 kB）。开发记录已更新至 `docs/development-log.md` 阶段 7；本轮无 commit/push/PR/Qoder Sites 发布（遵守用户约束）；未声称生产级安全。**通过**

## 结论

15 项全部通过（0 失败、0 跳过）。遗留说明：① 匿名学习应用的 token 存于 localStorage 属既定取舍（重置机制 + 401 自愈 + 无 URL/日志泄露已核验）；② 浏览器自动化 click 工具限制已在证据中披露，不影响应用本身功能判定。
