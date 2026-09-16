# 受控资料扩展运行手册

> 本手册记录阶段五首次真实扩展成功后可重复执行的操作流程。`PROJECT_SPEC.md` 始终是唯一权威开发基线；两者冲突时，以 `PROJECT_SPEC.md` 为准。本手册不是新的项目范围、计划或第二套批准清单。

## 1. 适用范围

仅用于向当前私人化工外贸询盘证据工作台增加经过人工批准的官方制造商 TDS/SDS。它不授权任意上传、无人监督抓取、账号绕过、公开产品目录、第二向量库或新检索架构。

新 PDF 通过预检和进入索引，只表示资料可以参与检索。HDT、Tg、配比、固化制度、认证及其他高风险事实仍须单独人工核验并加入事实白名单，才能进入结构化 `supported` 输出。

## 2. 首次成功扩展确立的原则

1. **先写 golden，后启用资料。** 每个新产品至少有一个精确到产品、文件和物理页的正向 case，并增加防止典型误读的必要负例；已有 case 的询盘、目标文件和目标页不得重建或漂移。
2. **资料外置，Git 只保存轻量清单。** PDF 留在批准资料根目录；仓库保存相对路径、版本、地区、启用状态、SHA-256、来源 URL 和获取日期。
3. **先隔离、再审批。** 普通 HTTPS 直接下载优先，文件先放在正式资料根目录之外。只有普通下载确实不可用时才考虑最小浏览器辅助工具，不能绕过登录、验证码、付费墙、许可或访问控制。
4. **单一事实来源。** 入库、索引元数据、状态检查和 PDF 查看器都读取 `materials_catalog.json`，不得恢复固定产品列表或第二套日期/地区映射。
5. **全量暂存重建。** 当前语料规模继续使用一个 multilingual-e5-small + Chroma 索引；新索引在同一父目录的暂存目录构建，完整性和 golden gate 通过后才切换。
6. **失败不破坏正式索引。** 构建或验证失败时删除暂存目录并保留原索引；成功切换后只保留一个可交换的 `.backup`。
7. **状态必须识别漂移。** 索引保存启用清单全部审批元数据的指纹；`ready` 要求清单指纹与索引一致。查询、结构化分析和 UI 缓存结果也必须绑定该指纹；仅有索引目录并不等于可用。

这些做法借鉴了成熟项目的已验证模式，而没有安装不需要的平台：

- DVC：大型资料留在 Git 外，版本库保存轻量元数据和可复现关系：<https://github.com/iterative/dvc>
- Hugging Face Hub：修订快照、校验和、临时下载后验证：<https://github.com/huggingface/huggingface_hub/blob/main/docs/source/en/guides/cli.md>
- The Update Framework：目标文件元数据、哈希、版本和回滚保护思想：<https://github.com/theupdateframework/specification/blob/master/tuf-spec.md>
- pip：暂存与缓存位于同一文件系统，避免跨文件系统切换和并发替换问题：<https://github.com/pypa/pip/blob/main/NEWS.rst>

## 3. 扩展前检查

```powershell
cd "F:\外贸化工"
git status --short --branch
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m chemical_trade_copilot.cli status `
  --catalog materials_catalog.json --database .chroma
```

开始前必须满足：工作树差异已理解；当前测试通过；状态为 `ready`；资料来源是公开、可追溯的制造商页面；候选文件尚未放入正式资料根目录。

## 4. 获取与隔离审查

1. 记录产品页、TDS/SDS 直接 URL 和获取日期。
2. 用普通浏览器或直接 HTTPS 下载到正式资料根目录之外的待审目录。
3. 计算 SHA-256，检查文件可读性、物理页数、文本可提取性、文件内产品身份、版本/日期和管辖地区。
4. 文件若使用缩写、商标名或产品代码，必须确认与拟批准产品的对应关系；不得靠宽松模糊匹配猜测。
5. 遇到账号、验证码、付费墙或许可限制时停止并更换公开候选，不尝试绕过。

## 5. Golden 与人工批准门槛

在移动文件和设置 `enabled: true` 前：

1. 在 `tests/fixtures/golden_retrieval_cases.json` 增加正向 retrieval case；
2. 对闪点/储存温度冒充连续使用温度、认证越界等真实风险增加负例；
3. 运行相关 evaluator 测试，确认新增 case 在资料未启用时不会改变原产品 gate；
4. 向用户列明产品、文件、版本/日期、地区、URL、哈希、正向目标页和负例；
5. 获得明确人工批准。

不得用修改原有目标页或降低 Top 3 门槛的方式让新扩展通过。

## 6. 正式启用

人工批准后，把确切文件复制到批准资料根目录下的产品子目录。随后在 `materials_catalog.json` 为当前 TDS/SDS 各增加一条启用记录。字段包括：

- `product`
- `relative_path`
- `document_type`
- `date_revision`
- `jurisdiction`
- `enabled`
- `sha256`
- `source_url`
- `acquired_on`
- 可选 `document_identity`：仅当文件正文使用与清单产品名不同的明确代码/别名时使用；该字符串必须真实出现在正文中。

每个启用产品必须恰好有一份 TDS 和一份 SDS。旧版本可以留在清单中，但必须设置 `enabled: false`。

## 7. 预检、重建与验证

```powershell
.\.venv\Scripts\python.exe -m chemical_trade_copilot.cli preflight `
  --materials-root "G:\桌面\化工" --catalog materials_catalog.json

.\.venv\Scripts\python.exe -m chemical_trade_copilot.cli rebuild `
  --materials-root "G:\桌面\化工" `
  --catalog materials_catalog.json `
  --database .chroma `
  --golden-cases tests\fixtures\golden_retrieval_cases.json

.\.venv\Scripts\python.exe -m chemical_trade_copilot.cli status `
  --catalog materials_catalog.json --database .chroma

