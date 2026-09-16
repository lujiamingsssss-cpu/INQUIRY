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

## Unique Next Action

核对模块依赖图，确认待删模块（review_workspace / review_email / review_email_generation /
review_translation）没有被保留模块依赖，然后开始改造。
