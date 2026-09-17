# Current Work: 化工询盘台改造为「业务员一次性工具」

**Status: 进行中**（已核验结论缓存已实现并验证；仍待用户人工检查后才合并）
**Branch**: `rework/one-shot`　**Remote**: `github.com/lujiamingsssss-cpu/INQUIRY`　**Repo**: `F:\化工询盘台`

## Objective

把双语版工作台改造成业务员肯用的一次性工具：输入询盘 → 证据约束的结论 → 导出 → 关闭。
**不保留询盘记录**；已核验结论在本机缓存，使同一条询盘给出同一结论（见下）。

## Active Scope（除"待办"外均已完成）

- 单页化：删除 8 页导航、审阅记录/修订哈希、备份恢复、打印页、决定页与内部候选下拉、
  逐页机器翻译；删除 `review_workspace` / `review_email` / `review_email_generation` /
  `review_translation` 及其测试。
- 解析链不变：`workflow` 内联回「检索 → 证据合并 → 门禁分析」三步，送入模型的证据集合不裁剪；
  `inquiry_analysis` 仅改 API 客户端参数（关闭思考模式 + 45s 超时 + `max_retries=0`）。
- 保留复核卡（询盘事实 / 歧义 / 边界 / 追问，纯本地计算，零模型调用）。
- 导出：内存生成 Markdown 与可打印 HTML。
- UI 语言不变：`APP_CSS` 原有规则未改，仅**新增** `.st-key-ctc_source_layout` 一条布局规则
  （用户明确要求来源页左右分栏）。
- 来源页：缩略图去边框去底色、贴左并按自身宽度；文件信息与操作占满右栏；
  新增本地化键 `source.open_original`。
- 本地化缺口修复：中英混排、`公开演示`/Vercel 措辞、硬编码进度提示、英文按钮。
- 独立环境：`.venv`（Python 3.11.9）+ 依赖齐备 + **本仓库自己的索引** `.chroma`
  （45 页、`status=ready`、golden gate 7 例 hit@3=1.0）。
- 双击启动脚本 `启动化工询盘台.bat`（CRLF / 纯 ASCII / 无 BOM）、`README.md`、`.env.example`。
- 应用自己读取 `.env.local`（`utf-8-sig`，兼容 BOM），不再依赖脚本解析配置。
- 代理环境兼容修复：`chemical_trade_copilot.__init__.sanitize_no_proxy`。
- **已核验结论缓存**（`answer_cache.py`，用户批准：内部规则、不作为面向使用者的存储功能）：
  只缓存**通过门禁**的结论；命中时**零模型调用**，但用缓存的检索计划在本地重跑检索并核对证据身份；
  资料指纹 / 模型名 / 结构版本变化即失效；界面不提供历史浏览与导出；删一个文件即清空。
- 把"本次模型输出未通过校验（可重试）"与"资料不足"在界面上**分开表述**
  （新增 `guardrail.eyebrow/headline/body`），避免业务员误以为公司缺资料。
- 失败不再静默：`_render_entry_content` 的兜底异常会向 stderr 打印类型与信息，便于诊断。
- 测试 **188 项全绿**（使用本仓库 venv 运行）。

## Non-goals

- 不改解析链：门禁、事实白名单、条件绑定、提示词、检索与资料模块。
- 不新增依赖、服务、审批流程；不提供面向使用者的记录/历史/备份功能。

## Authoritative State

- `rework/one-shot` 为本次改造分支，最新提交见 `git log`（与本文件同批提交）。
- `main` = 保留基线（`70a9227`、`47109fa`）。**尚未合并**——用户要求先人工检查。
- 远端 `main` 与 `rework/one-shot` 均已推送，工作区干净。

## Approval and Rollback

- 已批准：去形式主义、做成一次性工具、不存数据、支持导出、UI 风格不变、
  建独立虚拟环境与启动脚本、来源页布局调整。
- **明确未批准：合并到 `main`**（用户："跑完先不要合并，先人工检查"）。
- 回滚：`git checkout main`，或 `git reset --hard 70a9227`。

## Latest Verification（真实模型 + 真索引，本仓库 venv）

- 正向询盘（MPDA/HDT）：`supported`，21–24 秒；结论、四态决策行、条件绑定事实卡、来源原页齐全。
- 负向询盘（200°C 连续使用 + 食品接触）：`insufficient`，不推荐产品、无参数卡。
- 导出：Markdown 2 558 B、可打印 HTML 13 890 B。
- **不落盘**：运行前后仓库文件数 92 → 92。
- golden 门禁：7 例，hit@3 = 1.0；`pip check` 无破损依赖。
- 证据与截图：`G:\桌面\单页版验证`（中英各 9 张 + 两个导出样例）。
- **稳定性实测**（同一询盘、同一索引、同一模型）：索引检索连续 3 次签名相同（1 种）；
  命中页面 6/6 相同；**模型原始输出 6/6 各不相同**。即不稳定的是文字表达，不是索引。