.\.venv\Scripts\python.exe -m chemical_trade_copilot.cli verify `
  --catalog materials_catalog.json `
  --database .chroma `
  --golden-cases tests\fixtures\golden_retrieval_cases.json
```

验收必须同时满足：

- 预检中的产品、文件和物理页数量符合人工记录；
- `rebuild` 返回 `active_index_replaced`；
- `status` 返回 `ready` 且 `rollback_available` 为 `true`；
- 所有适用正向 golden case 在 Top 3 内命中；
- 新产品普通查询命中批准的目标文件和物理页；
- PDF 查看器展示同一清单中的产品、文件、物理页、日期/修订和地区；
- 原有阶段四演示案例不退化。

## 8. 回滚与恢复

```powershell
.\.venv\Scripts\python.exe -m chemical_trade_copilot.cli rollback --database .chroma
.\.venv\Scripts\python.exe -m chemical_trade_copilot.cli status `
  --catalog materials_catalog.json --database .chroma
```

回滚会交换当前索引和唯一备份。若当前清单仍是新版本，状态应明确显示 `index_catalog_mismatch`，不能误报 `ready`。此时有两种受控恢复方式：

- 问题只在新索引且需要回到新版本：修复后重新执行完整 `rebuild`；
- 演练或确认旧索引无误后前滚：再次执行 `rollback` 交换回已验证的新索引，然后运行 `status` 和 `verify`。

若决定长期退回旧资料版本，还必须通过正常 Git 变更恢复上一版清单，再重新运行预检、状态和对应 golden gate；不要手工修改 Chroma 内容。

若状态显示 `index_recovery_required`，说明目录切换曾被进程终止或文件系统错误打断。此时不得删除 `.staging`、`.rollback`、`.recovery` 或 `.backup`，也不得继续重建；先保留全部目录和命令输出，由开发会话按受管标记及生命周期测试确定恢复动作。正常的已捕获回滚失败会自动尽力恢复原 active/backup；下一次 `rollback` 也会先恢复被搁置的受管 backup。

## 9. 完成与复杂度自省

最终运行全量测试、依赖检查、wheel 构建和真实来源页查看。然后逐项回答：

- 新增代码是否只解决了本次可复现失败或明确验收要求？
- 是否仍只有一份清单、一个 E5、一个 Chroma 和一次受控全量重建？
- 是否没有新增账号、后台、上传、爬虫、第二数据库、BM25、RRF、重排器或 Agent？
- 是否如实披露旧资料、地区限制、产品开发/实验用途等来源限制？
- 是否保持“新资料可检索”与“高风险事实已核验”两件事严格分离？

全部满足后，更新 `PROJECT_SPEC.md`、`TASK_STATUS.md` 和 `HANDOFF.md`，提交并推送，然后立即停止，不自动开始下一阶段。

## 10. 首次成功样例：BAER XP9500

2026-07-28 首次真实扩展使用 ACS Technical Products 的 BAER XP9500 官方 TDS/SDS。普通直接下载可用，因此没有创建浏览器插件。两份资料从隔离待审区经人工批准后加入正式目录；SDS 正文只写 `XP-9500, XP-2500`，因此清单显式声明 `document_identity: "XP-9500"`，预检仍要求该代码真实出现在正文中。

扩展后共有 3 个产品、6 份文件、45 个物理页；5 个正向 golden case 全部在 Top 3 命中。真实回滚后状态正确报告新清单与旧索引不一致，再次交换恢复新索引后状态回到 `ready` 且 gate 再次通过。

BAER 资料明确写有“Under Product Development”和“FOR EXPERIMENTAL USE ONLY”。其 310–315°C 闪点和储存限制不得解释为连续使用温度；本次没有为 BAER 新增任何高风险人工核验事实。
