# 保留说明：本目录是化工询盘台「双语版」的唯一正式基线

本目录建立于 2026-09-16，目的是把此前**没有任何版本控制**的一份可用实现，固定为受 Git 管理的正式基线。

## 1. 来源

| 项 | 值 |
|---|---|
| 来源路径 | `F:\半导体材料产品展示\.worktrees\technical-review-o1` |
| 来源记录的 Git 分支 | `codex/technical-review-o1` @ `79c1cab`（来自该目录内的 `CURRENT_WORK.md`） |
| 来源 `.git` 内容 | `gitdir: F:/外贸化工/.git/worktrees/technical-review-o1` |
| 问题 | 该 gitdir 路径**已不存在**（原仓库 `F:\外贸化工` 已改名/迁移为 `F:\半导体材料产品展示`），因此来源目录**无法执行任何 Git 操作**，其中的"大量未提交改动"只以散文件形式存在 |

来源目录内的 `CURRENT_WORK.md` 原文记录：

> Branch `codex/technical-review-o1` is at `79c1cab` with substantial uncommitted application changes from the completed UI/review stages; **they must be preserved**.

本目录即为该要求的落地。

## 2. 内容完整性

- 共保留 **63 个文件**，与来源逐文件 **SHA256 全部一致**（0 不一致）。
- 校验清单见 `MANIFEST.sha256`。
- 唯一未复制的是来源中失效的 `.git` 指针文件。

## 3. 刻意排除的内容及原因

| 排除项 | 原因 |
|---|---|
| `.env.local` | 可能含密钥/凭据，**不得进入任何副本或版本控制** |
| `.vercel/` | Vercel 本机授权状态，属机器本地私密状态 |
| `.chroma/` | 来源中的索引为**空索引**（0 页、无清单指纹），不可用 |
| `deploy/` | 6.45 MB 的 Vercel 部署用 PDF 与索引打包；正式资料根按设计位于仓库外，副本无需重复 |
| `output/`、`tmp/`、`.playwright-cli/`、`__pycache__/`、`.pytest_cache/` | 运行与临时产物，可重建 |
| `.git` 文件 | 指向已不存在的路径，无意义 |

## 4. 运行前提（本副本不含索引）

- Python `>=3.11,<3.14`，依赖见 `pyproject.toml`（Streamlit 1.60 等）。
- 正式资料根：`G:\桌面\化工`（含 TDS/SDS 的 6 份已批准 PDF）。
- **需要一份清单指纹匹配的 Chroma 索引**：本副本未包含索引。可用 `chemical_trade_copilot.cli rebuild` 按 `materials_catalog.json` 重建，或指向已存在的匹配索引。
- 启动入口：`src/chemical_trade_copilot/streamlit_app.py`；语言由 `?lang=en` / `?lang=zh-CN` 或界面选择框控制。
- 需要环境变量 `DEEPSEEK_API_KEY`。

## 5. 已知缺陷（保持原样记录，未修正）

1. **思考模式未关闭 + 无显式超时**：`inquiry_analysis.py` 的 `DeepSeekJsonClient` 使用 `max_tokens=6000`，而 DeepSeek 思考模式默认开启且思考内容与答案共用该预算。实测一次分析调用出现 `finish_reason=length`、`content` 为空，应用重试整轮后降级为"证据不足"，单次最长约 6 分钟且产出为零。修复方式（已在 `F:\半导体材料产品展示` 验证）：显式 `extra_body={"thinking": {"type": "disabled"}}`，并给 SDK 设置显式 `timeout` 与 `max_retries=0`。
2. **本地化缺口**：中文界面中仍出现英文文案（如页脚 `Evidence scope: approved … documents only. Document dates and jurisdictions remain limitations.`）；英文界面中出现硬编码中文（翻译进度提示 `正在翻译当前分析，原始证据和专家决定保持不变……`）；分析进度提示为硬编码英文。相关字符串见 `streamlit_app.py` L142、L1539 与 `inquiry_review.py` 的 `support_statement`。
3. **候选选择器与检索范围绑定**：`inquiry_review.py` 的 `_internal_candidates()` 只按**本次检索命中**（`limit=3`）分组生成候选，因此该下拉通常只有 1 项，且不含目录内其他产品。