- **缓存决定性验证**：以**无效密钥**启动的实例，对同一条询盘仍给出 `supported`
  （14.1s，命中缓存），而换一条新询盘立刻 `error`（15.0s）——证明命中路径**零模型调用**，
  且密钥确实无效。真密钥实例上命中用时 12.3s（完整分析约 23s）。
- 缓存内容体检：无 `sk-`、无 `DEEPSEEK_API_KEY`，字段仅 key/inquiry/model/search_query/
  document_types/evidence/analysis_json/created_at；文件已被 Git 忽略。

## Known Behaviour（不是回归，但需要产品决策）

门禁对模型输出做确定性校验。实测 10 次采样中 1 次被拒，原因：

```
temperature values are allowed only in verified key parameters
```

即模型把温度值写进了自由叙述，而非只放在已核验参数对象里。被拒后应用重试一次，
仍不合格即降级。**已做两件事降低其危害**：①缓存让同一条询盘的重复提问稳定得到同一结论；
②把"本次未通过校验（可重试）"与"资料不足"在界面上分开表述。
**仍未做**：收紧系统提示词以降低首次被拒率——那会改动解析链提示词，需另行验证，留待用户决定。

## Pitfalls（新会话必读，避免重复踩）

1. **`NO_PROXY` 含方括号 IPv6（如 `[::1]`）会让 httpx 构造客户端抛 `InvalidURL`**，
   表现为向量模型加载与模型 API 调用整体失败（命令行重建索引崩溃、启动脚本一启就报错）。
   已由 `chemical_trade_copilot.__init__` 在导入时清洗；不要在别处再用原始取值起进程。
2. **批处理脚本必须 CRLF**；`if (...)` 块内的 `echo` 文本不得含未转义括号
   （曾因 `Build it first (see README.md):` 的 `)` 提前闭合块而报 `': was unexpected'`）；
   Streamlit 首次运行邮箱提示需 `server.showEmailPrompt=false`，否则双击启动会卡住。
3. **`.env.local` 若带 UTF-8 BOM，批处理 `for /f` 会把首行键名读错且不报错**。
   配置已改由应用读取（`utf-8-sig`）；不要退回脚本解析。
4. **Streamlit 主区域是内部滚动容器**，Playwright `fullPage` 截图会被截断在视口高度；
   需注入 CSS 解除内部滚动（脚本：`C:\Users\HUGO\AppData\Local\Temp\ctc_full_shots.js`）。
5. 本仓库 `.chroma` 不入 Git；干净检出上必须先 `cli rebuild` 才有索引。
6. `.worktrees/technical-review-o1` 无有效 Git 元数据，且其 `.env.local` **含凭据**，
   不得复制、提交或外发。
7. 覆盖桌面截图前确认图片未被看图工具占用，否则写入报 `UNKNOWN: unknown error`；
   稳妥做法是先截到临时目录再复制。
8. **界面眉标经 CSS 转大写**，Playwright 断言必须忽略大小写——用小写 `Evidence validated`
   匹配会永远不成立，表现为"白等 300 秒后其实早已成功"（本次踩了两次）。
9. 兜底 `except Exception` 会吞掉真实原因；排查"分析无法完成"时先看 stderr 的
   `[chemical-trade-copilot] analysis failed:` 一行。

## Temporary Artifacts

- 系统临时目录中的 `ctc_*.py`、`ctc_*.js`、`ctc_oneshot_verify\`、`ctc_*_shots\`：
  本次任务的探针与截图脚本，可删。
- `.cache/verified_answers.json`：已核验结论缓存（无凭据），已被 Git 忽略；删除即清空。
- `F:\化工询盘台\.env.local`：本机配置（**含密钥**），已被 Git 忽略，不要提交或外发。
- `F:\化工询盘台\.chroma`：本机索引，可重建，不入 Git。

## Verification Commands

```powershell
cd F:\化工询盘台
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m chemical_trade_copilot.cli status --catalog materials_catalog.json --database .chroma
# 或直接双击：启动化工询盘台.bat
```

## Unique Next Action

**等待用户人工检查**（已明确要求"先不要合并"）。检查通过后：把 `rework/one-shot` 合并到 `main`、
删除该分支、删除本文件；并按上文 Known Behaviour 决定是否收紧提示词以降低被拒率。
