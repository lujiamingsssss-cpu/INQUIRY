# Current Work: 化工询盘台改造为「业务员一次性工具」

## Objective

在 `F:\化工询盘台`（双语版唯一正式基线）上去掉审阅工作流的形式主义，做成业务员肯用的一次性工具：
输入询盘 → 证据约束的结论 → 导出 → 关闭，**不持久化任何数据**。

## Active Scope

保留并强化：证据门禁与失败关闭、来源页查看（真实 PDF 物理页）、已核验事实卡（条件绑定）、四态决策行、
复核卡中的询盘事实/歧义/边界/追问、英文邮件草稿、**导出**。

删除：审阅工作区与状态持久化、记录页与修订哈希、备份/恢复、打印页、决定页与内部候选下拉、
机器翻译、8 页编号导航、Vercel/Docker 部署件。

新增：单页界面；内存生成 Markdown 与可打印 HTML 导出；进度提示说人话。

界面语言：保留双语静态文案，清除硬编码中英混排（含英文界面里的中文翻译提示）。

## Non-goals

- 不改 UI 设计语言：`ui_components.APP_CSS` 逐字节不动。
- 不改解析链：`inquiry_analysis.py` 的门禁、白名单、事实绑定、提示词；`retrieval.py`/`materials.py`/`pdf_pages.py`。
- 不为省钱削减送入分析模型的证据集合（`merge_ranked_with_corpus` 行为不变）。
- 不做存储、账号、云端服务、多用户、历史记录。

## Authoritative State

- 仓库：`F:\化工询盘台`；`main` = 保留基线 `70a9227`；工作分支 `rework/one-shot`。
- 远端：`https://github.com/lujiamingsssss-cpu/INQUIRY`（推送已验证可用）。
- 基线来源与已知缺陷见 `PRESERVATION.md`。

## Approval and Rollback

- 人工批准：去形式主义 + 一次性工具 + 不存数据 + 支持导出 + UI 风格不变 —— 用户已明确批准。
- 回滚：`git checkout main`；基线完整且逐字节可复现。

## Complexity Budget

- 允许改动：`workflow.py`、`streamlit_app.py`、`localization.py`、`inquiry_analysis.py`（仅 API 客户端参数）、
  新增 `export_bundle.py` 及对应测试。
- 禁止：新依赖、新服务、新持久化、第二套解析链、新增审批流程。

## Temporary Artifacts

- 无长期临时产物。验证用截图与探针脚本置于系统临时目录，任务收口时删除。
- `deploy/`、`.chroma/`、`.env.local`、`.vercel/` 等本机/部署产物未纳入版本控制，见 `.gitignore`。

## Progress

- 已删除：`review_workspace` / `review_email` / `review_email_generation` / `review_translation`
  及其测试、`Dockerfile.vercel`、`.dockerignore`。
- 已内联解析链（`workflow.py`），门禁模块 `inquiry_analysis.py` 仅改 API 客户端参数。
- 已新增 `export_bundle.py`（内存生成 Markdown 与可打印 HTML）与单页 `streamlit_app.py`。
- 已修本地化缺口：中英混排、`公开演示`/Vercel 措辞、硬编码进度提示。
- 已移除对分析结果无影响的目标市场下拉（装饰性输入）。
- 测试 164 项全绿（含新增 `test_export_bundle.py`、重写的 `test_streamlit_app.py` 与
  `test_localization.py`、`test_workflow.py`）。
- 已提交并推送：`2d7e68b`、`4ba99f0`（分支 `rework/one-shot`）。
- **真实端到端验证已通过**（2026-09-17，真模型 + 真索引，未打任何运行时补丁）：
  - 正向询盘（MPDA/HDT）23.8s → 结论、四态决策行、条件绑定的已核验事实卡、来源物理页齐全；
  - 负向询盘（200°C 连续使用 + 食品接触）29.9s → 不推荐产品、无已核验参数卡；
  - 导出：Markdown 2 558 B、可打印 HTML 13 890 B，内容含结论/决策行/参数条件/来源/询盘事实/边界/回复草稿；
  - **不落盘**：运行前后仓库文件数 92 → 92，无任何新增或删除；
  - 中文界面无英文残留（不再出现 `Public demo` / `Evidence scope`），进度提示已本地化；
  - UI 设计语言与基线一致（截图与两个导出样例见 `G:\桌面\单页版验证`）。
- 已知环境缺口：本仓库**尚无自己的虚拟环境**，验证时借用 `F:\半导体材料产品展示\.venv`。
  这是拆分后仍残留的隐式耦合，需为本仓库建立独立环境后才算真正独立。

## Unique Next Action

**等待人工检查**（用户明确要求验证通过后先不合并）。人工确认后收口：
将 `rework/one-shot` 合并到 `main`、删除该分支、删除本文件；同时评估为本仓库建立独立虚拟环境。


